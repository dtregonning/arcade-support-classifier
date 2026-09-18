"""Thin wrapper around services.validator, ready to be exposed as an MCP tool."""

from __future__ import annotations

from support_automation.models.ticket import SupportTicket
from support_automation.models.validation import ValidationResult
from support_automation.observability import log_step
from support_automation.services.validator import validate_ticket as _validate_ticket


def validate_ticket(ticket: SupportTicket) -> ValidationResult:
    with log_step(ticket_id=ticket.ticket_id, tool="validate_ticket") as record:
        result = _validate_ticket(ticket)
        record["human_review_required"] = not result.ready_for_automation
        return result
