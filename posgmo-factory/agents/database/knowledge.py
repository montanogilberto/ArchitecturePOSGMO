"""
Pre-loaded knowledge for database_llm_agent.

The LLM fallback used to fetch these via MCP tool calls (get_generation_rules,
get_sp_patterns, get_table_columns, get_relationships_for_table,
search_factory_experience). Those calls were the remaining source of
MALFORMED_FUNCTION_CALL after execution moved out (Milestone 7), and every
one of them has fixed or spec-derived arguments -- so they are called here
as plain Python and inlined into the instruction. Same authority order as
before: MCP facts first, factory experience labeled as historical evidence.
"""
from __future__ import annotations

import json
from typing import Callable

from google.adk.agents.readonly_context import ReadonlyContext

from agents.state_injection import with_state


def _load(spec_raw) -> dict:
    from agents.database.sql_templates import _safe_load
    return _safe_load(spec_raw)


def build_database_knowledge(spec_raw) -> dict:
    """Best-effort: a failing source is reported, never raised -- missing
    knowledge must not take the stage down."""
    from mcp_server import server as mcp

    table = _load(spec_raw).get("db", {}).get("table_name", "")
    sources = {
        "generation_rules.database": lambda: mcp.get_generation_rules().get("database"),
        "sp_patterns": mcp.get_sp_patterns,
        "reference_table.cashRegisterSessions": lambda: mcp.get_table_columns("cashRegisterSessions"),
        "relationships_for_table": lambda: mcp.get_relationships_for_table(table) if table else {},
        "factory_experience (HISTORICAL EVIDENCE, NOT AUTHORITATIVE)": lambda: mcp.search_factory_experience(
            "CREATE TABLE followed by CREATE OR ALTER PROC stored procedures", 3
        ),
    }
    out = {}
    for key, fn in sources.items():
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001 -- best-effort by design
            out[key] = {"unavailable": str(e)[:200]}
    return out


def with_database_knowledge(base_instruction: str, keys: list[str]) -> Callable[[ReadonlyContext], str]:
    # Static knowledge before per-run state, so Gemini's implicit prefix
    # cache can reuse it -- see agents/preloaded_knowledge.py.
    state_provider = with_state("", keys)

    def _provider(ctx: ReadonlyContext) -> str:
        knowledge = build_database_knowledge(ctx.state.get("specification", ""))
        return (
            base_instruction
            + "\n\n## Pre-loaded knowledge (MCP authoritative facts + historical evidence)\n```json\n"
            + json.dumps(knowledge, indent=2, default=str)[:30000]
            + "\n```"
            + state_provider(ctx)
        )

    return _provider
