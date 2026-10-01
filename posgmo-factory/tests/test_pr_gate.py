"""Deterministic pass/fail gate in front of pr_agent (agents/pr_gate/rules.py).

pr_agent's own prompt already says "only proceed if gate_result.status is
APPROVED AND review_result.passed is true" -- but that's an LLM instruction.
Confirmed live twice (2026-09-23, transactionNotification construction) that
pr_agent pushed real commits to the live repos anyway on runs where review
had explicitly failed. compute_pr_gate() is the Python-level replacement
that pr_stage checks before pr_agent ever gets invoked.
"""
import json

from agents.pr_gate.rules import compute_pr_gate


def _state(gate_status="APPROVED", passed=True, **extra):
    state = {
        "gate_result": json.dumps({"status": gate_status, "reason": "blocked reason", "fix": "fix hint"}),
        "review_result": json.dumps({"passed": passed, "issues": [{"artifact": "backend", "message": "x"}]}),
    }
    state.update(extra)
    return state


def test_approved_and_passed_may_proceed():
    may_proceed, blocked = compute_pr_gate(_state(gate_status="APPROVED", passed=True))
    assert may_proceed is True
    assert blocked == {}


def test_review_failed_blocks_even_when_gate_approved():
    """The live failure mode: gate_result APPROVED, review_result.passed
    explicitly False -- pr_agent must not run."""
    may_proceed, blocked = compute_pr_gate(_state(gate_status="APPROVED", passed=False))
    assert may_proceed is False
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "Review failed. Fix issues before PR."
    assert blocked["issues"]


def test_gate_blocked_blocks_regardless_of_review():
    may_proceed, blocked = compute_pr_gate(_state(gate_status="BLOCKED", passed=True))
    assert may_proceed is False
    assert blocked["reason"] == "blocked reason"
    assert blocked["fix"] == "fix hint"


def test_empty_review_result_blocks():
    """The other live failure mode: review_fix_loop never completed
    (reviewer_agent empty_turn), leaving review_result at its seeded '{}'
    default rather than an explicit passed:false -- must still block, not
    be treated as an implicit pass."""
    state = {
        "gate_result": json.dumps({"status": "APPROVED"}),
        "review_result": "{}",
    }
    may_proceed, blocked = compute_pr_gate(state)
    assert may_proceed is False
    assert blocked["status"] == "blocked"


def test_missing_keys_entirely_blocks():
    may_proceed, blocked = compute_pr_gate({})
    assert may_proceed is False


def test_fenced_json_is_parsed():
    state = {
        "gate_result": "```json\n" + json.dumps({"status": "APPROVED"}) + "\n```",
        "review_result": "```json\n" + json.dumps({"passed": True}) + "\n```",
    }
    may_proceed, _ = compute_pr_gate(state)
    assert may_proceed is True
