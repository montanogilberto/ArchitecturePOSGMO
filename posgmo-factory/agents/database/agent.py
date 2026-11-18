"""Database Agent definition.

`database_agent` (the name the pipeline, diagnostics and experience logs all
use) is now a thin deterministic stage, not an LLM:

1. CRUD-shaped modules (the vast majority) -> agents/database/sql_templates.py
   renders the SQL from specification + gate_result. Zero LLM calls, so zero
   MALFORMED_FUNCTION_CALL exposure.
2. Everything else (ACTION_ROUTER, BUSINESS_LOGIC, TIER_3, an unrecognized
   gate constraint) -> `database_llm_agent`, which has NO tools at all (its
   knowledge is pre-loaded into the instruction, see knowledge.py) and is
   retried up to MAX_LLM_ATTEMPTS times until it produces parseable output.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from google.adk.agents import Agent, BaseAgent
from agents.models import CODE_MODEL
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.database.knowledge import with_database_knowledge
from agents.database.prompt import INSTRUCTION
from agents.database.live_schema import live_table_columns
from agents.database.sql_templates import generate_crud_sql, fallback_reason, _safe_load
from agents.retry import run_with_retries

MAX_LLM_ATTEMPTS = 3

database_llm_agent = Agent(
    name="database_llm_agent",
    description=(
        "LLM fallback for database SQL the deterministic templates can't render "
        "(ACTION_ROUTER, BUSINESS_LOGIC, TIER_3, or an unrecognized gate constraint). "
        "Writes SQL as text; has no tools."
    ),
    model=CODE_MODEL,
    # Targeted context: exactly gate_result + specification (+ pre-fetched
    # knowledge), include_contents='none' -- Experiments 1-4 showed the full
    # accumulated conversation caused repeated MALFORMED_FUNCTION_CALL here.
    # database_repair_feedback: the SQL Server's own error for the previous
    # attempt, when the repair loop in _DatabaseStageAgent rejected it.
    instruction=with_database_knowledge(INSTRUCTION, ["gate_result", "specification", "spec_reconciliation", "database_repair_feedback"]),
    include_contents="none",
    # No tools at all. Execution moved to database_executor (Experiment 1);
    # the MCP knowledge calls were the remaining MALFORMED_FUNCTION_CALL
    # surface (Milestone 7), so their results are now inlined instead.
    tools=[],
    output_key="database_artifacts",
)


def llm_output_is_usable(raw) -> bool:
    """True when database_llm_agent's output is a JSON object carrying at
    least one SQL artifact (or the explicit blocked / no-SQL markers)."""
    data = _safe_load(raw)
    if not data:
        return False
    if data.get("status") == "blocked" or ("sql" in data and data["sql"] is None):
        return True
    sql_keys = ("create_table", "sp_upsert", "sp_all", "sp_one",
                "sp_action_router", "sp_data", "sp_persist")
    return any(isinstance(data.get(k), str) and data[k].strip() for k in sql_keys)


def sql_errors_on_server(raw) -> list[str]:
    """Executes CRUD-shaped SQL on the real server inside a rolled-back
    transaction; returns the server's error messages (empty = valid, or a
    shape the executor doesn't run). Never persists anything."""
    from agents.database.rules import execute_sql_on_server

    data = _safe_load(raw)
    keys = ("create_table", "sp_upsert", "sp_all", "sp_one")
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
        return []
    try:
        result = execute_sql_on_server(*(data[k] for k in keys), validate_only=True)
    except Exception as e:  # noqa: BLE001 -- no server = no repair signal, not a failure
        print(f"[database_agent] repair check unavailable: {str(e)[:120]}", flush=True)
        return []
    return [f"{d.get('batch_preview', '')[:60]!r}: {d.get('message', '')[:300]}"
            for d in result.get("details", []) if d.get("status") in ("error", "connection_error")]


class _DatabaseStageAgent(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        spec, gate = state.get("specification", ""), state.get("gate_result", "")
        started = time.monotonic()

        table = _safe_load(spec).get("db", {}).get("table_name", "")
        live_columns = live_table_columns(table) if _safe_load(gate).get("status") != "BLOCKED" else None
        artifacts = generate_crud_sql(spec, gate, live_columns)
        if artifacts is not None:
            artifacts["generation"] = {
                "generator": "template", "llm_attempts": 0,
                "existing_table": bool(live_columns),
                "elapsed_s": round(time.monotonic() - started, 3),
            }
            label = "blocked by gate" if artifacts.get("status") == "blocked" else "template"
            print(f"[database_agent] generator={label} llm_attempts=0", flush=True)
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={"database_artifacts": json.dumps(artifacts)}),
            )
            return

        reason = fallback_reason(spec, gate, live_columns)
        failures: list[str] = []
        output, attempt = None, 0
        best_output = None  # last usable SQL: a failed repair must never replace it with nothing
        while attempt < MAX_LLM_ATTEMPTS:
            report: dict = {}
            async for event in run_with_retries(
                self.sub_agents[0], ctx, "database_artifacts", llm_output_is_usable,
                MAX_LLM_ATTEMPTS - attempt, report,
            ):
                yield event
            output = report["output"]
            attempt += report["attempts"]
            failures += report["failures"]
            if not report["succeeded"]:
                # Step 1 evidence (leadCapture): repair attempts 2-3 came back
                # empty and the stage shipped nothing -> database 0.
                output = best_output if best_output is not None else output
                break
            best_output = output
            # Repair loop: prove the SQL on the real server (always rolled
            # back), and feed any server error back for the next attempt.
            server_errors = await asyncio.to_thread(sql_errors_on_server, output)
            if not server_errors:
                break
            failures.append(f"attempt {attempt}: server rejected SQL: {server_errors[0][:160]}")
            print(f"[database_agent] LLM SQL rejected by server on attempt {attempt} -- repairing", flush=True)
            feedback = json.dumps({"previous_attempt_errors": server_errors})
            ctx.session.state["database_repair_feedback"] = feedback  # read by the next attempt's instruction
            yield Event(author=self.name, actions=EventActions(state_delta={"database_repair_feedback": feedback}))

        artifacts = _safe_load(output)
        # Deterministic, independent of what the LLM wrote: an existing live
        # table that contradicts the gate's decisions needs a human decision
        # (Step 1 evidence: leadCaptures has a nullable companyId although
        # ADR-001 made the module TENANT_INDEPENDENT; the LLM surfaced it
        # inconsistently across runs).
        if live_columns:
            from agents.database.sql_templates import reconcile_with_live
            conflict = reconcile_with_live(_safe_load(spec), _safe_load(gate), live_columns)[2]
            if conflict:
                artifacts["live_conflict"] = conflict
        artifacts["generation"] = {
            "generator": "llm",
            "fallback_reason": reason,
            "llm_attempts": attempt,
            "succeeded": llm_output_is_usable(output),
            "server_validated": not failures or not failures[-1].startswith(f"attempt {attempt}: server rejected"),
            "failures": failures,
            "elapsed_s": round(time.monotonic() - started, 3),
        }
        print(f"[database_agent] generator=llm attempts={attempt} usable={artifacts['generation']['succeeded']} "
              f"reason={reason}", flush=True)
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"database_artifacts": json.dumps(artifacts)}),
        )


database_agent = _DatabaseStageAgent(
    name="database_agent",
    description=(
        "Produces CREATE TABLE + stored procedures for this module as text: "
        "deterministic templates for CRUD shapes, tool-less LLM with bounded "
        "retries otherwise. Does not execute them -- see database_executor_agent."
    ),
    sub_agents=[database_llm_agent],
)
