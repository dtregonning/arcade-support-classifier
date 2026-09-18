from support_automation.models.enrichment import TicketEnrichment
from support_automation.models.ticket import SupportTicket
from support_automation.services.severity import recommend_severity

_EMPTY_ENRICHMENT = TicketEnrichment(
    domains=[],
    signals=[],
    technologies=[],
    correlated_recent_changes=[],
    customer_hypotheses=[],
    observed_facts=[],
    possible_causes=[],
    uncorrelated_recent_changes=[],
)


def _ticket(**kwargs) -> SupportTicket:
    base = {"ticket_id": "T-1", "customer_id": "C-1", "description": "issue"}
    base.update(kwargs)
    return SupportTicket(**base)


def test_high_ratio_recommends_p1():
    ticket = _ticket(affected_users=950, total_users=1000)
    assessment = recommend_severity(ticket, _EMPTY_ENRICHMENT)
    assert assessment.recommended_severity == "P1"


def test_moderate_ratio_recommends_p2():
    ticket = _ticket(affected_users=330, total_users=1000)
    assessment = recommend_severity(ticket, _EMPTY_ENRICHMENT)
    assert assessment.recommended_severity == "P2"


def test_low_ratio_recommends_p3():
    ticket = _ticket(affected_users=5, total_users=1000)
    assessment = recommend_severity(ticket, _EMPTY_ENRICHMENT)
    assert assessment.recommended_severity == "P3"


def test_reported_severity_is_never_overwritten():
    ticket = _ticket(affected_users=5, total_users=1000, reported_severity="P1")
    assessment = recommend_severity(ticket, _EMPTY_ENRICHMENT)
    assert assessment.reported_severity == "P1"
    assert assessment.recommended_severity == "P3"
    assert assessment.differs is True


def test_matching_severity_does_not_flag_difference():
    ticket = _ticket(affected_users=950, total_users=1000, reported_severity="P1")
    assessment = recommend_severity(ticket, _EMPTY_ENRICHMENT)
    assert assessment.differs is False
