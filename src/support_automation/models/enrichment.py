"""Enrichment output model.

The central design rule for this module: FACT, CUSTOMER CLAIM, and SYSTEM
HYPOTHESIS are kept in separate fields and never merged into one bag of
"things we believe." `observed_facts` are derived directly from structured
evidence (logs, error messages). `customer_hypotheses` are the customer's
own claims, verbatim, never promoted to fact. `possible_causes` are the
system's own hypotheses, each with a confidence score and traceable back to
observed facts via `evidence`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SystemArea(StrEnum):
    """The closed set of taxonomy "system area" tags a ticket can carry.

    Deliberately closed, not free text: this is a Pydantic enum, so
    constructing a TicketEnrichment with any value outside this list
    raises a validation error rather than silently minting a new tag.
    That's what keeps this from turning into an unbounded pile of
    one-off labels over time -- adding a new area means editing this
    enum (and deciding whether it needs a rule in services/enricher.py),
    never happens implicitly through user input or an AI guess.
    """

    IDENTITY = "identity"
    OAUTH = "oauth"
    GOOGLE = "google"
    KUBERNETES = "kubernetes"
    DATABASE = "database"
    NETWORK = "network"
    API = "api"
    CONFIGURATION = "configuration"
    PLATFORM = "platform"
    INTEGRATIONS = "integrations"
    TOOLKIT = "toolkit"
    MCP_RUNTIME = "mcp_runtime"
    UNKNOWN = "unknown"


SystemAreaSource = Literal["rule_based", "ai_classified", "unknown"]


class Signal(BaseModel):
    type: str
    value: str
    evidence: str


class PossibleCause(BaseModel):
    cause: str
    confidence: float
    reason_codes: list[str]
    evidence: list[str]


class UncorrelatedChange(BaseModel):
    change: str
    reason: str


class TicketEnrichment(BaseModel):
    domains: list[str]
    signals: list[Signal]
    technologies: list[str]

    # Recent changes that share a keyword with a detected domain/signal.
    # Surfaced as investigation leads, never promoted to `possible_causes`
    # on their own — correlation is not causation.
    correlated_recent_changes: list[str]

    customer_hypotheses: list[str]
    observed_facts: list[str]
    possible_causes: list[PossibleCause]

    # Recent changes present on the ticket that were NOT correlated with any
    # observed signal. Kept visible so the demo can show what the system
    # deliberately declined to blame, rather than silently dropping them.
    uncorrelated_recent_changes: list[UncorrelatedChange]

    # Taxonomy display field -- NEVER read by routing (services/router.py
    # only ever looks at `domains`, above). Populated deterministically
    # from `domains` when the rule engine found something; only falls
    # back to an AI guess (services/ai_area_classifier.py, itself
    # constrained to this same enum) when domains came back empty. Kept
    # entirely separate from `domains` so an AI-sourced guess can never
    # silently influence a routing decision -- see CLAUDE.md's "AI is not
    # the policy engine".
    system_areas: list[SystemArea] = Field(default_factory=lambda: [SystemArea.UNKNOWN])
    system_area_source: SystemAreaSource = "unknown"
