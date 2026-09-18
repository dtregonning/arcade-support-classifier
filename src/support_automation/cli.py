"""CLI demo: run the full support automation pipeline against a ticket JSON
file and print a human-readable report.

Deliberately does not touch Arcade, Slack, or Linear — the demo must work
with zero third-party credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import (
    ActionRecommendation,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import SupportTicket
from support_automation.models.validation import ValidationResult
from support_automation.services.severity import recommend_severity
from support_automation.tools.enrich_ticket import enrich_ticket
from support_automation.tools.recommend_actions import recommend_actions
from support_automation.tools.route_ticket import route_ticket
from support_automation.tools.validate_ticket import validate_ticket

_EXECUTION_MARK = {
    "automatic": "✓",  # check
    "human_approval": "△",  # triangle
    "human_only": "⛔",  # no-entry
}


def load_ticket(path: Path) -> SupportTicket:
    data = json.loads(path.read_text())
    return SupportTicket(**data)


def _impact_line(ticket: SupportTicket) -> str:
    if ticket.affected_users is not None and ticket.total_users:
        pct = round(100 * ticket.affected_users / ticket.total_users)
        return f"Impact: ~{pct}% users ({ticket.affected_users}/{ticket.total_users})"
    if ticket.affected_users is not None:
        return f"Impact: {ticket.affected_users} users affected (total unknown)"
    return "Impact: unknown (affected_users not reported)"


def format_report(
    ticket: SupportTicket,
    validation: ValidationResult,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
    recommendation: ActionRecommendation,
) -> str:
    lines: list[str] = []
    w = lines.append

    w("SUPPORT AUTOMATION DEMO")
    w("=" * 40)
    w("")
    w("TICKET")
    w("-" * 40)
    w(f"{ticket.customer_name or ticket.customer_id or 'Unknown customer'} ({ticket.ticket_id})")
    w(ticket.subject or "(no subject)")
    w(_impact_line(ticket))
    w("")

    w("VALIDATION")
    w("-" * 40)
    w(f"Completeness: {validation.completeness_score}%")
    w(f"Valid: {'YES' if validation.valid else 'NO'}")
    w(f"Automation Ready: {'YES' if validation.ready_for_automation else 'NO'}")
    if validation.missing_fields:
        w(f"Missing fields: {', '.join(validation.missing_fields)}")
    for warning in validation.warnings:
        w(f"Warning [{warning.code}]: {warning.message}")
    w("")

    w("SIGNALS & ENRICHMENT")
    w("-" * 40)
    w(f"Domains: {', '.join(enrichment.domains) or 'none detected'}")
    w(f"Technologies: {', '.join(enrichment.technologies) or 'none detected'}")
    for signal in enrichment.signals:
        w(f"  Signal: {signal.type} = {signal.value}  ({signal.evidence})")
    for fact in enrichment.observed_facts:
        w(f"  Fact: {fact}")
    for hyp in enrichment.customer_hypotheses:
        w(f'  Customer hypothesis (not treated as fact): "{hyp}"')
    for cause in enrichment.possible_causes:
        w(f"  Possible cause: {cause.cause} (confidence {cause.confidence:.0%})")
        w(f"    reason_codes: {', '.join(cause.reason_codes)}")
    if enrichment.correlated_recent_changes:
        w("  Correlated recent changes (investigation leads, not confirmed causes):")
        for change in enrichment.correlated_recent_changes:
            w(f"    - {change}")
    if enrichment.uncorrelated_recent_changes:
        w("  Recent changes NOT implicated:")
        for u in enrichment.uncorrelated_recent_changes:
            w(f"    - {u.change} ({u.reason})")
    w("")

    w("SEVERITY")
    w("-" * 40)
    reported = severity.reported_severity.value if severity.reported_severity else "not reported"
    w(f"Customer:    {reported}")
    w(f"Recommended: {severity.recommended_severity.value}")
    for reason in severity.reasoning:
        w(f"  - {reason}")
    w("")

    w("ROUTING")
    w("-" * 40)
    w(f"Queue: {routing.queue}")
    w(f"Owner: {routing.owner}")
    w(f"Matched rule: {routing.matched_rule} (confidence {routing.routing_confidence:.0%})")
    w(f"Reason codes: {', '.join(routing.reason_codes)}")
    w(f"Requires human review: {'YES' if routing.requires_human_review else 'NO'}")
    w("")

    w("RECOMMENDED ACTIONS")
    w("-" * 40)
    for action in recommendation.actions:
        mark = _EXECUTION_MARK.get(action.execution, "?")
        w(f"{mark} {action.action}  (risk: {action.risk}, execution: {action.execution})")
    w("")

    w("REJECTED ACTIONS")
    w("-" * 40)
    for rejected in recommendation.actions_rejected:
        w(f"✗ {rejected.action}")
        w(f"  {rejected.reason}")

    return "\n".join(lines)


def run_pipeline(ticket: SupportTicket) -> str:
    validation = validate_ticket(ticket)
    enrichment = enrich_ticket(ticket)
    severity = recommend_severity(ticket, enrichment)
    routing = route_ticket(ticket, enrichment)
    recommendation = recommend_actions(ticket, validation, enrichment, severity, routing)
    return format_report(ticket, validation, enrichment, severity, routing, recommendation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="support-demo",
        description="Run the support automation pipeline against a ticket JSON file.",
    )
    parser.add_argument("ticket_path", type=Path, help="Path to a ticket JSON file")
    args = parser.parse_args(argv)

    if not args.ticket_path.exists():
        print(f"error: {args.ticket_path} does not exist", file=sys.stderr)
        return 1

    ticket = load_ticket(args.ticket_path)
    print(run_pipeline(ticket))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
