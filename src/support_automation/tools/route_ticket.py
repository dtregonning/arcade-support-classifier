"""Thin wrapper around services.router, ready to be exposed as an MCP tool."""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import RoutingResult
from support_automation.models.ticket import SupportTicket
from support_automation.observability import log_step
from support_automation.services.router import route_ticket as _route_ticket


def route_ticket(ticket: SupportTicket, enrichment: TicketEnrichment) -> RoutingResult:
    with log_step(ticket_id=ticket.ticket_id, tool="route_ticket") as record:
        result = _route_ticket(ticket, enrichment)
        record["matched_rule"] = result.matched_rule
        record["confidence"] = result.routing_confidence
        record["human_review_required"] = result.requires_human_review
        return result
