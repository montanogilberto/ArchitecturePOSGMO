"""
Pipeline execution diagnostics.

Experiment 1 (Commercial Factory / leadCapture, 2026-09-16) showed that
review_fix_loop's three sub-agents (reviewer_agent, loop_exit_agent,
review_fixer_agent) can silently produce nothing for an entire run -- no tool
call, no text, no error raised -- while the pipeline completes normally and
reports success. A second run (Experiment 1B) showed the same failure mode
hitting prd_enricher_agent, database_agent, and fixer_agent too: an LLM turn
either comes back completely empty, or the model attempts a tool call ADK
can't parse (error_code == MALFORMED_FUNCTION_CALL). Either way, the intended
work for that stage never happens, and none of it is visible anywhere except
by reading raw ADK events.

This module classifies events as they stream past in orchestrator.run_factory
so a run's diagnostics are attached to the saved session state instead of
requiring that manual, event-by-event inspection every time.

Purely additive: never blocks, retries, or changes agent behavior.
"""
from __future__ import annotations

from typing import Any, Optional

# The only stage in the current pipeline with no LLM call at all (a plain
# BaseAgent that runs compute_gate_result() directly). Every other stage --
# including ones whose own docstrings say "no LLM involved" (fixer_agent,
# reviewer_agent) -- is an LLM Agent wrapping a single tool call, and is
# therefore expected to produce a function_call, text, or a state_delta on
# every turn. See agents/decision_gate/agent.py vs agents/fixer/agent.py.
PURE_PYTHON_AGENTS = {"decision_gate_agent"}


def classify_event(event: Any) -> Optional[dict]:
    """Returns a diagnostic dict if this event looks like a silent failure
    for an LLM-backed agent turn (empty turn or malformed tool call), else
    None."""
    author = getattr(event, "author", None)
    if not author or author in PURE_PYTHON_AGENTS:
        return None

    error_code = getattr(event, "error_code", None)
    error_message = getattr(event, "error_message", None)

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content else None
    has_call = has_response = has_text = False
    if parts:
        for p in parts:
            if getattr(p, "function_call", None):
                has_call = True
            if getattr(p, "function_response", None):
                has_response = True
            if getattr(p, "text", None):
                has_text = True

    actions = getattr(event, "actions", None)
    state_delta = getattr(actions, "state_delta", None) if actions else None
    has_state_write = bool(state_delta)

    if error_code:
        return {
            "agent": author,
            "kind": "error",
            "error_code": str(error_code),
            "error_message": str(error_message) if error_message else None,
        }

    if not (has_call or has_response or has_text or has_state_write):
        return {
            "agent": author,
            "kind": "empty_turn",
            "error_code": None,
            "error_message": (
                "Event had no function_call, function_response, text, or "
                "state_delta -- this agent's turn produced nothing observable."
            ),
        }

    return None


def summarize(diagnostics: list[dict]) -> dict:
    by_agent: dict[str, int] = {}
    for d in diagnostics:
        by_agent[d["agent"]] = by_agent.get(d["agent"], 0) + 1
    return {
        "total_flagged_events": len(diagnostics),
        "flagged_by_agent": by_agent,
    }
