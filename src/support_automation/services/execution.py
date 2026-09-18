"""Executes AUTO-tier recommended actions (create_linear_issue,
notify_support_channel) against real Linear/Slack through Arcade's direct
tool-execution API (`arcadepy`).

This is the only place in the codebase that talks to Arcade directly
outside of the MCP server (`server.py`), and it never holds a raw Slack
or Linear token — only ARCADE_API_KEY, which Arcade uses to run the
already-authorized `Linear.CreateIssue` / `Slack.SendMessage` tools on
this service's behalf. Per CLAUDE.md's automation policy, only actions
the recommender already marked `execution="automatic"` are run — nothing
here can promote an APPROVAL_REQUIRED or HUMAN_ONLY action to automatic.

Optional by design: if ARCADE_API_KEY, LINEAR_TEAM, or SLACK_CHANNEL is
not configured, the corresponding action is reported as "skipped" rather
than raising. Classification must keep working with zero third-party
credentials (see CLAUDE.md), and this module never blocks that.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.execution import ExecutionResult
from support_automation.models.routing import (
    ActionRecommendation,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import Severity, SupportTicket

_EXECUTABLE_ACTIONS = {"create_linear_issue", "notify_support_channel"}

_LINEAR_PRIORITY_BY_SEVERITY = {
    Severity.P1: "urgent",
    Severity.P2: "high",
    Severity.P3: "medium",
    Severity.P4: "low",
}


class ArcadeToolClient(Protocol):
    """The slice of `arcadepy.Arcade` this module needs — narrowed so tests
    can inject a fake without depending on the real SDK or network."""

    tools: Any


def _default_client() -> ArcadeToolClient | None:
    api_key = os.environ.get("ARCADE_API_KEY")
    if not api_key:
        return None
    from arcadepy import Arcade

    return Arcade(api_key=api_key)


def _linear_description(
    ticket: SupportTicket,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
) -> str:
    reported = severity.reported_severity.value if severity.reported_severity else "not reported"
    lines = [
        f"**Ticket:** {ticket.ticket_id} — "
        f"{ticket.customer_name or ticket.customer_id or 'Unknown customer'}",
        "",
        f"**Severity:** Customer reported {reported}; "
        f"system-recommended **{severity.recommended_severity.value}**.",
    ]
    lines += [f"- {reason}" for reason in severity.reasoning]
    lines += ["", f"**Domain:** {', '.join(enrichment.domains) or 'none detected'}"]

    if enrichment.possible_causes:
        lines += ["", "**Most likely cause:**"]
        for cause in enrichment.possible_causes:
            lines.append(f"- {cause.cause} (confidence {cause.confidence:.0%})")
            lines += [f"  - {ev}" for ev in cause.evidence]

    if enrichment.customer_hypotheses:
        quoted = "; ".join(enrichment.customer_hypotheses)
        lines += ["", f'**Customer hypothesis (not treated as fact):** "{quoted}"']

    if enrichment.correlated_recent_changes:
        lines += ["", "**Correlated recent change (investigation lead, not a confirmed cause):**"]
        lines += [f"- {change}" for change in enrichment.correlated_recent_changes]

    if enrichment.uncorrelated_recent_changes:
        lines += ["", "**Explicitly NOT implicated (no evidence links these to the signal):**"]
        lines += [f"- {u.change}" for u in enrichment.uncorrelated_recent_changes]

    lines += [
        "",
        f"**Routing:** {routing.queue} / {routing.owner} "
        f"(matched rule: {routing.matched_rule}, confidence {routing.routing_confidence:.0%})",
        "",
        "_Created automatically by the support automation portal (AUTO-tier action)._",
    ]
    return "\n".join(lines)


def _slack_message(
    ticket: SupportTicket,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
    linear_url: str | None,
) -> str:
    customer = ticket.customer_name or ticket.customer_id or "Unknown customer"
    lines = [
        f":rotating_light: *New support automation routing — {ticket.ticket_id} ({customer})*",
        "",
        f"*Issue:* {ticket.subject or ticket.description or '(no subject)'}",
        f"*Recommended severity:* {severity.recommended_severity.value}",
    ]
    if enrichment.possible_causes:
        top = enrichment.possible_causes[0]
        lines.append(f"*Likely cause:* {top.cause} ({top.confidence:.0%} confidence)")
    lines.append(f"*Route:* {routing.queue} / {routing.owner}")
    if linear_url:
        lines += ["", f"Investigation issue: {linear_url}"]
    return "\n".join(lines)


class _ToolRun:
    """Outcome of one `tools.execute` call. Deliberately not a pre-flight
    authorize() check — an earlier version of this module called
    `client.tools.authorize()` before every execute() to decide whether to
    run at all, but that call proved unreliable in practice: it kept
    reporting a stale "needs_authorization" for an already-authorized
    user/tool pair (confirmed independently authorized via
    `client.auth.start()`, and confirmed working via a direct
    `tools.execute()` call) rather than reflecting the tool's real,
    current authorization state. `execute()` itself is the source of
    truth: on success it runs the tool; when the grant is genuinely
    missing, Arcade signals that through `output.authorization` on the
    execute response itself rather than requiring a separate check."""

    def __init__(self, ok: bool, value: dict | None, error: str | None, auth_url: str | None):
        self.ok = ok
        self.value = value
        self.error = error
        self.auth_url = auth_url


def _run_tool(client: ArcadeToolClient, tool_name: str, user_id: str, input_: dict) -> _ToolRun:
    from arcadepy import ArcadeError

    try:
        response = client.tools.execute(tool_name=tool_name, input=input_, user_id=user_id)
    except ArcadeError as exc:
        # A bad/expired ARCADE_API_KEY, a network blip, or Arcade being
        # unreachable must degrade this one action to "failed", not crash
        # the whole classify request -- classification has to keep working
        # even when Arcade itself is misconfigured or down.
        return _ToolRun(False, None, str(exc), None)

    output = response.output
    if response.success:
        value = output.value if output else None
        return _ToolRun(True, value if isinstance(value, dict) else None, None, None)

    authorization = getattr(output, "authorization", None) if output else None
    if authorization and getattr(authorization, "status", None) != "completed":
        return _ToolRun(False, None, None, getattr(authorization, "url", None))

    error = output.error.message if output and output.error else None
    return _ToolRun(False, None, error or "Unknown error", None)


def execute_auto_actions(
    ticket: SupportTicket,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
    recommendation: ActionRecommendation,
    *,
    client: ArcadeToolClient | None = None,
) -> list[ExecutionResult]:
    """Run whichever of `recommendation.actions` this module knows how to
    execute for real (create_linear_issue, notify_support_channel), and
    only those marked `execution="automatic"`. Everything else — including
    APPROVAL_REQUIRED actions like request_google_reauthorization — is
    left untouched; this function has no way to execute them and must not
    grow one without a corresponding change to the automation policy."""
    auto_actions = {
        a.action for a in recommendation.actions if a.execution == "automatic"
    } & _EXECUTABLE_ACTIONS
    if not auto_actions:
        return []

    resolved_client = client if client is not None else _default_client()
    if resolved_client is None:
        return [
            ExecutionResult(
                action=action,
                status="skipped",
                detail="ARCADE_API_KEY not configured; execution skipped.",
            )
            for action in sorted(auto_actions)
        ]

    user_id = os.environ.get("ARCADE_USER_ID", "support-portal")
    results: list[ExecutionResult] = []
    linear_url: str | None = None

    if "create_linear_issue" in auto_actions:
        team = os.environ.get("LINEAR_TEAM")
        if not team:
            results.append(
                ExecutionResult(
                    action="create_linear_issue",
                    status="skipped",
                    detail="LINEAR_TEAM not configured; execution skipped.",
                )
            )
        else:
            title = (
                f"{ticket.subject or ticket.description or 'Support ticket'} — "
                f"{ticket.customer_name or ticket.customer_id or ticket.ticket_id}"
            )
            run = _run_tool(
                resolved_client,
                "Linear.CreateIssue",
                user_id,
                {
                    "team": team,
                    "title": title,
                    "description": _linear_description(ticket, enrichment, severity, routing),
                    "priority": _LINEAR_PRIORITY_BY_SEVERITY.get(
                        severity.recommended_severity, "none"
                    ),
                },
            )
            if run.ok:
                linear_url = (run.value or {}).get("issue", {}).get("url")
                results.append(
                    ExecutionResult(
                        action="create_linear_issue",
                        status="executed",
                        detail=linear_url or "Issue created.",
                    )
                )
            elif run.auth_url:
                results.append(
                    ExecutionResult(
                        action="create_linear_issue",
                        status="needs_authorization",
                        detail=run.auth_url,
                    )
                )
            else:
                results.append(
                    ExecutionResult(action="create_linear_issue", status="failed", detail=run.error)
                )

    if "notify_support_channel" in auto_actions:
        channel = os.environ.get("SLACK_CHANNEL")
        if not channel:
            results.append(
                ExecutionResult(
                    action="notify_support_channel",
                    status="skipped",
                    detail="SLACK_CHANNEL not configured; execution skipped.",
                )
            )
        else:
            run = _run_tool(
                resolved_client,
                "Slack.SendMessage",
                user_id,
                {
                    "channel_name": channel,
                    "message": _slack_message(ticket, enrichment, severity, routing, linear_url),
                },
            )
            if run.ok:
                results.append(
                    ExecutionResult(
                        action="notify_support_channel",
                        status="executed",
                        detail=f"Posted to #{channel.lstrip('#')}.",
                    )
                )
            elif run.auth_url:
                results.append(
                    ExecutionResult(
                        action="notify_support_channel",
                        status="needs_authorization",
                        detail=run.auth_url,
                    )
                )
            else:
                results.append(
                    ExecutionResult(
                        action="notify_support_channel", status="failed", detail=run.error
                    )
                )

    return results
