"""Deterministic ticket validation.

Every check here is rule-based and visible in config/validation_rules.yaml.
No AI, no invented confidence numbers — completeness is a sum of weights
for fields that are actually present on the ticket.
"""

from __future__ import annotations

from typing import Any

import yaml

from support_automation._config_paths import config_path
from support_automation.models.ticket import SupportTicket
from support_automation.models.validation import ValidationResult, ValidationWarning

_CONFIG_PATH = config_path("validation_rules.yaml")


def _load_rules() -> dict[str, Any]:
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


_RULES = _load_rules()
_WEIGHTS: dict[str, int] = _RULES["field_weights"]
_VALID_MIN = _RULES["thresholds"]["valid_minimum_score"]
_READY_MIN = _RULES["thresholds"]["ready_for_automation_minimum_score"]
_P1_MIN_RATIO = _RULES["severity_support"]["P1_minimum_impact_ratio"]


def _field_present(ticket: SupportTicket, field: str) -> bool:
    if field == "evidence":
        return bool(ticket.logs) or bool(ticket.error_messages)
    value = getattr(ticket, field)
    if isinstance(value, list):
        return len(value) > 0
    return value is not None


def _missing_field_names(ticket: SupportTicket, field: str) -> list[str]:
    """Map a scored field to the ticket field name(s) reported as missing."""
    if field == "evidence":
        return ["logs", "error_messages"]
    return [field]


def validate_ticket(ticket: SupportTicket) -> ValidationResult:
    score = 0
    missing_fields: list[str] = []

    for field, weight in _WEIGHTS.items():
        if _field_present(ticket, field):
            score += weight
        else:
            missing_fields.extend(_missing_field_names(ticket, field))

    warnings: list[ValidationWarning] = []

    if (
        ticket.reported_severity == "P1"
        and ticket.affected_users is not None
        and ticket.total_users is not None
        and ticket.total_users > 0
    ):
        ratio = ticket.affected_users / ticket.total_users
        if ratio < _P1_MIN_RATIO:
            warnings.append(
                ValidationWarning(
                    code="severity_unsupported",
                    message=(
                        f"Ticket claims P1 but currently describes impact to "
                        f"{ratio:.0%} of users ({ticket.affected_users}/{ticket.total_users})."
                    ),
                )
            )

    if not ticket.logs and not ticket.error_messages:
        warnings.append(
            ValidationWarning(
                code="missing_evidence",
                message="No logs or error messages were provided.",
            )
        )

    has_identity = ticket.ticket_id and (ticket.customer_id or ticket.customer_name)
    valid = bool(has_identity and ticket.description and score >= _VALID_MIN)
    ready_for_automation = valid and score >= _READY_MIN

    return ValidationResult(
        valid=valid,
        completeness_score=score,
        missing_fields=missing_fields,
        warnings=warnings,
        ready_for_automation=ready_for_automation,
    )
