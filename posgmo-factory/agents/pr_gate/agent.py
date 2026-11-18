"""PR Gate Agent definition — pure Python BaseAgent wrapping pr_agent."""
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.pr_gate.rules import compute_pr_gate


class _PrGateAgent(BaseAgent):
    """Runs compute_pr_gate() directly -- zero LLM calls. Only invokes its
    wrapped pr_agent sub-agent when the gate clears; otherwise writes
    pr_result itself and pr_agent never runs at all, so it never gets a
    chance to call a GitHub tool on a run that shouldn't be pushed."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        may_proceed, blocked_result = compute_pr_gate(dict(ctx.session.state))

        if may_proceed:
            async for event in self.sub_agents[0].run_async(ctx):
                yield event
            return

        print(f"[pr_gate] blocked deterministically: {blocked_result.get('reason')}", flush=True)
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"pr_result": json.dumps(blocked_result)}),
        )


def make_pr_gate_agent(pr_agent) -> _PrGateAgent:
    return _PrGateAgent(
        name="pr_stage",
        description="Deterministic pass/fail gate in front of pr_agent",
        sub_agents=[pr_agent],
    )
