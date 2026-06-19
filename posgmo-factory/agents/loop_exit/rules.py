"""Loop Exit — checks review_result and escalates if review passed."""
from __future__ import annotations

import json

from google.adk.tools.tool_context import ToolContext

MAX_ITERATIONS = 3


def check_and_exit(tool_context: ToolContext) -> dict:
    """
    Reads review_result from session state.
    - If review passed → sets escalate=True so LoopAgent exits and pr_agent runs.
    - If iteration limit reached → also escalates (prevents infinite loop).
    - Otherwise → returns issues so review_fixer_agent can act on them.
    """
    raw = tool_context.state.get("review_result", "{}")
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        result = {}

    passed = result.get("passed", False)
    iteration = tool_context.state.get("review_loop_iteration", 0) + 1
    tool_context.state["review_loop_iteration"] = iteration

    scores = result.get("scores", {})
    issues = result.get("issues", [])
    errors = [i for i in issues if i.get("severity") == "error"]
    summary = result.get("summary", "no review_result in state")

    print(
        f"[loop_exit] iteration={iteration}/{MAX_ITERATIONS} "
        f"passed={passed} errors={len(errors)} — {summary}",
        flush=True,
    )

    if passed or iteration >= MAX_ITERATIONS:
        reason = "review passed" if passed else f"max iterations ({MAX_ITERATIONS}) reached"
        print(f"[loop_exit] escalating — {reason}", flush=True)
        tool_context.actions.escalate = True
        return {
            "escalate": True,
            "reason": reason,
            "passed": passed,
            "scores": scores,
            "iteration": iteration,
        }

    # Not passed yet — return errors so review_fixer can fix them
    return {
        "escalate": False,
        "iteration": iteration,
        "errors": errors,
        "scores": scores,
        "summary": summary,
    }
