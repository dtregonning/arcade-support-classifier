"""Request/response schemas for the web portal.

Kept separate from support_automation.models: `TicketSubmission` is a
presentation-layer concern (an optional ticket_id, form-friendly defaults)
and must not leak into the core ticket model used by the CLI, MCP tools,
and tests.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.execution import ExecutionResult
from support_automation.models.routing import (
    ActionRecommendation,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import CustomerTier, Environment, Severity, SupportTicket
from support_automation.models.validation import ValidationResult


class TicketSubmission(BaseModel):
    ticket_id: str | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    customer_tier: CustomerTier | None = None

    subject: str | None = None
    description: str | None = None

    reported_severity: Severity | None = None
    affected_users: int | None = None
    total_users: int | None = None

    product: str | None = None
    provider: str | None = None
    environment: Environment | None = None

    error_messages: list[str] = Field(default_factory=list)
    logs: str | None = None

    reproduction_steps: list[str] = Field(default_factory=list)

    first_seen_at: datetime | None = None
    reported_at: datetime | None = None

    recent_changes: list[str] = Field(default_factory=list)
    customer_hypothesis: str | None = None


class ClassificationResult(BaseModel):
    ticket: SupportTicket
    validation: ValidationResult
    enrichment: TicketEnrichment
    severity: SeverityAssessment
    routing: RoutingResult
    recommendation: ActionRecommendation
    executions: list[ExecutionResult] = Field(default_factory=list)
