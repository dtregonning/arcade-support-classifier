import json
from pathlib import Path

from support_automation.models.ticket import SupportTicket
from support_automation.services.enricher import RuleBasedEnricher
from support_automation.services.router import route_ticket
from support_automation.services.severity import recommend_severity
from support_automation.services.validator import validate_ticket
from support_automation.tools.generate_ticket import generate_ticket
from support_automation.tools.recommend_actions import recommend_actions

_REPO_ROOT = Path(__file__).resolve().parents[1]
_enricher = RuleBasedEnricher()


def _load_hero_ticket() -> SupportTicket:
    data = json.loads((_REPO_ROOT / "data" / "hero_ticket.json").read_text())
    return SupportTicket(**data)


def test_hero_scenario_end_to_end():
    ticket = _load_hero_ticket()

    validation = validate_ticket(ticket)
    assert validation.valid is True
    assert validation.ready_for_automation is True

    enrichment = _enricher.enrich(ticket)
    assert "oauth" in enrichment.domains
    assert "google" in enrichment.domains
    assert any(
        s.type == "scope_mismatch" and s.value == "gmail.compose" for s in enrichment.signals
    )

    cause_labels = [c.cause for c in enrichment.possible_causes]
    assert "OAuth scope mismatch" in cause_labels

    severity = recommend_severity(ticket, enrichment)
    assert severity.recommended_severity == "P2"
    assert severity.reported_severity == "P1"
    assert severity.differs is True

    routing = route_ticket(ticket, enrichment)
    assert routing.queue == "identity-integrations"

    recommendation = recommend_actions(ticket, validation, enrichment, severity, routing)
    rejected_actions = [r.action for r in recommendation.actions_rejected]
    assert "page_infrastructure" in rejected_actions


def test_hero_scenario_rejects_okta_and_salesforce_as_causes():
    ticket = _load_hero_ticket()
    enrichment = _enricher.enrich(ticket)

    cause_text = " ".join(c.cause.lower() for c in enrichment.possible_causes)
    assert "okta" not in cause_text
    assert "salesforce" not in cause_text

    uncorrelated_text = " ".join(u.change.lower() for u in enrichment.uncorrelated_recent_changes)
    assert "salesforce" in uncorrelated_text


def test_hero_scenario_rejects_infrastructure_paging():
    ticket = _load_hero_ticket()
    validation = validate_ticket(ticket)
    enrichment = _enricher.enrich(ticket)
    severity = recommend_severity(ticket, enrichment)
    routing = route_ticket(ticket, enrichment)
    recommendation = recommend_actions(ticket, validation, enrichment, severity, routing)

    rejected_actions = {r.action for r in recommendation.actions_rejected}
    assert "page_infrastructure" in rejected_actions
    assert all(a.action != "page_infrastructure" for a in recommendation.actions)


def test_hero_scenario_does_not_claim_arcade_lost_tokens_as_fact():
    ticket = _load_hero_ticket()
    enrichment = _enricher.enrich(ticket)

    facts_text = " ".join(enrichment.observed_facts).lower()
    assert "arcade is losing tokens" not in facts_text
    assert "Arcade is losing tokens" in enrichment.customer_hypotheses


# --- Safety tests -----------------------------------------------------


def test_low_confidence_route_requires_human_review():
    ticket = generate_ticket("unknown_issue", completeness=1.0)
    enrichment = _enricher.enrich(ticket)
    routing = route_ticket(ticket, enrichment)
    assert routing.routing_confidence < 0.6
    assert routing.requires_human_review is True


def test_customer_claims_never_appear_in_observed_facts():
    for scenario in [
        "oauth_scope_mismatch",
        "kubernetes_crashloop",
        "kubernetes_oom",
        "api_rate_limit",
        "database_connection_exhaustion",
    ]:
        ticket = generate_ticket(scenario, completeness=1.0)
        enrichment = _enricher.enrich(ticket)
        assert ticket.customer_hypothesis not in enrichment.observed_facts
        for fact in enrichment.observed_facts:
            assert fact != ticket.customer_hypothesis


def test_unrelated_recent_changes_do_not_become_possible_causes():
    ticket = _load_hero_ticket()
    enrichment = _enricher.enrich(ticket)

    cause_evidence = " ".join(
        evidence for cause in enrichment.possible_causes for evidence in cause.evidence
    ).lower()
    assert "okta" not in cause_evidence
    assert "salesforce" not in cause_evidence
