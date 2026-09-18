"""Tests for support_automation.services.execution.

Uses a fake Arcade client (no network, no real SDK) so these stay fast
and deterministic while still exercising the real branching logic:
missing config, needs-authorization, success, and failure.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from support_automation.models.routing import ActionRecommendation, RecommendedAction
from support_automation.models.ticket import SupportTicket
from support_automation.services.enricher import RuleBasedEnricher
from support_automation.services.execution import execute_auto_actions
from support_automation.services.router import route_ticket
from support_automation.services.severity import recommend_severity

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENRICHER = RuleBasedEnricher()


def _hero_context():
    ticket = SupportTicket(**json.loads((_REPO_ROOT / "data" / "hero_ticket.json").read_text()))
    enrichment = _ENRICHER.enrich(ticket)
    severity = recommend_severity(ticket, enrichment)
    routing = route_ticket(ticket, enrichment)
    recommendation = ActionRecommendation(
        actions=[
            RecommendedAction(action="create_linear_issue", risk="low", execution="automatic"),
            RecommendedAction(action="notify_support_channel", risk="low", execution="automatic"),
            RecommendedAction(
                action="request_google_reauthorization", risk="low", execution="human_approval"
            ),
        ],
        actions_rejected=[],
    )
    return ticket, enrichment, severity, routing, recommendation


class _FakeAuthorization:
    def __init__(self, status, url):
        self.status = status
        self.url = url


class _FakeExecuteResponse:
    def __init__(self, success, value=None, error_message=None, authorization=None):
        self.success = success
        error = SimpleNamespace(message=error_message) if error_message else None
        self.output = SimpleNamespace(value=value, error=error, authorization=authorization)


class _FakeTools:
    """Mirrors arcadepy: authorization state is only ever learned from an
    execute() response's `output.authorization`, never a separate
    pre-check — see the comment on `_ToolRun` in execution.py for why."""

    def __init__(self, authorized=True, linear_url="https://linear.app/x/issue/DON-1"):
        self.authorized = authorized
        self.linear_url = linear_url
        self.executed = []

    def execute(self, *, tool_name, input, user_id):
        self.executed.append((tool_name, input))
        if not self.authorized:
            return _FakeExecuteResponse(
                success=False,
                authorization=_FakeAuthorization(
                    status="pending", url=f"https://arcade.dev/authorize/{tool_name}"
                ),
            )
        if tool_name == "Linear.CreateIssue":
            return _FakeExecuteResponse(
                success=True, value={"issue": {"url": self.linear_url}}
            )
        if tool_name == "Slack.SendMessage":
            return _FakeExecuteResponse(success=True, value={"ok": True})
        raise AssertionError(f"unexpected tool: {tool_name}")


class _FakeClient:
    def __init__(self, **kwargs):
        self.tools = _FakeTools(**kwargs)


def test_skips_when_no_client_configured(monkeypatch):
    monkeypatch.delenv("ARCADE_API_KEY", raising=False)
    ticket, enrichment, severity, routing, recommendation = _hero_context()

    results = execute_auto_actions(ticket, enrichment, severity, routing, recommendation)

    statuses = {r.action: r.status for r in results}
    assert statuses == {"create_linear_issue": "skipped", "notify_support_channel": "skipped"}


def test_skips_when_team_or_channel_not_configured(monkeypatch):
    monkeypatch.delenv("LINEAR_TEAM", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL", raising=False)
    ticket, enrichment, severity, routing, recommendation = _hero_context()

    results = execute_auto_actions(
        ticket, enrichment, severity, routing, recommendation, client=_FakeClient()
    )

    statuses = {r.action: r.status for r in results}
    assert statuses == {"create_linear_issue": "skipped", "notify_support_channel": "skipped"}


def test_needs_authorization_surfaces_url(monkeypatch):
    monkeypatch.setenv("LINEAR_TEAM", "DON")
    monkeypatch.setenv("SLACK_CHANNEL", "support-engineering")
    ticket, enrichment, severity, routing, recommendation = _hero_context()

    results = execute_auto_actions(
        ticket,
        enrichment,
        severity,
        routing,
        recommendation,
        client=_FakeClient(authorized=False),
    )

    for result in results:
        assert result.status == "needs_authorization"
        assert result.detail.startswith("https://arcade.dev/authorize/")


def test_executes_and_links_linear_issue_into_slack_message(monkeypatch):
    monkeypatch.setenv("LINEAR_TEAM", "DON")
    monkeypatch.setenv("SLACK_CHANNEL", "support-engineering")
    ticket, enrichment, severity, routing, recommendation = _hero_context()
    fake_client = _FakeClient(linear_url="https://linear.app/x/issue/DON-5")

    results = execute_auto_actions(
        ticket, enrichment, severity, routing, recommendation, client=fake_client
    )

    statuses = {r.action: r.status for r in results}
    assert statuses == {"create_linear_issue": "executed", "notify_support_channel": "executed"}

    linear_result = next(r for r in results if r.action == "create_linear_issue")
    assert linear_result.detail == "https://linear.app/x/issue/DON-5"

    _, slack_input = next(
        call for call in fake_client.tools.executed if call[0] == "Slack.SendMessage"
    )
    assert "https://linear.app/x/issue/DON-5" in slack_input["message"]


def test_never_executes_approval_required_action(monkeypatch):
    monkeypatch.setenv("LINEAR_TEAM", "DON")
    monkeypatch.setenv("SLACK_CHANNEL", "support-engineering")
    ticket, enrichment, severity, routing, recommendation = _hero_context()
    fake_client = _FakeClient()

    execute_auto_actions(ticket, enrichment, severity, routing, recommendation, client=fake_client)

    executed_tools = {call[0] for call in fake_client.tools.executed}
    assert executed_tools == {"Linear.CreateIssue", "Slack.SendMessage"}


def test_reports_failure_from_tool_execution(monkeypatch):
    monkeypatch.setenv("LINEAR_TEAM", "DON")
    monkeypatch.delenv("SLACK_CHANNEL", raising=False)
    ticket, enrichment, severity, routing, recommendation = _hero_context()

    class _FailingTools(_FakeTools):
        def execute(self, *, tool_name, input, user_id):
            return _FakeExecuteResponse(success=False, error_message="team not found")

    class _FailingClient:
        def __init__(self):
            self.tools = _FailingTools()

    results = execute_auto_actions(
        ticket, enrichment, severity, routing, recommendation, client=_FailingClient()
    )

    linear_result = next(r for r in results if r.action == "create_linear_issue")
    assert linear_result.status == "failed"
    assert linear_result.detail == "team not found"
