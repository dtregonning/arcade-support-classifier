"""Mock ticket generator for testing and demos.

Deterministic and seeded: the same (scenario, customer_tier, completeness)
always produces the same ticket, so tests stay reproducible. When
`completeness < 1.0`, optional fields are dropped (never the identity
fields) so the validator has something real to detect.
"""

from __future__ import annotations

import random
import zlib
from datetime import UTC, datetime, timedelta

from support_automation.models.ticket import CustomerTier, Environment, Severity, SupportTicket

_OPTIONAL_FIELDS = [
    "customer_name",
    "customer_tier",
    "affected_users",
    "total_users",
    "first_seen_at",
    "reported_at",
    "recent_changes",
    "provider",
    "environment",
    "error_messages",
    "logs",
    "reproduction_steps",
    "customer_hypothesis",
]

_NOW = datetime(2026, 9, 15, tzinfo=UTC)

SCENARIOS: dict[str, dict] = {
    "oauth_scope_mismatch": {
        "subject": "Gmail send failing for subset of users",
        "description": (
            "Users are intermittently unable to send Gmail messages through the AI agent "
            "integration."
        ),
        "product": "AI Agent Platform",
        "provider": "Google",
        "environment": Environment.PRODUCTION,
        "error_messages": ["authorization_required: missing required scope"],
        "logs": (
            "tool=Gmail.SendEmail status=authorization_required "
            "required_scopes=[gmail.send,gmail.compose] granted_scopes=[gmail.readonly,gmail.send]"
        ),
        "reproduction_steps": [
            "Connect Google account",
            "Attempt to send email via agent",
            "Observe authorization_required error",
        ],
        "recent_changes": ["Google toolkit upgraded v3.1 to v3.4 on Monday"],
        "customer_hypothesis": "Arcade is losing tokens",
        "affected_users": 340,
        "total_users": 1000,
        "reported_severity": Severity.P1,
        "first_seen_offset_days": 2,
    },
    "expired_token": {
        "subject": "OAuth token expired, integration failing",
        "description": "Customer integration stopped working after an OAuth token expired.",
        "product": "AI Agent Platform",
        "provider": "Google",
        "environment": Environment.PRODUCTION,
        "error_messages": ["invalid_token: token_expired"],
        "logs": "tool=Calendar.ListEvents status=unauthorized error=token_expired",
        "reproduction_steps": ["Call Calendar.ListEvents", "Observe unauthorized error"],
        "recent_changes": [],
        "customer_hypothesis": "Something broke on your end overnight",
        "affected_users": 5,
        "total_users": 500,
        "reported_severity": Severity.P2,
        "first_seen_offset_days": 1,
    },
    "kubernetes_crashloop": {
        "subject": "Worker pods stuck in CrashLoopBackOff",
        "description": (
            "Background job workers are continuously restarting and failing to process queued jobs."
        ),
        "product": "Job Processing Service",
        "provider": None,
        "environment": Environment.PRODUCTION,
        "error_messages": ["Back-off restarting failed container", "CrashLoopBackOff"],
        "logs": "pod=worker-7f9c status=CrashLoopBackOff restarts=14 reason=Error",
        "reproduction_steps": ["Deploy worker image v2.9.0", "Observe pod restart loop"],
        "recent_changes": ["Deployed worker image v2.9.0"],
        "customer_hypothesis": "Your infrastructure is down",
        "affected_users": 1000,
        "total_users": 1000,
        "reported_severity": Severity.P1,
        "first_seen_offset_days": 0,
    },
    "kubernetes_oom": {
        "subject": "Worker pods being OOMKilled under load",
        "description": (
            "Pods processing large batch jobs are being killed for exceeding memory limits."
        ),
        "product": "Job Processing Service",
        "provider": None,
        "environment": Environment.PRODUCTION,
        "error_messages": ["OOMKilled", "container exceeded memory limit"],
        "logs": "pod=batch-worker-3 status=OOMKilled memory_limit=512Mi",
        "reproduction_steps": ["Submit large batch job", "Observe pod termination"],
        "recent_changes": ["Increased default batch size from 100 to 500"],
        "customer_hypothesis": "Must be a memory leak in your platform",
        "affected_users": 120,
        "total_users": 1000,
        "reported_severity": Severity.P2,
        "first_seen_offset_days": 3,
    },
    "api_rate_limit": {
        "subject": "Salesforce sync failing with 429 errors",
        "description": "Salesforce sync jobs are failing intermittently with rate limit errors.",
        "product": "Integration Sync Service",
        "provider": "Salesforce",
        "environment": Environment.PRODUCTION,
        "error_messages": ["HTTP 429 Too Many Requests"],
        "logs": "tool=Salesforce.Sync status=429 retry_after=30",
        "reproduction_steps": ["Trigger sync job", "Observe 429 responses"],
        "recent_changes": ["Increased sync frequency from hourly to every 5 minutes"],
        "customer_hypothesis": "Salesforce must be down",
        "affected_users": 45,
        "total_users": 900,
        "reported_severity": Severity.P3,
        "first_seen_offset_days": 1,
    },
    "network_timeout": {
        "subject": "Intermittent connection timeouts to integration endpoint",
        "description": "Requests to the third-party API occasionally time out without a response.",
        "product": "Integration Sync Service",
        "provider": None,
        "environment": Environment.PRODUCTION,
        "error_messages": ["connect ETIMEDOUT", "network timeout after 30s"],
        "logs": "endpoint=api.partner.example status=timeout duration_ms=30000",
        "reproduction_steps": ["Call partner API", "Observe timeout after 30s"],
        "recent_changes": ["Partner rotated their API endpoint IP range"],
        "customer_hypothesis": "Our network is fine, must be your side",
        "affected_users": 30,
        "total_users": 800,
        "reported_severity": Severity.P3,
        "first_seen_offset_days": 4,
    },
    "database_connection_exhaustion": {
        "subject": "Application errors under peak load",
        "description": "During peak traffic, requests fail with database errors.",
        "product": "Core Platform",
        "provider": None,
        "environment": Environment.PRODUCTION,
        "error_messages": [
            "FATAL: remaining connection slots are reserved",
            "connection pool exhausted",
        ],
        "logs": "database=postgres status=error message='too many connections' pool_size=20",
        "reproduction_steps": ["Generate peak load", "Observe connection errors"],
        "recent_changes": ["Scaled application instances from 4 to 12"],
        "customer_hypothesis": "Your database must be down",
        "affected_users": 600,
        "total_users": 1000,
        "reported_severity": Severity.P1,
        "first_seen_offset_days": 0,
    },
    "unknown_issue": {
        "subject": "Occasional slowness reported",
        "description": "A customer reports vague, intermittent slowness with no clear pattern.",
        "product": "AI Agent Platform",
        "provider": None,
        "environment": Environment.PRODUCTION,
        "error_messages": [],
        "logs": None,
        "reproduction_steps": [],
        "recent_changes": [],
        "customer_hypothesis": "Not sure, just feels slower lately",
        "affected_users": None,
        "total_users": None,
        "reported_severity": Severity.P3,
        "first_seen_offset_days": 5,
    },
}


def generate_ticket(
    scenario: str,
    customer_tier: CustomerTier | str = CustomerTier.ENTERPRISE,
    completeness: float = 1.0,
) -> SupportTicket:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'. Options: {sorted(SCENARIOS)}")
    if not 0.0 <= completeness <= 1.0:
        raise ValueError("completeness must be between 0.0 and 1.0")

    template = SCENARIOS[scenario]
    customer_tier = CustomerTier(customer_tier)

    seed = zlib.crc32(f"{scenario}:{customer_tier}:{completeness}".encode())
    rng = random.Random(seed)

    ticket_id = f"TICK-{seed % 100000:05d}"
    customer_id = f"CUST-{(seed // 7) % 100000:05d}"

    fields: dict = {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "customer_name": f"{scenario.replace('_', ' ').title()} Customer",
        "customer_tier": customer_tier,
        "subject": template["subject"],
        "description": template["description"],
        "reported_severity": template["reported_severity"],
        "affected_users": template["affected_users"],
        "total_users": template["total_users"],
        "product": template["product"],
        "provider": template["provider"],
        "environment": template["environment"],
        "error_messages": list(template["error_messages"]),
        "logs": template["logs"],
        "reproduction_steps": list(template["reproduction_steps"]),
        "first_seen_at": _NOW - timedelta(days=template["first_seen_offset_days"]),
        "reported_at": _NOW,
        "recent_changes": list(template["recent_changes"]),
        "customer_hypothesis": template["customer_hypothesis"],
        "metadata": {"scenario": scenario},
    }

    if completeness < 1.0:
        keep_count = round(completeness * len(_OPTIONAL_FIELDS))
        drop_count = len(_OPTIONAL_FIELDS) - keep_count
        fields_to_drop = rng.sample(_OPTIONAL_FIELDS, k=drop_count)
        list_fields = {
            "error_messages",
            "reproduction_steps",
            "recent_changes",
        }
        for field in fields_to_drop:
            fields[field] = [] if field in list_fields else None

    return SupportTicket(**fields)
