"""MCP server: exposes generate_ticket, validate_ticket, enrich_ticket,
route_ticket, and recommend_actions as MCP tools via Arcade's MCP
framework.

No business logic lives here. Every @app.tool function is a thin wrapper
around the already-tested support_automation.services / .tools functions
— this module's only real job is adapting to the MCP wire format:

- `TicketPayload` mirrors `SupportTicket` field-for-field, except
  `first_seen_at`/`reported_at` are ISO-8601 strings instead of
  `datetime.datetime`. Arcade's tool-schema builder does not support
  `datetime` as a wire type; Pydantic parses the ISO string back into a
  real `datetime` when `SupportTicket` is constructed, so no date-handling
  logic changes anywhere else in the codebase.
- `recommend_actions` computes severity internally (via the same
  `services.severity.recommend_severity` the CLI and web portal call) and
  returns it alongside the recommendation, because CLAUDE.md's required
  tool surface is exactly generate/validate/enrich/route/recommend — there
  is no separate "assess severity" tool — while `route_ticket`'s output
  stays exactly the schema CLAUDE.md specifies.

Run with:
    uv run support-mcp stdio
    uv run support-mcp http

Deliberately does NOT use `from __future__ import annotations` (unlike the
rest of this codebase): arcade_mcp_server's @app.tool decorator inspects
live annotation objects to build JSON schemas, and does not resolve PEP
563 postponed (stringified) annotations, so tools defined under that
import silently fail to register.
"""

import sys
from typing import Annotated

from arcade_mcp_server import MCPApp
from pydantic import BaseModel, Field

from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import (
    ActionRecommendation,
    RecommendedAction,
    RejectedAction,
    RoutingResult,
    SeverityAssessment,
)
from support_automation.models.ticket import CustomerTier, Environment, Severity, SupportTicket
from support_automation.models.validation import ValidationResult
from support_automation.services.severity import recommend_severity
from support_automation.tools.enrich_ticket import enrich_ticket as _enrich_ticket
from support_automation.tools.generate_ticket import generate_ticket as _generate_ticket
from support_automation.tools.recommend_actions import recommend_actions as _recommend_actions
from support_automation.tools.route_ticket import route_ticket as _route_ticket
from support_automation.tools.validate_ticket import validate_ticket as _validate_ticket

app = MCPApp(name="support_automation", version="0.1.0")


class TicketPayload(BaseModel):
    """Wire-format ticket for MCP tool calls. Identical to SupportTicket
    except first_seen_at/reported_at are ISO-8601 strings — see module
    docstring."""

    ticket_id: str

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

    first_seen_at: str | None = None
    reported_at: str | None = None

    recent_changes: list[str] = Field(default_factory=list)
    customer_hypothesis: str | None = None

    metadata: dict[str, str] = Field(default_factory=dict)


class RecommendActionsResult(BaseModel):
    severity: SeverityAssessment
    actions: list[RecommendedAction]
    actions_rejected: list[RejectedAction]


def _as_model(model_cls: type[BaseModel], value: BaseModel | dict) -> BaseModel:
    """arcade_core's ToolExecutor validates tool inputs through a generated
    wrapper model and calls the tool function with that model's
    `.model_dump()` — so nested Pydantic-typed parameters actually arrive
    as plain dicts at runtime, not model instances. Reconstruct the real
    model here rather than assuming the declared type."""
    return value if isinstance(value, model_cls) else model_cls(**value)


def _to_ticket(payload: TicketPayload | dict) -> SupportTicket:
    data = payload if isinstance(payload, dict) else payload.model_dump()
    return SupportTicket(**data)


def _to_payload(ticket: SupportTicket) -> TicketPayload:
    return TicketPayload(**ticket.model_dump(mode="json"))


@app.tool
def generate_ticket(
    scenario: Annotated[
        str,
        "Scenario name: oauth_scope_mismatch, expired_token, kubernetes_crashloop, "
        "kubernetes_oom, api_rate_limit, network_timeout, database_connection_exhaustion, "
        "or unknown_issue",
    ],
    customer_tier: Annotated[CustomerTier, "Customer tier"] = CustomerTier.ENTERPRISE,
    completeness: Annotated[
        float, "Fraction (0.0-1.0) of optional fields to populate; below 1.0 omits some"
    ] = 1.0,
) -> Annotated[TicketPayload, "A generated mock support ticket"]:
    """Generate a realistic mock support ticket for testing, with deterministic seeded
    randomness so the same inputs always produce the same ticket."""
    ticket = _generate_ticket(scenario, customer_tier=customer_tier, completeness=completeness)
    return _to_payload(ticket)


@app.tool
def validate_ticket(
    ticket: Annotated[TicketPayload, "The ticket to validate"],
) -> Annotated[ValidationResult, "Completeness score, missing fields, warnings, and readiness"]:
    """Deterministically validate whether a ticket has enough information for automation."""
    return _validate_ticket(_to_ticket(ticket))


@app.tool
def enrich_ticket(
    ticket: Annotated[TicketPayload, "The ticket to enrich"],
) -> Annotated[
    TicketEnrichment,
    "Extracted signals, technologies, and possible causes, with facts, customer "
    "hypotheses, and system hypotheses kept separate",
]:
    """Extract structured technical signals from a ticket's logs/errors/description."""
    return _enrich_ticket(_to_ticket(ticket))


@app.tool
def route_ticket(
    ticket: Annotated[TicketPayload, "The ticket to route"],
    enrichment: Annotated[TicketEnrichment, "Enrichment output from enrich_ticket"],
) -> Annotated[RoutingResult, "Destination queue, owner, and routing rationale"]:
    """Route a ticket to a support queue using policy from config/routing_rules.yaml."""
    return _route_ticket(_to_ticket(ticket), _as_model(TicketEnrichment, enrichment))


@app.tool
def recommend_actions(
    ticket: Annotated[TicketPayload, "The ticket"],
    validation: Annotated[ValidationResult, "Output of validate_ticket"],
    enrichment: Annotated[TicketEnrichment, "Output of enrich_ticket"],
    routing: Annotated[RoutingResult, "Output of route_ticket"],
) -> Annotated[
    RecommendActionsResult,
    "Independently assessed severity, recommended actions (each gated by an "
    "automation execution class), and actions explicitly rejected with reasons",
]:
    """Recommend support actions, gated by automation policy (AUTO / APPROVAL_REQUIRED /
    HUMAN_ONLY). Always reports rejected actions alongside recommended ones."""
    real_ticket = _to_ticket(ticket)
    real_validation = _as_model(ValidationResult, validation)
    real_enrichment = _as_model(TicketEnrichment, enrichment)
    real_routing = _as_model(RoutingResult, routing)
    severity = recommend_severity(real_ticket, real_enrichment)
    recommendation: ActionRecommendation = _recommend_actions(
        real_ticket, real_validation, real_enrichment, severity, real_routing
    )
    return RecommendActionsResult(
        severity=severity,
        actions=recommendation.actions,
        actions_rejected=recommendation.actions_rejected,
    )


def main() -> None:
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    app.run(transport=transport, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
