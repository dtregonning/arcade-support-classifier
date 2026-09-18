"""Core support ticket model.

Not every field is required. Missing information is intentional: the
validator's job is to detect and score what's absent, so tickets are
deliberately allowed to be incomplete here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CustomerTier(StrEnum):
    ENTERPRISE = "enterprise"
    BUSINESS = "business"
    FREE = "free"


class Severity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Environment(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class SupportTicket(BaseModel):
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

    first_seen_at: datetime | None = None
    reported_at: datetime | None = None

    recent_changes: list[str] = Field(default_factory=list)

    customer_hypothesis: str | None = None

    metadata: dict[str, str] = Field(default_factory=dict)
