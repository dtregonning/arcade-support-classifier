"""Thin wrapper around services.recommendations, ready to be exposed as an MCP tool."""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import (
    ActionRecommendation,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import SupportTicket
from support_automation.models.validation import ValidationResult
from support_automation.observability import log_step
from support_automation.services.recommendations import recommend_actions as _recommend_actions


def recommend_actions(
    ticket: SupportTicket,
    validation: ValidationResult,
    enrichment: TicketEnrichment,
    severity: SeverityAssessment,
    routing: RoutingResult,
) -> ActionRecommendation:
    with log_step(ticket_id=ticket.ticket_id, tool="recommend_actions") as record:
        result = _recommend_actions(ticket, validation, enrichment, severity, routing)
        record["human_review_required"] = any(a.execution != "automatic" for a in result.actions)
        return result
