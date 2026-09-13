"""End-to-end acceptance test: a REAL Gemini-backed debate over "create a
new module for rewards", exercising the full Phase 2-6 pipeline (evidence
gathering, intake gate, blind proposals, dynamic multi-expert challenge,
same-agent rebuttal, convergence/escalation). Skipped automatically when no
API key is configured (CI without secrets, or a fresh clone).

Asserts STRUCTURAL/provenance guarantees, not a specific semantic outcome —
the actual LLM content is real and not fully predictable (including
WHETHER the intake gate decides to escalate for clarification), so this
checks that the plumbing behaved correctly given whatever the models
actually decided, not that they reached one scripted conclusion."""
import asyncio
import os

import pytest
from dotenv import load_dotenv

from debate_schema import DebateSession, read_blackboard, read_status
from debate_v2.run import run_debate

load_dotenv()

pytestmark = pytest.mark.skipif(
    not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
    reason="requires a live Gemini API key (GOOGLE_API_KEY or GEMINI_API_KEY)",
)


def test_rewards_debate_changes_the_decision_through_interaction():
    state = asyncio.run(run_debate("create a new module for rewards"))
    status = read_status(state)

    # #2 — evidence gathered before any expert (or the intake gate) spoke.
    verified = read_blackboard(state, "context_verified_facts")
    assert len(verified) > 0
    assert any("posRewardBalance" in v.claim for v in verified)

    proposals = read_blackboard(state, "proposals")

    if status.needs_user_input and not proposals:
        # Phase 6: intake judged the request too ambiguous to debate yet —
        # a valid, real outcome. Just prove the escalation is well-formed.
        assert status.escalation_reason
        assert len(status.open_questions) >= 1
        return

    participants = read_blackboard(state, "participants")
    challenges = read_blackboard(state, "challenges")
    rebuttals = read_blackboard(state, "rebuttals")
    conflicts = read_blackboard(state, "conflicts")
    decisions = read_blackboard(state, "decisions")
    rejected = read_blackboard(state, "rejected_alternatives")

    # #1 (structural corroboration) — exactly one proposal per proposer,
    # both present, both independently non-trivial.
    assert {p.agent for p in proposals} == {"product_owner", "architect"}
    assert len(proposals) == 2
    assert all(len(p.claim) > 10 for p in proposals)

    # #3 — real challenge(s) exist (Phase 4: 1+ dynamically-selected
    # challengers), each targeting one of the two proposers.
    assert len(challenges) >= 1
    for c in challenges:
        assert c.target in {"product_owner", "architect"}
    challenger_names = {c.agent for c in challenges}
    assert challenger_names <= {p.agent for p in participants} - {"product_owner", "architect"}

    # #4 — every DISTINCT challenged proposer produced exactly one rebuttal
    # from the SAME agent instance (bundling all challenges against them —
    # Phase 4 generalization of "the same agent revises").
    challenged_targets = {c.target for c in challenges}
    assert {r.agent for r in rebuttals} == challenged_targets
    for r in rebuttals:
        assert r.agent in {"product_owner", "architect"}

    # #7 — convergence gate actually ran: EXACTLY one of {decided, escalated}
    # is true — never neither (gate silently skipped), never both.
    assert (len(decisions) == 1) != (status.needs_user_input is True)

    if decisions:
        decision = decisions[0]
        # #8 — provenance: the decision's claim/evidence trace back to an
        # actual blackboard message, never invented text.
        all_claims = {p.claim for p in proposals} | {r.claim for r in rebuttals} | {
            r.alternative for r in rebuttals if r.alternative
        }
        assert decision.selected_claim in all_claims
        all_evidence_sets = [p.evidence for p in proposals] + [r.evidence for r in rebuttals]
        assert decision.evidence in all_evidence_sets

        # #5 — the losing proposal(s) survive as rejected_alternatives, not deleted.
        assert len(rejected) >= 1
        rejected_claims = {r.claim for r in rejected}
        assert decision.selected_claim not in rejected_claims

    # #6 — chairperson never manufactured a claim: conflict record references
    # only participants who actually spoke.
    all_agent_names = {p.agent for p in participants}
    for c in conflicts:
        assert set(c.participants) <= all_agent_names

    # #9 — the full debate is reconstructable from state alone.
    session = DebateSession(
        request=state["request"],
        verified_facts=verified,
        assumptions=read_blackboard(state, "context_assumptions"),
        evidence=read_blackboard(state, "context_evidence"),
        participants=participants,
        proposals=proposals,
        challenges=challenges,
        rebuttals=rebuttals,
        conflicts=conflicts,
        scores=read_blackboard(state, "scores"),
        risks=read_blackboard(state, "risks"),
        decisions=decisions,
        rejected_alternatives=rejected,
        status=status,
    )
    assert len(session.participants) >= 3   # 2 proposers + at least 1 challenger
    assert len(session.proposals) == 2
