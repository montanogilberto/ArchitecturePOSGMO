"""Decision Gate Agent definition — pure Python BaseAgent."""
from agents.decision_gate.rules import compute_gate_result
import json
from typing import AsyncGenerator
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event


class _DecisionGateAgent(BaseAgent):
    """
    Runs compute_gate_result() directly — zero LLM calls.
    Writes gate_result into session state via Event state_delta.
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state_dict = dict(ctx.session.state)
        gate_result = compute_gate_result(state_dict)
        gate_json = json.dumps(gate_result)
        print(f"[gate] result status={gate_result['status']} tier={gate_result.get('tier')}", flush=True)

        yield Event(
            author=self.name,
            state={"gate_result": gate_json},
        )


decision_gate_agent = _DecisionGateAgent(
    name="decision_gate_agent",
    description=(
        "Deterministic quality gate: classifies module tier, detects backend pattern, "
        "emits mandatory constraints. Pure Python — no LLM classification."
    ),
)