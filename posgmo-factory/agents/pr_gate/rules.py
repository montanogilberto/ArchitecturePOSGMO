"""
Deterministic pass/fail decision for whether pr_agent may run.

pr_agent's own prompt already says "only proceed if gate_result.status is
APPROVED AND review_result.passed is true, otherwise respond blocked and
stop" -- but that's an LLM instruction, and LLMs don't reliably follow it
under degraded conditions. Confirmed live twice while getting
transactionNotification through construction (2026-09-23): once on a run
where architect/database/backend/frontend all failed and review scored
database=0/backend=0/frontend=0 with 48 errors, and once where the
review_fix_loop itself never completed (reviewer_agent empty_turn) -- both
times pr_agent still called github_create_branch and pushed real commits to
the live POSVending / smartloans_backend repos before anyone reviewed
anything. Pushing to a real repo is exactly the kind of hard-to-reverse,
externally-visible action that must not depend on an LLM choosing to obey a
prompt, so this is checked deterministically in Python instead.
"""
from __future__ import annotations

from agents.retry import parse_json_object


def compute_pr_gate(state: dict) -> tuple[bool, dict]:
    """Returns (may_proceed, pr_result_if_blocked).

    pr_result_if_blocked is the same {"status": "blocked", ...} shape
    pr_agent's prompt already produces on a blocked run, so downstream
    consumers of pr_result see no shape change -- only the unreliable
    LLM-judgment path is removed. Ignored by the caller when may_proceed
    is True.
    """
    gate = parse_json_object(state.get("gate_result"))
    review = parse_json_object(state.get("review_result"))

    gate_ok = gate.get("status") == "APPROVED"
    review_ok = review.get("passed") is True

    if gate_ok and review_ok:
        return True, {}

    if not gate_ok:
        reason = gate.get("reason", "Architecture gate did not approve this specification.")
        return False, {"status": "blocked", "reason": reason, "fix": gate.get("fix")}

    return False, {
        "status": "blocked",
        "reason": "Review failed. Fix issues before PR.",
        "issues": review.get("issues", []),
    }
