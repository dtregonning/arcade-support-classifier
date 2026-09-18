"""Thin wrapper around services.enricher, ready to be exposed as an MCP tool."""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.ticket import SupportTicket
from support_automation.observability import log_step
from support_automation.services.enricher import RuleBasedEnricher, TicketEnricher

_DEFAULT_ENRICHER: TicketEnricher = RuleBasedEnricher()


def enrich_ticket(
    ticket: SupportTicket, enricher: TicketEnricher = _DEFAULT_ENRICHER
) -> TicketEnrichment:
    with log_step(ticket_id=ticket.ticket_id, tool="enrich_ticket") as record:
        result = enricher.enrich(ticket)
        record["confidence"] = max((c.confidence for c in result.possible_causes), default=None)
        return result
