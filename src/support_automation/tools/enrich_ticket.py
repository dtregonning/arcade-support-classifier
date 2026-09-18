"""Thin wrapper around services.enricher, ready to be exposed as an MCP tool.

Also owns the one place the optional AI area-classification fallback
gets consulted (services/ai_area_classifier.py) -- only when the
deterministic enricher's `system_area_source` came back "unknown" (i.e.
the rule engine detected no domain at all). This keeps RuleBasedEnricher
itself pure and fully deterministic/testable in isolation, while every
caller of enrich_ticket (CLI, MCP server, web portal) gets the same
optional upgrade for free.
"""

from __future__ import annotations

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.ticket import SupportTicket
from support_automation.observability import log_step
from support_automation.services.ai_area_classifier import classify_area
from support_automation.services.enricher import RuleBasedEnricher, TicketEnricher, evidence_text

_DEFAULT_ENRICHER: TicketEnricher = RuleBasedEnricher()


def enrich_ticket(
    ticket: SupportTicket, enricher: TicketEnricher = _DEFAULT_ENRICHER
) -> TicketEnrichment:
    with log_step(ticket_id=ticket.ticket_id, tool="enrich_ticket") as record:
        result = enricher.enrich(ticket)
        record["confidence"] = max((c.confidence for c in result.possible_causes), default=None)

        if result.system_area_source == "unknown":
            area = classify_area(evidence_text(ticket))
            if area is not None:
                result = result.model_copy(
                    update={"system_areas": [area], "system_area_source": "ai_classified"}
                )

        return result
