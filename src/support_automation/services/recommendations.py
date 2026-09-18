"""Recommended actions, gated by the automation policy.

Three execution classes (see CLAUDE.md "Automation Policy"):
  - AUTO: internal, reversible, low-risk (tagging, internal issues, notes)
  - APPROVAL_REQUIRED: customer-facing or config-changing
  - HUMAN_ONLY: destructive/irreversible/security-sensitive

This module maps `execution` to those classes via the string values
"automatic", "human_approval", "human_only". No LLM output can bypass this
mapping — it is plain deterministic code driven by validation, enrichment,
severity, and routing outputs, and it always documents what it declined to
do and why.
"""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import (
    ActionRecommendation,
    RecommendedAction,
    RejectedAction,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import Severity, SupportTicket
from support_automation.models.validation import ValidationResult

_NO_PAGING_REASON = "No infrastructure evidence currently supports paging."
_INFRA_DOMAINS = {"kubernetes", "database"}

_STANDARD_ACTIONS = [
    RecommendedAction(action="create_linear_issue", risk="low", execution="automatic"),
    RecommendedAction(action="notify_support_channel", risk="low", execution="automatic"),
]


def _reauthorization_action(enrichment: TicketEnrichment) -> RecommendedAction:
    action = (
        "request_google_reauthorization"
        if "google" in enrichment.domains
        else "request_reauthorization"
    )
    return RecommendedAction(action=action, risk="low", execution="human_approval")


def recommend_actions(
    ticket: SupportTicket,
    validation: ValidationResult,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
) -> ActionRecommendation:
    signal_types = {s.type for s in enrichment.signals}
    domains = set(enrichment.domains)

    actions: list[RecommendedAction] = list(_STANDARD_ACTIONS)
    rejected: list[RejectedAction] = []

    if signal_types & {"scope_mismatch", "expired_token"}:
        reauth = _reauthorization_action(enrichment)
        if validation.valid:
            actions.append(reauth)
        else:
            rejected.append(
                RejectedAction(
                    action=reauth.action,
                    reason="Ticket is missing critical identity information; cannot "
                    "recommend a customer-facing action yet.",
                )
            )

    if "db_connection_exhaustion" in signal_types:
        actions.append(
            RecommendedAction(
                action="increase_connection_pool_size", risk="medium", execution="human_approval"
            )
        )

    if signal_types & {"container_crash", "oom_kill"}:
        actions.append(
            RecommendedAction(action="restart_workload", risk="medium", execution="human_approval")
        )

    if "rate_limit" in signal_types:
        actions.append(
            RecommendedAction(
                action="request_rate_limit_increase", risk="low", execution="human_approval"
            )
        )

    if "configuration_error" in signal_types:
        actions.append(
            RecommendedAction(
                action="send_configuration_guidance", risk="low", execution="human_approval"
            )
        )

    for change in enrichment.correlated_recent_changes:
        actions.append(
            RecommendedAction(
                action=f"investigate_recent_change:{change}", risk="low", execution="automatic"
            )
        )

    justifies_paging = (
        bool(domains & _INFRA_DOMAINS) and severity.recommended_severity == Severity.P1
    )
    if justifies_paging:
        actions.append(
            RecommendedAction(
                action="page_infrastructure", risk="medium", execution="human_approval"
            )
        )
    else:
        rejected.append(RejectedAction(action="page_infrastructure", reason=_NO_PAGING_REASON))

    if not enrichment.possible_causes:
        rejected.append(
            RejectedAction(
                action="automated_remediation",
                reason="No technical signal was detected with enough confidence to "
                "recommend a specific remediation; requires human triage.",
            )
        )

    for uncorrelated in enrichment.uncorrelated_recent_changes:
        rejected.append(
            RejectedAction(
                action=f"attribute_root_cause_to:{uncorrelated.change}",
                reason=uncorrelated.reason,
            )
        )

    return ActionRecommendation(actions=actions, actions_rejected=rejected)
