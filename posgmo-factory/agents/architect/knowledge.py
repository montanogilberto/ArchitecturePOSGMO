"""
Pre-loaded knowledge for architect_agent.

architect_agent runs at temperature 0, so when one of its MCP tool calls came
back MALFORMED_FUNCTION_CALL, retrying with the same context reproduced the
same failure (Step 1 evidence: 3/3 attempts failed in each affected run,
decision_gate then BLOCKED the run). Every one of its six knowledge calls has
fixed or state-derived arguments, so they are called here as plain Python and
inlined -- same sources, same order, same authority labels; no function-call
surface left to malform.
"""
from __future__ import annotations

import json

from google.adk.agents.readonly_context import ReadonlyContext

from agents.retry import retry_notice


def build_architect_knowledge(module: str, description: str) -> dict:
    from mcp_server import server as mcp

    sources = {
        "1. generation_rules": mcp.get_generation_rules,
        "2. frontend_patterns": mcp.get_frontend_patterns,
        "3. backend_patterns": mcp.get_backend_patterns,
        "4. sp_patterns": mcp.get_sp_patterns,
        f"5. decisions_for_module({module})": lambda: mcp.get_decisions_for_module(module),
        "6. factory_experience (HISTORICAL EVIDENCE, NOT AUTHORITATIVE)":
            lambda: mcp.search_factory_experience(description or module, 3),
    }
    out = {}
    for key, fn in sources.items():
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001 -- a missing source must not stop the run
            out[key] = {"unavailable": str(e)[:200]}
    return out


def with_architect_knowledge(base_instruction: str):
    def _provider(ctx: ReadonlyContext) -> str:
        knowledge = build_architect_knowledge(
            str(ctx.state.get("module", "")), str(ctx.state.get("description", ""))
        )
        return (
            base_instruction
            + "\n\n## Pre-loaded knowledge (results of the knowledge calls above)\n```json\n"
            + json.dumps(knowledge, indent=1, default=str)
            + "\n```"
            + retry_notice(ctx.state, "architect_agent")
        )

    return _provider
