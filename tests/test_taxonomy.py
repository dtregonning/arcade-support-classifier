"""Tests for the taxonomy "system area" tag: the closed SystemArea enum,
its deterministic derivation from `domains`, and the AI fallback that
only ever fires when the rule engine found nothing.
"""

import importlib
import json
from pathlib import Path

import pydantic
import pytest

from support_automation.models.enrichment import SystemArea, TicketEnrichment
from support_automation.models.ticket import SupportTicket
from support_automation.services.enricher import RuleBasedEnricher
from support_automation.tools.enrich_ticket import enrich_ticket

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENRICHER = RuleBasedEnricher()

# `import support_automation.tools.enrich_ticket as X` would bind X to the
# `enrich_ticket` *function* (tools/__init__.py's `from .enrich_ticket
# import enrich_ticket` overwrites the submodule attribute on the `tools`
# package as a side effect of importing it) -- importlib sidesteps that.
enrich_ticket_module = importlib.import_module("support_automation.tools.enrich_ticket")


def _hero_ticket() -> SupportTicket:
    return SupportTicket(**json.loads((_REPO_ROOT / "data" / "hero_ticket.json").read_text()))


def test_system_area_is_a_closed_enum():
    """Constructing a TicketEnrichment with a value outside SystemArea must
    fail -- this is the actual "can't creep" guarantee, enforced by
    Pydantic, not by convention."""
    with pytest.raises(pydantic.ValidationError):
        TicketEnrichment(
            domains=[],
            signals=[],
            technologies=[],
            correlated_recent_changes=[],
            customer_hypotheses=[],
            observed_facts=[],
            possible_causes=[],
            uncorrelated_recent_changes=[],
            system_areas=["not_a_real_area"],
            system_area_source="unknown",
        )


def test_rule_based_enricher_maps_domains_to_areas_for_hero_ticket():
    enrichment = _ENRICHER.enrich(_hero_ticket())

    assert enrichment.system_area_source == "rule_based"
    assert set(enrichment.system_areas) == {
        SystemArea.IDENTITY,
        SystemArea.OAUTH,
        SystemArea.GOOGLE,
    }


def test_rule_based_enricher_leaves_unknown_ticket_unclassified():
    ticket = SupportTicket(ticket_id="TICK-EMPTY", description="It's not working.")
    enrichment = _ENRICHER.enrich(ticket)

    assert enrichment.domains == []
    assert enrichment.system_areas == [SystemArea.UNKNOWN]
    assert enrichment.system_area_source == "unknown"


def test_ai_fallback_not_consulted_when_rule_engine_found_a_domain(monkeypatch):
    """Cost/correctness guard: the AI classifier must never be called for a
    ticket the rule engine already classified."""
    calls = []
    monkeypatch.setattr(
        enrich_ticket_module,
        "classify_area",
        lambda evidence: calls.append(evidence) or SystemArea.TOOLKIT,
    )

    result = enrich_ticket(_hero_ticket())

    assert calls == []
    assert result.system_area_source == "rule_based"
    assert SystemArea.TOOLKIT not in result.system_areas


def test_ai_fallback_consulted_and_applied_when_rule_engine_found_nothing(monkeypatch):
    monkeypatch.setattr(
        enrich_ticket_module, "classify_area", lambda evidence: SystemArea.MCP_RUNTIME
    )
    ticket = SupportTicket(ticket_id="TICK-EMPTY", description="Tool calls are timing out.")

    result = enrich_ticket(ticket)

    assert result.system_areas == [SystemArea.MCP_RUNTIME]
    assert result.system_area_source == "ai_classified"


def test_ai_fallback_returning_none_leaves_ticket_unknown(monkeypatch):
    monkeypatch.setattr(enrich_ticket_module, "classify_area", lambda evidence: None)
    ticket = SupportTicket(ticket_id="TICK-EMPTY", description="It's not working.")

    result = enrich_ticket(ticket)

    assert result.system_areas == [SystemArea.UNKNOWN]
    assert result.system_area_source == "unknown"


def test_classify_area_is_a_noop_without_api_key(monkeypatch):
    from support_automation.services.ai_area_classifier import classify_area

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert classify_area("tool call to Gmail.SendEmail timed out") is None
