"""Routing result and severity assessment models."""

from __future__ import annotations

from pydantic import BaseModel

from support_automation.models.ticket import Severity


class RoutingResult(BaseModel):
    queue: str
    owner: str
    matched_rule: str
    routing_confidence: float
    reason_codes: list[str]
    requires_human_review: bool


class SeverityAssessment(BaseModel):
    reported_severity: Severity | None
    recommended_severity: Severity
    differs: bool
    reasoning: list[str]


class RecommendedAction(BaseModel):
    action: str
    risk: str
    execution: str


class RejectedAction(BaseModel):
    action: str
    reason: str


class ActionRecommendation(BaseModel):
    actions: list[RecommendedAction]
    actions_rejected: list[RejectedAction]
