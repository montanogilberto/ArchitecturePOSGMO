"""Deterministic tests for the Context Agent's evidence gathering (Phase 2,
acceptance criterion #2: evidence before judgment). No LLM calls — runs
against the real repo state, same as production would."""

from debate_v2.context import gather_context


def test_rewards_request_finds_the_real_draft_prds():
    verified, assumptions = gather_context("create a new module for rewards")
    verified_claims = " ".join(v.claim for v in verified)
    assert "prd_posRewardBalance.json" in verified_claims
    assert "5 draft PRD file(s)" in verified_claims
    # Every verified fact must carry a source citation.
    assert all(v.source for v in verified)


def test_rewards_request_surfaces_the_pre_existing_adjacent_concept():
    verified, _ = gather_context("create a new module for rewards")
    claims = " ".join(v.claim for v in verified)
    assert "existing loan-behavior rewardBalances table" in claims


def test_unknown_domain_produces_assumptions_not_fabricated_facts():
    """A negative existence check ("no generated output exists yet") is
    itself a legitimately verified fact — it's the POSITIVE claims (prior
    design docs, knowledge-base coverage) that must never be fabricated for
    a domain with no real trace in the repo."""
    verified, assumptions = gather_context("create a new module for zzzznotarealdomain")
    verified_claims = " ".join(v.claim for v in verified)
    assert "draft PRD file(s) already exist" not in verified_claims
    assert "is mentioned in the architecture knowledge base" not in verified_claims
    assert any("zzzznotarealdomain" in a.claim for a in assumptions)


def test_empty_request_yields_only_assumptions():
    verified, assumptions = gather_context("")
    assert verified == []
    assert len(assumptions) == 1
