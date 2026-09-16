"""
Targeted state injection for LLM agent instructions.

Every generation-stage agent's own prompt already declares exactly which
session-state keys it needs (e.g. database/prompt.py: "Read the
SpecificationJSON from session state key 'specification'"). But with the
default `instruction=lambda _ctx: INSTRUCTION` pattern used across this
codebase, that key's actual JSON value never reaches the model directly --
the model only ever "sees" it by having read a PRIOR AGENT'S text reply
earlier in the accumulated conversation (e.g. architect_agent's own output
IS the specification JSON, visible as a past turn). That's why naively
setting `include_contents='none'` on database_agent/backend_agent/
frontend_agent (as was done for reviewer_agent/loop_exit_agent/
review_fixer_agent/fixer_agent -- their tools take zero arguments and read
purely from tool_context.state, so this doesn't apply to them) would make
them blind rather than focused: it would cut off the exact data their own
prompts say they require.

This module is the alternative: an InstructionProvider (a callable ADK
accepts anywhere a static instruction string works) that reads specific
named state keys directly via ReadonlyContext.state and inlines their
*current* value into the instruction text. Combined with
include_contents='none', an agent then gets exactly what its own prompt
already claims to need -- no more, no less -- instead of either the full
accumulated conversation or nothing.

This is context SELECTION, not context elimination.
"""
from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.readonly_context import ReadonlyContext


def _pretty(raw) -> str:
    if not isinstance(raw, str):
        return json.dumps(raw, indent=2, default=str)
    raw = raw.strip()
    if not raw:
        return "(not yet available)"
    body = raw
    if body.startswith("```"):
        body = "\n".join(
            line for line in body.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        return json.dumps(json.loads(body), indent=2)
    except (json.JSONDecodeError, TypeError):
        return raw


def with_state(base_instruction: str, keys: list[str]) -> Callable[[ReadonlyContext], str]:
    """Returns an InstructionProvider: base_instruction followed by one
    clearly-labeled, pretty-printed block per key in `keys`, read fresh from
    session state at call time (not baked in at agent-construction time)."""

    def _provider(ctx: ReadonlyContext) -> str:
        blocks = [base_instruction]
        for key in keys:
            value = ctx.state.get(key, "")
            blocks.append(f"\n\n## Current `{key}` (from session state)\n```json\n{_pretty(value)}\n```")
        return "".join(blocks)

    return _provider
