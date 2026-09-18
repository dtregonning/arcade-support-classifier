"""Ticket enrichment: turns raw ticket text/logs into structured technical
context.

`TicketEnricher` is a Protocol so an AI-backed implementation can be added
later (e.g. for free-text summarization or extraction on messier tickets)
without changing tools/enrich_ticket.py or anything downstream. The rule
engine here is intentionally the default and only implementation for the
MVP — the system must work with zero external API keys.

The one rule enforced throughout: `observed_facts` come only from
structured evidence (logs, error messages, subject/description text).
`customer_hypothesis` is carried through unmodified and is never used to
derive a fact or a possible cause. Recent changes are only ever
*correlated* (by keyword overlap with a detected domain) — they are never
promoted to a cause by themselves.
"""

from __future__ import annotations

import re
from typing import Protocol

from support_automation.models.enrichment import (
    PossibleCause,
    Signal,
    SystemArea,
    TicketEnrichment,
    UncorrelatedChange,
)
from support_automation.models.ticket import SupportTicket


class TicketEnricher(Protocol):
    def enrich(self, ticket: SupportTicket) -> TicketEnrichment: ...


_SCOPE_RE = re.compile(r"required_scopes\s*=\s*\[([^\]]*)\]", re.IGNORECASE)
_GRANTED_RE = re.compile(r"granted_scopes\s*=\s*\[([^\]]*)\]", re.IGNORECASE)

_CORRELATION_KEYWORDS: dict[str, list[str]] = {
    # Deliberately excludes "okta" and generic "auth" — a different identity
    # provider's certificate rotation is not evidence for a Google OAuth
    # scope mismatch just because both involve "auth" in some sense.
    "oauth": ["oauth", "scope", "token", "google", "gmail", "toolkit"],
    "google": ["google", "gmail", "toolkit", "oauth", "scope"],
    "kubernetes": ["kubernetes", "k8s", "node", "cluster", "deploy", "pod", "helm"],
    "database": ["database", "db", "connection", "pool", "postgres", "mysql"],
    "network": ["network", "dns", "timeout", "firewall", "proxy"],
    "api": ["api", "rate limit", "429", "endpoint", "gateway"],
    "configuration": ["config", "configuration", "setting"],
}


def evidence_text(ticket: SupportTicket) -> str:
    """Text drawn only from structured evidence fields, never the customer's
    hypothesis — keeps facts derived here separate from customer claims.
    Public (not `_`-prefixed): tools/enrich_ticket.py reuses this exact
    text for the optional AI area-classification fallback, so both paths
    see the same evidence."""
    parts = [
        ticket.subject or "",
        ticket.description or "",
        *ticket.error_messages,
        ticket.logs or "",
    ]
    return "\n".join(parts).lower()


def _detect_oauth_scope_mismatch(text: str) -> tuple[list[Signal], list[str]] | None:
    scope_match = _SCOPE_RE.search(text)
    granted_match = _GRANTED_RE.search(text)
    if not scope_match or not granted_match:
        return None

    required = {s.strip() for s in scope_match.group(1).split(",") if s.strip()}
    granted = {s.strip() for s in granted_match.group(1).split(",") if s.strip()}
    missing = sorted(required - granted)
    if not missing:
        return None

    signals = [
        Signal(
            type="scope_mismatch",
            value=scope,
            evidence=f"required_scopes includes {scope} but granted_scopes does not",
        )
        for scope in missing
    ]
    facts = [f"{scope} scope is required" for scope in missing]
    facts += [f"{scope} scope was not granted" for scope in missing]
    return signals, facts


def _detect_expired_token(text: str) -> tuple[list[Signal], list[str]] | None:
    if "token_expired" in text or ("token" in text and "expired" in text):
        return (
            [
                Signal(
                    type="expired_token",
                    value="token_expired",
                    evidence="Ticket evidence references an expired authorization token",
                )
            ],
            ["authorization token is expired"],
        )
    return None


def _detect_kubernetes(text: str) -> tuple[list[Signal], list[str]] | None:
    signals: list[Signal] = []
    facts: list[str] = []
    if "crashloopbackoff" in text:
        signals.append(
            Signal(
                type="container_crash",
                value="CrashLoopBackOff",
                evidence="Logs/description reference CrashLoopBackOff",
            )
        )
        facts.append("container is in CrashLoopBackOff")
    if "oomkilled" in text or "out of memory" in text:
        signals.append(
            Signal(
                type="oom_kill",
                value="OOMKilled",
                evidence="Logs/description reference OOMKilled or out-of-memory termination",
            )
        )
        facts.append("container was OOMKilled")
    return (signals, facts) if signals else None


def _detect_rate_limit(text: str) -> tuple[list[Signal], list[str]] | None:
    if "429" in text or "too many requests" in text or "rate limit" in text:
        return (
            [
                Signal(
                    type="rate_limit",
                    value="http_429",
                    evidence="Logs/description reference HTTP 429 / rate limiting",
                )
            ],
            ["upstream returned HTTP 429 (rate limited)"],
        )
    return None


def _detect_db_connection_exhaustion(text: str) -> tuple[list[Signal], list[str]] | None:
    has_db = "database" in text or "postgres" in text or "mysql" in text or " db " in text
    has_pool = (
        "connection pool" in text or "too many connections" in text or "pool exhausted" in text
    )
    if has_db and has_pool:
        return (
            [
                Signal(
                    type="db_connection_exhaustion",
                    value="connection_pool_exhausted",
                    evidence="Logs/description reference database connection pool exhaustion",
                )
            ],
            ["database connection pool is exhausted"],
        )
    return None


def _detect_network_timeout(text: str) -> tuple[list[Signal], list[str]] | None:
    if "timeout" in text and ("network" in text or "connect" in text or "timed out" in text):
        return (
            [
                Signal(
                    type="network_timeout",
                    value="network_timeout",
                    evidence="Logs/description reference a network timeout",
                )
            ],
            ["a network timeout was observed"],
        )
    return None


def _detect_http_500(text: str) -> tuple[list[Signal], list[str]] | None:
    if "500" in text and (
        "internal server error" in text or "http 500" in text or "status=500" in text
    ):
        return (
            [
                Signal(
                    type="http_500",
                    value="http_500",
                    evidence="Logs/description reference HTTP 500 responses",
                )
            ],
            ["upstream returned HTTP 500 responses"],
        )
    return None


def _detect_bad_configuration(text: str) -> tuple[list[Signal], list[str]] | None:
    if "misconfigured" in text or "misconfiguration" in text or "invalid configuration" in text:
        return (
            [
                Signal(
                    type="configuration_error",
                    value="invalid_configuration",
                    evidence="Logs/description reference invalid or misconfigured settings",
                )
            ],
            ["customer configuration is invalid"],
        )
    return None


# Each entry: (domains, technologies, confidence, cause label, reason_codes, detector)
_RULES: list[tuple[list[str], list[str], float, str, list[str], object]] = [
    (
        ["identity", "oauth", "google"],
        ["Google", "OAuth"],
        0.96,
        "OAuth scope mismatch",
        ["oauth_scope_mismatch", "google_provider"],
        _detect_oauth_scope_mismatch,
    ),
    (
        ["identity", "oauth"],
        ["OAuth"],
        0.85,
        "Expired OAuth token",
        ["expired_token"],
        _detect_expired_token,
    ),
    (
        ["platform", "kubernetes"],
        ["Kubernetes"],
        0.9,
        "Kubernetes workload crash",
        ["kubernetes_crash"],
        _detect_kubernetes,
    ),
    (
        ["integrations", "api"],
        [],
        0.8,
        "Upstream API rate limiting",
        ["http_429"],
        _detect_rate_limit,
    ),
    (
        ["platform", "database"],
        [],
        0.85,
        "Database connection pool exhaustion",
        ["db_connection_exhaustion"],
        _detect_db_connection_exhaustion,
    ),
    (
        ["network"],
        [],
        0.6,
        "Network timeout",
        ["network_timeout"],
        _detect_network_timeout,
    ),
    (
        ["platform", "api"],
        [],
        0.5,
        "Upstream HTTP 500 errors",
        ["http_500"],
        _detect_http_500,
    ),
    (
        ["configuration"],
        [],
        0.7,
        "Invalid customer configuration",
        ["configuration_error"],
        _detect_bad_configuration,
    ),
]


_DOMAIN_TO_AREA: dict[str, SystemArea] = {
    "identity": SystemArea.IDENTITY,
    "oauth": SystemArea.OAUTH,
    "google": SystemArea.GOOGLE,
    "platform": SystemArea.PLATFORM,
    "kubernetes": SystemArea.KUBERNETES,
    "integrations": SystemArea.INTEGRATIONS,
    "api": SystemArea.API,
    "database": SystemArea.DATABASE,
    "network": SystemArea.NETWORK,
    "configuration": SystemArea.CONFIGURATION,
}


def _system_areas(domains: list[str]) -> tuple[list[SystemArea], str]:
    """Deterministic mapping from the free-string `domains` this module
    already detects to the closed SystemArea taxonomy enum -- a pure
    relabeling, no new detection logic. `toolkit` and `mcp_runtime` have
    no rule-based path yet (nothing here currently detects them); they
    only ever get assigned by the AI fallback in tools/enrich_ticket.py
    when `domains` comes back empty."""
    areas = [_DOMAIN_TO_AREA[d] for d in domains if d in _DOMAIN_TO_AREA]
    if areas:
        return areas, "rule_based"
    return [SystemArea.UNKNOWN], "unknown"


def _technology_hits(text: str) -> list[str]:
    known = {
        "salesforce": "Salesforce",
        "okta": "Okta",
        "gmail": "Gmail",
        "google": "Google",
        "kubernetes": "Kubernetes",
        "postgres": "Postgres",
        "mysql": "MySQL",
    }
    return [label for keyword, label in known.items() if keyword in text]


def _correlate_recent_changes(
    recent_changes: list[str], domains: list[str]
) -> tuple[list[str], list[str]]:
    """Split recent changes into (correlated, uncorrelated) based on keyword
    overlap with detected domains. A change is correlated only if its text
    shares a keyword with one of the ticket's detected domains — proximity
    in time is not treated as evidence on its own."""
    keywords: set[str] = set()
    for domain in domains:
        keywords.update(_CORRELATION_KEYWORDS.get(domain, []))

    correlated: list[str] = []
    uncorrelated: list[str] = []
    for change in recent_changes:
        lowered = change.lower()
        if keywords and any(kw in lowered for kw in keywords):
            correlated.append(change)
        else:
            uncorrelated.append(change)
    return correlated, uncorrelated


class RuleBasedEnricher:
    """Deterministic, keyword/regex-driven enrichment. No external calls."""

    def enrich(self, ticket: SupportTicket) -> TicketEnrichment:
        text = evidence_text(ticket)

        domains: list[str] = []
        technologies: set[str] = set()
        signals: list[Signal] = []
        observed_facts: list[str] = []
        possible_causes: list[PossibleCause] = []

        for domain_list, techs, confidence, cause_label, reason_codes, detector in _RULES:
            result = detector(text)
            if result is None:
                continue
            rule_signals, rule_facts = result

            for domain in domain_list:
                if domain not in domains:
                    domains.append(domain)
            technologies.update(techs)
            signals.extend(rule_signals)
            observed_facts.extend(rule_facts)
            possible_causes.append(
                PossibleCause(
                    cause=cause_label,
                    confidence=confidence,
                    reason_codes=reason_codes,
                    evidence=[s.evidence for s in rule_signals],
                )
            )

        technologies.update(_technology_hits(text))

        if ticket.provider:
            technologies.add(ticket.provider)
            if ticket.provider.lower() == "google" and "google" not in domains:
                domains.append("google")

        correlated_changes, uncorrelated_changes = _correlate_recent_changes(
            ticket.recent_changes, domains
        )
        uncorrelated = [
            UncorrelatedChange(
                change=c, reason="No evidence links this change to the observed signals."
            )
            for c in uncorrelated_changes
        ]

        customer_hypotheses = [ticket.customer_hypothesis] if ticket.customer_hypothesis else []
        system_areas, system_area_source = _system_areas(domains)

        return TicketEnrichment(
            domains=domains,
            signals=signals,
            technologies=sorted(technologies),
            correlated_recent_changes=correlated_changes,
            customer_hypotheses=customer_hypotheses,
            observed_facts=observed_facts,
            possible_causes=possible_causes,
            uncorrelated_recent_changes=uncorrelated,
            system_areas=system_areas,
            system_area_source=system_area_source,
        )
