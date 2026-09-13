"""Standalone entrypoint for the Phase 2 debate spike. NOT wired into
agents/agent.py or orchestrator.py — run manually via ../run_debate_spike.py."""
from __future__ import annotations

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from debate_v2.context import ContextAgent
from debate_v2.experts import build_architect_agent, build_challenger_agent, build_product_owner_agent
from debate_v2.intake import build_intake_agent
from debate_v2.orchestrator import DebateOrchestratorAgent
from debate_v2.panel import select_challengers


async def run_debate(request: str) -> dict:
    # Panel selection (Phase 4, doc §6) runs on the request text alone —
    # ADK's sub_agents must be fixed before the orchestrator starts, so this
    # happens before ANALYZE gathers verified facts, not after.
    challenger_roles = select_challengers(request)
    orchestrator = DebateOrchestratorAgent(
        name="debate_orchestrator",
        sub_agents=[
            ContextAgent(name="context_agent"),
            build_intake_agent(),
            build_product_owner_agent(),
            build_architect_agent(),
            *[build_challenger_agent(role) for role in challenger_roles],
        ],
    )
    session_service = InMemorySessionService()
    runner = Runner(agent=orchestrator, app_name="debate_v2", session_service=session_service)
    session = await session_service.create_session(
        app_name="debate_v2", user_id="spike", state={"request": request},
    )
    async for _event in runner.run_async(
        user_id="spike", session_id=session.id,
        new_message=Content(role="user", parts=[Part(text=request)]),
    ):
        pass
    final = await session_service.get_session(app_name="debate_v2", user_id="spike", session_id=session.id)
    return dict(final.state)
