"""Phase 5 — convergence/escalation additions: the panel-size budget guard
(doc §14's "maximum ... reached" stopping condition, applied to panel size
since the round protocol itself is already fixed-length) and the
transparency ScoreCard (doc §13). No LLM calls."""

from debate_schema import Severity, read_blackboard
from debate_v2.orchestrator import compute_decision_or_escalation
from debate_v2.panel import MAX_CHALLENGERS, select_challengers
from tests.test_debate_v2_decision_logic import _add_challenge, _add_rebuttal, _base_state


def test_panel_size_never_exceeds_budget():
    # A request engineered to hit every keyword trigger at once.
    kitchen_sink = (
        "create a new module for a secure payment ui screen with whatsapp "
        "notifications, acceptance tests, and compliance audit rules"
    )
    selected = select_challengers(kitchen_sink)
    assert len(selected) <= MAX_CHALLENGERS


def test_always_active_roles_survive_the_cap():
    kitchen_sink = (
        "create a new module for a secure payment ui screen with whatsapp "
        "notifications, acceptance tests, and compliance audit rules"
    )
    selected = select_challengers(kitchen_sink)
    assert "domain_expert" in selected
    assert "critic" in selected


def test_decision_delta_includes_a_scorecard_per_candidate():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.medium)
    _add_rebuttal(state, agent="architect", alternative="Revised claim", confidence=0.9)

    delta = compute_decision_or_escalation(state)
    state.update(delta)

    scores = read_blackboard(state, "scores")
    assert len(scores) == 2  # one per proposer's final candidate
    subjects = {s.subject for s in scores}
    assert "Revised claim" in subjects
    assert "Extend existing capability" in subjects
    for s in scores:
        assert s.total is not None
        assert 0.0 <= s.total <= 10.0
