"""Database Executor Agent definition — pure Python BaseAgent, zero LLM calls.

Runs immediately after database_agent (as part of generation_stage) to
execute the SQL database_agent wrote as plain text. See rules.py for why
this is a deliberately separate, LLM-free step rather than a tool
database_agent calls itself, the same architectural pattern as
decision_gate_agent (agents/decision_gate/agent.py).
"""
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.database_executor.rules import merge_execution_result


class _DatabaseExecutorAgent(BaseAgent):
    """Runs merge_execution_result() directly — zero LLM calls. Writes the
    updated database_artifacts (with "execution" added) back into session
    state via Event state_delta, same mechanism as decision_gate_agent."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state_dict = dict(ctx.session.state)
        updated_artifacts = merge_execution_result(state_dict)

        execution = updated_artifacts.get("execution") if isinstance(updated_artifacts, dict) else None
        if execution is not None:
            print(
                f"[database_executor] success={execution.get('success')} "
                f"statements={len(execution.get('details', []))}",
                flush=True,
            )
        else:
            print(
                "[database_executor] nothing to execute this run "
                "(database_artifacts empty, or a non-CRUD SP shape execute_sql_on_server doesn't handle)",
                flush=True,
            )

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"database_artifacts": json.dumps(updated_artifacts)}),
        )


database_executor_agent = _DatabaseExecutorAgent(
    name="database_executor_agent",
    description=(
        "Deterministic, zero-LLM step: executes the SQL database_agent just wrote "
        "(as plain text) against SQL Server, and records the result in "
        "database_artifacts.execution. No model involved -- see rules.py for why."
    ),
)
