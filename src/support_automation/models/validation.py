"""Deterministic validation result model."""

from __future__ import annotations

from pydantic import BaseModel


class ValidationWarning(BaseModel):
    code: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    completeness_score: int
    missing_fields: list[str]
    warnings: list[ValidationWarning]
    ready_for_automation: bool
