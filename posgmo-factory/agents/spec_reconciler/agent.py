"""Spec Reconciler Agent — pure Python BaseAgent, zero LLM calls.

Runs after decision_gate_agent and before generation_stage. See rules.py.
"""
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.spec_reconciler.rules import reconcile_specification


class _SpecReconcilerAgent(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        new_spec, record = reconcile_specification(dict(ctx.session.state))
        print(f"[spec_reconciler] {record}", flush=True)
        delta = {"spec_reconciliation": json.dumps(record)}
        if new_spec is not None:
            delta["specification"] = json.dumps(new_spec)
        yield Event(author=self.name, actions=EventActions(state_delta=delta))


spec_reconciler_agent = _SpecReconcilerAgent(
    name="spec_reconciler_agent",
    description=(
        "Deterministic, zero-LLM: when the module's table already exists live, "
        "corrects specification's PK/columns to the live table before construction."
    ),
)
