"""Tests for the debate blackboard schema and its (de)serialization helpers."""

import pytest
from pydantic import ValidationError

from debate_schema import (
    BLACKBOARD_LIST_KEYS,
    Conflict,
    ContextItem,
    ContextItemKind,
    DebateMessage,
    DebatePhase,
    DebateSession,
    DebateStatus,
    Decision,
    MessageType,
    Participant,
    RejectedAlternative,
    Risk,
    ScoreCard,
    ScoreDimension,
    Severity,
    append_to_blackboard,
    read_blackboard,
    read_status,
    seed_blackboard_state,
    write_status,
)


# ---------------------------------------------------------------------------
# DebateMessage
# ---------------------------------------------------------------------------

def test_debate_message_requires_confidence_between_0_and_1():
    with pytest.raises(ValidationError):
        DebateMessage(
            round=1, phase=DebatePhase.propose, agent="architect",
            type=MessageType.proposal, claim="do X", confidence=1.5,
        )


def test_debate_message_valid():
    msg = DebateMessage(
        round=2, phase=DebatePhase.challenge, agent="critic", type=MessageType.challenge,
        target="architect", claim="Income already exists",
        evidence=["repo:smartloans_backend/modules/income.py"],
        confidence=0.85,
    )
    assert msg.target == "architect"
    assert msg.evidence[0].startswith("repo:")


# ---------------------------------------------------------------------------
# DebateSession — full blackboard assembly
# ---------------------------------------------------------------------------

def test_debate_session_assembles_full_blackboard():
    session = DebateSession(
        request="create a new module for rewards",
        verified_facts=[ContextItem(kind=ContextItemKind.verified_fact, claim="posReward* tables exist",
                                     source="repo:smartloans_backend/sql/sp_posReward.sql")],
        participants=[Participant(agent="architect", role="architect"),
                      Participant(agent="critic", role="critic")],
        proposals=[DebateMessage(round=1, phase=DebatePhase.propose, agent="architect",
                                  type=MessageType.proposal, claim="Create new Rewards module", confidence=0.6)],
        challenges=[DebateMessage(round=2, phase=DebatePhase.challenge, agent="critic", target="architect",
                                   type=MessageType.challenge, claim="Duplicates posReward*", confidence=0.85)],
        conflicts=[Conflict(id="c1", description="new module vs extend existing",
                             participants=["architect", "critic"], severity=Severity.high)],
        scores=[ScoreCard(subject="Create new Rewards module",
                           scores={ScoreDimension.reuse: 2.0, ScoreDimension.security: 8.0})],
        risks=[Risk(description="duplicate business logic", severity=Severity.medium)],
        decisions=[Decision(round=4, selected_claim="Extend existing Rewards capability",
                             rationale="reuse posReward*", confidence=0.9)],
        rejected_alternatives=[RejectedAlternative(claim="Create new Rewards module",
                                                     reason="duplicates posReward*")],
        status=DebateStatus(round=4, phase=DebatePhase.decide, confidence=0.9),
    )
    assert session.decisions[0].decided_by == "debate"
    assert session.rejected_alternatives[0].claim == session.proposals[0].claim
    # Rejected proposal != deleted proposal: both must coexist.
    assert len(session.proposals) == 1 and len(session.rejected_alternatives) == 1


# ---------------------------------------------------------------------------
# Flat session-state (de)serialization helpers
# ---------------------------------------------------------------------------

def test_seed_blackboard_state_covers_every_list_key():
    seeded = seed_blackboard_state()
    for key in BLACKBOARD_LIST_KEYS:
        assert seeded[key] == "[]"
    assert "status" in seeded


def test_append_and_read_blackboard_round_trip():
    state = seed_blackboard_state()
    msg = DebateMessage(round=1, phase=DebatePhase.propose, agent="architect",
                         type=MessageType.proposal, claim="Create new Rewards module", confidence=0.6)
    state["proposals"] = append_to_blackboard(state, "proposals", msg)

    msg2 = DebateMessage(round=1, phase=DebatePhase.propose, agent="product_owner",
                          type=MessageType.proposal, claim="AI orchestration layer", confidence=0.5)
    state["proposals"] = append_to_blackboard(state, "proposals", msg2)

    roundtripped = read_blackboard(state, "proposals")
    assert len(roundtripped) == 2
    assert roundtripped[0].claim == "Create new Rewards module"
    assert roundtripped[1].agent == "product_owner"


def test_append_to_blackboard_rejects_wrong_model_type():
    state = seed_blackboard_state()
    wrong_item = Risk(description="not a message", severity=Severity.low)
    with pytest.raises(TypeError):
        append_to_blackboard(state, "proposals", wrong_item)


def test_append_to_blackboard_rejects_unknown_key():
    state = seed_blackboard_state()
    msg = DebateMessage(round=1, phase=DebatePhase.propose, agent="architect",
                         type=MessageType.proposal, claim="x", confidence=0.5)
    with pytest.raises(ValueError):
        append_to_blackboard(state, "not_a_real_key", msg)


def test_status_round_trip_defaults_when_absent():
    state = {}
    status = read_status(state)
    assert status == DebateStatus()

    status.round = 3
    status.needs_user_input = True
    status.escalation_reason = "unresolved high-severity conflict"
    state["status"] = write_status(status)

    reloaded = read_status(state)
    assert reloaded.round == 3
    assert reloaded.needs_user_input is True
    assert reloaded.escalation_reason == "unresolved high-severity conflict"
