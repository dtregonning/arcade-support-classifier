"""Severity engine.

Never trusts the customer-reported severity blindly. Computes an
independent recommendation from measurable impact (affected/total user
ratio) and known domain characteristics, and always returns both values —
the reported severity is never silently overwritten.
"""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import SeverityAssessment
from support_automation.models.ticket import Severity, SupportTicket

# Domains where, absent better impact data, we assume production
# unavailability rather than a merely degraded state.
_PRODUCTION_DOWN_DOMAINS = {"kubernetes"}


def _severity_from_ratio(ratio: float) -> Severity:
    if ratio >= 0.8:
        return Severity.P1
    if ratio >= 0.1:
        return Severity.P2
    if ratio > 0:
        return Severity.P3
    return Severity.P4


def recommend_severity(ticket: SupportTicket, enrichment: TicketEnrichment) -> SeverityAssessment:
    reasoning: list[str] = []

    if ticket.affected_users is not None and ticket.total_users:
        ratio = ticket.affected_users / ticket.total_users
        recommended = _severity_from_ratio(ratio)
        reasoning.append(
            f"{ticket.affected_users}/{ticket.total_users} users affected "
            f"({ratio:.0%}) maps to {recommended.value}."
        )
    elif any(d in _PRODUCTION_DOWN_DOMAINS for d in enrichment.domains):
        recommended = Severity.P1
        reasoning.append(
            "No user-impact counts provided, but detected domain "
            f"({', '.join(enrichment.domains)}) implies production unavailability."
        )
    elif enrichment.possible_causes:
        recommended = Severity.P2
        reasoning.append(
            "No user-impact counts provided; defaulting to P2 given a detected "
            "technical signal without confirmed full-production impact."
        )
    else:
        recommended = Severity.P3
        reasoning.append("No user-impact counts and no strong technical signal detected.")

    reported = ticket.reported_severity
    differs = reported is not None and reported != recommended
    if differs:
        reasoning.append(
            f"Reported severity ({reported.value}) differs from recommended "
            f"({recommended.value}); reported severity is preserved, not overwritten."
        )

    return SeverityAssessment(
        reported_severity=reported,
        recommended_severity=recommended,
        differs=differs,
        reasoning=reasoning,
    )
