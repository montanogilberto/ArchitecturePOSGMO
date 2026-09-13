"""Phase 6 — intake gate schema and status plumbing. No LLM calls."""

from debate_schema import DebateStatus, read_status, write_status
from debate_v2.intake import IntakeOutput


def test_intake_output_defaults_to_no_questions():
    out = IntakeOutput(is_ambiguous=False, reasoning="evidence is comprehensive")
    assert out.questions == []


def test_intake_output_can_carry_questions():
    out = IntakeOutput(
        is_ambiguous=True, reasoning="two unrelated meanings of 'rewards' exist",
        questions=["Do you mean the POS loyalty program or something else?"],
    )
    assert len(out.questions) == 1


def test_debate_status_round_trips_open_questions():
    status = DebateStatus(
        needs_user_input=True, escalation_reason="ambiguous intent",
        open_questions=["Which domain?", "Which user role triggers this?"],
    )
    state = {"status": write_status(status)}
    reloaded = read_status(state)
    assert reloaded.needs_user_input is True
    assert reloaded.open_questions == ["Which domain?", "Which user role triggers this?"]


def test_default_status_has_no_open_questions():
    assert read_status({}).open_questions == []
