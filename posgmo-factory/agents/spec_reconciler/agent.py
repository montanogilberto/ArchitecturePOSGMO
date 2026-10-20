"""Spec Reconciler Agent — pure Python BaseAgent, zero LLM calls.

Runs after decision_gate_agent and before generation_stage. See rules.py.
"""
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.spec_reconciler.rules import normalize_frontend_paths, reconcile_specification


class _SpecReconcilerAgent(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = dict(ctx.session.state)
        # 1. Frontend paths → MVVM layout (always; the architect's JSON is never
        #    validated by SpecificationJSON in the pipeline, so enforce here).
        paths_spec, paths_record = normalize_frontend_paths(state)
        if paths_spec is not None:
            state["specification"] = json.dumps(paths_spec)
        # 2. Existing live table outranks the spec.
        new_spec, record = reconcile_specification(state)
        record["frontend_paths"] = paths_record
        print(f"[spec_reconciler] {record}", flush=True)
        delta = {"spec_reconciliation": json.dumps(record)}
        final = new_spec if new_spec is not None else paths_spec
        if final is not None:
            delta["specification"] = json.dumps(final)
        yield Event(author=self.name, actions=EventActions(state_delta=delta))


spec_reconciler_agent = _SpecReconcilerAgent(
    name="spec_reconciler_agent",
    description=(
        "Deterministic, zero-LLM: when the module's table already exists live, "
        "enforces the MVVM frontend file layout, and corrects specification's "
        "PK/columns to the live table before construction."
    ),
)
