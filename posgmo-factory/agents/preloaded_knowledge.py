"""
Pre-loaded MCP knowledge for construction agents.

Step 1 evidence: every LLM agent that fetched knowledge through MCP tool calls
hit MALFORMED_FUNCTION_CALL in real runs (architect, backend, prd_enricher,
review_fixer), and a retry with the same context often reproduced it
(backend_agent 3/3 in one run). The knowledge calls these agents are told to
make take no arguments, so they are made here as plain Python and inlined
into the instruction -- same sources, same order, no function-call surface.
"""
from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from agents.retry import retry_notice
from agents.state_injection import with_state

PRELOADED_HEADER = (
    "## Knowledge sources (PRE-LOADED — you have NO tools)\n"
    "The results of the knowledge calls below are already inlined at the END of this\n"
    "instruction under \"Pre-loaded knowledge\", keyed by the same numbers. Do not attempt\n"
    "any function call — none exist. The guidance for each source still applies:\n"
)


def load_sources(names: list[str]) -> dict:
    from mcp_server import server as mcp

    out = {}
    for i, name in enumerate(names, 1):
        try:
            out[f"{i}. {name}"] = getattr(mcp, name)()
        except Exception as e:  # noqa: BLE001 -- a missing source must not stop the run
            out[f"{i}. {name}"] = {"unavailable": str(e)[:200]}
    return out


def with_preloaded_knowledge(base_instruction: str, state_keys: list[str],
                             sources: list[str], agent_name: str = "") -> Callable[[ReadonlyContext], str]:
    # Order is a cost decision: the static part (instruction + knowledge, the
    # bulk of the tokens and identical on every run) comes FIRST, per-run
    # state LAST, so Gemini's implicit prefix cache bills the static part at
    # 10% of the input price. State in the middle broke the shared prefix.
    state_provider = with_state("", state_keys)

    def _provider(ctx: ReadonlyContext) -> str:
        return (
            base_instruction
            + "\n\n## Pre-loaded knowledge (results of the knowledge calls above)\n```json\n"
            + json.dumps(load_sources(sources), indent=1, default=str)
            + "\n```"
            + state_provider(ctx)
            + retry_notice(ctx.state, agent_name)
        )

    return _provider
