from support_automation.models.ticket import SupportTicket
from support_automation.services.validator import validate_ticket
from support_automation.tools.generate_ticket import generate_ticket


def test_missing_fields_detected():
    ticket = SupportTicket(ticket_id="T-1", customer_id="C-1", description="Something broke")
    result = validate_ticket(ticket)
    assert "affected_users" in result.missing_fields
    assert "first_seen_at" in result.missing_fields
    assert "provider" in result.missing_fields


def test_completeness_score_is_consistent_for_same_input():
    ticket = generate_ticket("oauth_scope_mismatch", completeness=0.7)
    result_a = validate_ticket(ticket)
    result_b = validate_ticket(ticket.model_copy())
    assert result_a.completeness_score == result_b.completeness_score


def test_full_ticket_scores_higher_than_sparse_ticket():
    full = generate_ticket("oauth_scope_mismatch", completeness=1.0)
    sparse = generate_ticket("oauth_scope_mismatch", completeness=0.2)
    assert validate_ticket(full).completeness_score > validate_ticket(sparse).completeness_score


def test_unsupported_severity_warning_generated():
    ticket = SupportTicket(
        ticket_id="T-2",
        customer_id="C-2",
        description="One user cannot log in",
        reported_severity="P1",
        affected_users=1,
        total_users=1000,
    )
    result = validate_ticket(ticket)
    codes = [w.code for w in result.warnings]
    assert "severity_unsupported" in codes


def test_no_severity_warning_when_impact_supports_p1():
    ticket = SupportTicket(
        ticket_id="T-3",
        customer_id="C-3",
        description="Production is fully down",
        reported_severity="P1",
        affected_users=950,
        total_users=1000,
    )
    result = validate_ticket(ticket)
    codes = [w.code for w in result.warnings]
    assert "severity_unsupported" not in codes


def test_sparse_ticket_not_ready_for_automation():
    ticket = SupportTicket(ticket_id="T-4", description="It's not working")
    result = validate_ticket(ticket)
    assert result.ready_for_automation is False
