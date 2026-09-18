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

from pydantic import BaseModel


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
