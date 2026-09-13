"""Phase 4 — dynamic panel selection (doc §6). Deterministic, no LLM."""

from debate_v2.panel import select_challengers


def test_always_includes_core_challengers():
    selected = select_challengers("create a new module for rewards")
    assert "domain_expert" in selected
    assert "critic" in selected


def test_generic_request_does_not_pull_in_conditional_experts():
    selected = select_challengers("create a new module for rewards")
    assert "security_expert" not in selected
    assert "integration_expert" not in selected


def test_payment_request_activates_security_expert():
    selected = select_challengers("create a new module for card payment processing")
    assert "security_expert" in selected


def test_notification_request_activates_integration_expert():
    selected = select_challengers("add WhatsApp notifications for order status")
    assert "integration_expert" in selected


def test_multiple_triggers_can_combine():
    selected = select_challengers("build a secure chat screen for KYC document upload")
    assert "security_expert" in selected      # kyc
    assert "integration_expert" in selected   # chat
    assert "ux_expert" in selected            # screen


def test_every_selected_role_is_a_registered_challenger():
    from debate_v2.experts import CHALLENGER_ROLE_BLURBS
    for request in ["create a new module for rewards", "add secure payment with push notifications"]:
        for role in select_challengers(request):
            assert role in CHALLENGER_ROLE_BLURBS, f"{role!r} has no registered blurb"
