"""Unit tests for debate_v2.orchestrator.compute_decision_or_escalation() —
the pure COMPARE/DECIDE function, no LLM calls, no ADK Runner. Covers
acceptance criteria #5 (rejected alternative survives), #6 (chairperson
cannot manufacture a claim), #7 (unresolved high-severity conflict blocks
convergence), and #8 (decision provenance)."""

import json

from debate_schema import (
    Conflict, DebateMessage, DebatePhase, MessageType, Severity,
    append_to_blackboard, read_blackboard, read_status, seed_blackboard_state,
)
from debate_v2.orchestrator import compute_decision_or_escalation


def _base_state():
    state = seed_blackboard_state()
    state["request"] = "create a new module for rewards"
    po = DebateMessage(round=1, phase=DebatePhase.propose, agent="product_owner",
                        type=MessageType.proposal, claim="Extend existing capability",
                        evidence=["repo:a"], confidence=0.6)
    arch = DebateMessage(round=1, phase=DebatePhase.propose, agent="architect",
                          type=MessageType.proposal, claim="Create new module",
                          evidence=["repo:b"], confidence=0.7)
    state["proposals"] = append_to_blackboard(state, "proposals", po)
    state["proposals"] = append_to_blackboard(state, "proposals", arch)
    return state


def _add_challenge(state, target, severity):
    challenge = DebateMessage(round=2, phase=DebatePhase.challenge, agent="critic",
                               type=MessageType.challenge, target=target,
                               claim=f"Disagree with {target}", evidence=["repo:c"], confidence=0.8)
    state["challenges"] = append_to_blackboard(state, "challenges", challenge)
    conflict = Conflict(id="c1", description=challenge.claim,
                         participants=sorted(["critic", target]), severity=severity)
    state["conflicts"] = append_to_blackboard(state, "conflicts", conflict)
    return challenge


def _add_rebuttal(state, agent, alternative, confidence, claim="original claim restated"):
    """`claim` should match what the agent's DEFENDED (unchanged) position
    actually reads as — when alternative is None, a faithful defense
    restates the original, it doesn't say something unrelated."""
    rebuttal = DebateMessage(round=3, phase=DebatePhase.rebut, agent=agent,
                              type=MessageType.rebuttal, target="critic",
                              claim=claim, evidence=["repo:d"], reasoning_summary="because evidence",
                              alternative=alternative, confidence=confidence)
    state["rebuttals"] = append_to_blackboard(state, "rebuttals", rebuttal)
    return rebuttal


# ---------------------------------------------------------------------------
# #7 — high-severity unresolved conflict blocks automatic convergence
# ---------------------------------------------------------------------------

def test_high_severity_unresolved_conflict_escalates_instead_of_deciding():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.high)
    _add_rebuttal(state, agent="architect", alternative=None, confidence=0.7)  # defends, doesn't revise

    delta = compute_decision_or_escalation(state)
    state.update(delta)

    status = read_status(state)
    assert status.needs_user_input is True
    assert "not resolved" in status.escalation_reason
    assert json.loads(state.get("decisions", "[]")) == []


def test_high_severity_conflict_resolved_by_alternative_does_converge():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.high)
    _add_rebuttal(state, agent="architect", alternative="Revised: extend existing", confidence=0.85)

    delta = compute_decision_or_escalation(state)
    state.update(delta)

    status = read_status(state)
    assert status.needs_user_input is False
    decisions = read_blackboard(state, "decisions")
    assert len(decisions) == 1


def test_low_severity_conflict_converges_even_without_revision():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.low)
    _add_rebuttal(state, agent="architect", alternative=None, confidence=0.9)

    delta = compute_decision_or_escalation(state)
    state.update(delta)

    assert read_status(state).needs_user_input is False
    assert len(read_blackboard(state, "decisions")) == 1


# ---------------------------------------------------------------------------
# #6 — chairperson selects among claims, never manufactures one
# ---------------------------------------------------------------------------

def test_decision_claim_is_always_copied_verbatim_from_a_blackboard_message():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.medium)
    _add_rebuttal(state, agent="architect", alternative="Revised claim text", confidence=0.95)

    delta = compute_decision_or_escalation(state)
    state.update(delta)
    decision = read_blackboard(state, "decisions")[0]

    all_claims = {"Extend existing capability", "Create new module", "Revised claim text"}
    assert decision.selected_claim in all_claims


def test_compare_step_honestly_picks_higher_confidence_not_the_rebuttal_by_default():
    """Regression test for a real bug caught during the Phase 2 smoke run:
    the first implementation always picked the rebuttal as the winner even
    when the untouched proposal had higher confidence, and mislabeled the
    rejection reason as 'lower confidence' when it was actually higher."""
    state = _base_state()  # architect proposed "Create new module" at confidence 0.7
    _add_challenge(state, target="architect", severity=Severity.medium)
    # architect defends unchanged at confidence 0.5 — LOWER than product_owner's 0.6.
    _add_rebuttal(state, agent="architect", alternative=None, confidence=0.5, claim="Create new module")

    delta = compute_decision_or_escalation(state)
    state.update(delta)
    decision = read_blackboard(state, "decisions")[0]
    rejected = read_blackboard(state, "rejected_alternatives")

    assert decision.selected_claim == "Extend existing capability"  # product_owner's, confidence 0.6
    assert decision.confidence == 0.6
    rejected_claims = {r.claim: r for r in rejected}
    assert "Create new module" in rejected_claims
    assert "0.50" in rejected_claims["Create new module"].reason
    assert "0.60" in rejected_claims["Create new module"].reason


# ---------------------------------------------------------------------------
# #5 — rejected proposal survives, is never deleted
# ---------------------------------------------------------------------------

def test_rejected_alternative_is_recorded_not_discarded():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.medium)
    _add_rebuttal(state, agent="architect", alternative="Revised claim", confidence=0.95)

    delta = compute_decision_or_escalation(state)
    state.update(delta)
    rejected = read_blackboard(state, "rejected_alternatives")
    rejected_claims = {r.claim for r in rejected}

    assert "Create new module" in rejected_claims          # superseded by own rebuttal
    assert "Extend existing capability" in rejected_claims  # lower confidence than 0.95


# ---------------------------------------------------------------------------
# #8 — decision provenance points back to the winning message's evidence
# ---------------------------------------------------------------------------

def test_decision_evidence_matches_the_winning_messages_evidence_exactly():
    state = _base_state()
    _add_challenge(state, target="architect", severity=Severity.medium)
    _add_rebuttal(state, agent="architect", alternative="Revised claim", confidence=0.95)

    delta = compute_decision_or_escalation(state)
    state.update(delta)
    decision = read_blackboard(state, "decisions")[0]

    assert decision.evidence == ["repo:d"]  # exactly the rebuttal's evidence, nothing added


def test_no_challenge_yet_returns_empty_delta():
    state = _base_state()
    assert compute_decision_or_escalation(state) == {}
