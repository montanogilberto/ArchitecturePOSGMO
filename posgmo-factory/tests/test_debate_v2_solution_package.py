"""Phase 7 — Solution Package / ADR rendering. No LLM calls; builds a
synthetic blackboard the same shape debate_v2/orchestrator.py produces."""

import json

from debate_schema import DebateStatus, Participant, Severity, seed_blackboard_state, write_status
from debate_v2.orchestrator import compute_decision_or_escalation
from debate_v2.solution_package import render_solution_package
from tests.test_debate_v2_decision_logic import _add_challenge, _add_rebuttal, _base_state


def test_solution_package_covers_all_sections_for_a_decided_debate():
    state = _base_state()
    parts = [Participant(agent="product_owner", role="product_owner"),
             Participant(agent="architect", role="architect"),
             Participant(agent="critic", role="critic")]
    state["participants"] = json.dumps([p.model_dump(mode="json") for p in parts])

    _add_challenge(state, target="architect", severity=Severity.medium)
    _add_rebuttal(state, agent="architect", alternative="Revised claim", confidence=0.95)
    delta = compute_decision_or_escalation(state)
    state.update(delta)

    package = render_solution_package(state)

    assert "# Solution Package" in package
    assert "## 1. Problem Statement" in package
    assert state["request"] in package
    assert "## 4. Candidate Solutions" in package
    assert "Extend existing capability" in package   # product_owner's original proposal
    assert "## 5. Debate Summary" in package
    assert "## 7. Decision" in package
    assert "Revised claim" in package
    assert "## 8. Rejected Alternatives" in package
    assert "## 10. Next Step" in package


def test_solution_package_renders_escalation_without_a_decision():
    state = seed_blackboard_state()
    state["request"] = "make it better"
    state["status"] = write_status(DebateStatus(
        needs_user_input=True, escalation_reason="too vague",
        open_questions=["What are we improving?"],
    ))

    package = render_solution_package(state)
    assert "Clarification Needed" in package
    assert "too vague" in package
    assert "What are we improving?" in package
    assert "## 4. Candidate Solutions" not in package  # never got that far
