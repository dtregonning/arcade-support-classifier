from support_automation.services.enricher import RuleBasedEnricher
from support_automation.services.router import route_ticket
from support_automation.tools.generate_ticket import generate_ticket

_enricher = RuleBasedEnricher()


def _route(scenario: str):
    ticket = generate_ticket(scenario, completeness=1.0)
    enrichment = _enricher.enrich(ticket)
    return route_ticket(ticket, enrichment)


def test_google_oauth_routes_to_identity_integrations():
    result = _route("oauth_scope_mismatch")
    assert result.queue == "identity-integrations"
    assert result.owner == "support-engineering"
    assert result.matched_rule == "oauth-google"


def test_kubernetes_crashloop_routes_to_platform():
    result = _route("kubernetes_crashloop")
    assert result.queue == "platform"
    assert result.matched_rule == "kubernetes-crash"


def test_kubernetes_oom_routes_to_platform():
    result = _route("kubernetes_oom")
    assert result.queue == "platform"
    assert result.matched_rule == "kubernetes-crash"


def test_rate_limit_routes_to_integrations():
    result = _route("api_rate_limit")
    assert result.queue == "integrations"
    assert result.matched_rule == "api-rate-limit"


def test_unknown_issue_falls_back_to_general_triage():
    result = _route("unknown_issue")
    assert result.queue == "general-triage"
    assert result.matched_rule == "unknown"
    assert result.requires_human_review is True


def test_higher_priority_rule_wins_when_multiple_match():
    # oauth_scope_mismatch matches both the oauth-google rule (priority 100)
    # and would also satisfy a generic oauth check; ensure the highest
    # priority, most specific rule is the one selected.
    result = _route("oauth_scope_mismatch")
    assert result.matched_rule == "oauth-google"
