"""Policy-driven ticket routing.

All routing logic lives in config/routing_rules.yaml, not in this file.
This module only knows how to evaluate a `when` clause against a ticket and
its enrichment, and pick the highest-priority match. Editing routing
behavior should never require a code change.
"""

from __future__ import annotations

from typing import Any

import yaml

from support_automation._config_paths import config_path
from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.routing import RoutingResult
from support_automation.models.ticket import SupportTicket

_CONFIG_PATH = config_path("routing_rules.yaml")

_LOW_CONFIDENCE_THRESHOLD = 0.6


def _load_rules() -> list[dict[str, Any]]:
    with _CONFIG_PATH.open() as f:
        data = yaml.safe_load(f)
    return sorted(data["rules"], key=lambda r: r["priority"], reverse=True)


_RULES = _load_rules()


def _signal_matches(enrichment: TicketEnrichment, name: str) -> bool:
    return any(s.type == name or s.value == name for s in enrichment.signals)


def _rule_matches(
    when: dict[str, Any], ticket: SupportTicket, enrichment: TicketEnrichment
) -> bool:
    if when.get("always"):
        return True

    if "domain" in when and when["domain"] not in enrichment.domains:
        return False

    if "domain_any" in when and not any(d in enrichment.domains for d in when["domain_any"]):
        return False

    if "provider" in when:
        wanted = when["provider"].lower()
        provider_ok = (ticket.provider or "").lower() == wanted
        tech_ok = wanted in (t.lower() for t in enrichment.technologies)
        if not (provider_ok or tech_ok):
            return False

    if "signal" in when and not _signal_matches(enrichment, when["signal"]):
        return False

    if "signal_any" in when and not any(_signal_matches(enrichment, s) for s in when["signal_any"]):
        return False

    return True


def _reason_codes(enrichment: TicketEnrichment) -> list[str]:
    codes: set[str] = set()
    for cause in enrichment.possible_causes:
        codes.update(cause.reason_codes)
    return sorted(codes) if codes else ["no_matching_signal"]


def route_ticket(ticket: SupportTicket, enrichment: TicketEnrichment) -> RoutingResult:
    for rule in _RULES:
        if _rule_matches(rule["when"], ticket, enrichment):
            confidence = rule["confidence"]
            requires_human_review = (
                rule["id"] == "unknown" or confidence < _LOW_CONFIDENCE_THRESHOLD
            )
            return RoutingResult(
                queue=rule["route"]["queue"],
                owner=rule["route"]["owner"],
                matched_rule=rule["id"],
                routing_confidence=confidence,
                reason_codes=_reason_codes(enrichment),
                requires_human_review=requires_human_review,
            )

    raise RuntimeError("No routing rule matched; routing_rules.yaml must include a fallback rule")
