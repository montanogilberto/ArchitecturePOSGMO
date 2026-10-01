"""
Run a deterministic tool function as a pipeline stage — zero LLM calls.

fixer / reviewer / loop_exit / review_fixer were LLM Agents whose only job
was to call one zero-argument Python tool. Step 1 evidence (29 real runs):
those turns came back empty or MALFORMED often enough that the tool silently
never ran -- 11 runs applied no deterministic fixes at all, and one run
(factoryRunUsage-20260923-092926-3) finished with NO review verdict. An LLM
adds nothing to "call this function"; this stage calls it directly, the same
pattern decision_gate_agent and database_executor_agent already use.
"""
from __future__ import annotations

from typing import AsyncGenerator, Callable

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions


class _ToolContextShim:
    """The subset of ToolContext the rules modules use: `.state` (a dict) and
    `.actions.escalate` (loop_exit)."""

    def __init__(self, state: dict):
        self.state = state
        self.actions = EventActions()


class DeterministicToolStage(BaseAgent):
    fn: Callable

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        before = dict(ctx.session.state)
        shim = _ToolContextShim(dict(before))
        try:
            self.fn(shim)
        except Exception as e:  # noqa: BLE001 -- a deterministic stage must never take the run down
            # Recorded, not raised: the run continues so the reviewer still
            # issues a verdict on whatever the artifacts are.
            import traceback
            shim.state[f"{self.name}_error"] = f"{type(e).__name__}: {e} | {traceback.format_exc()[-800:]}"
            print(f"[{self.name}] ERROR (recorded, run continues): {type(e).__name__}: {e}", flush=True)
        delta = {k: v for k, v in shim.state.items() if before.get(k) != v}
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=delta, escalate=shim.actions.escalate or None),
        )
