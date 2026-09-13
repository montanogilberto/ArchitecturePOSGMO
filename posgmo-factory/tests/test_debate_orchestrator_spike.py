"""
Phase 0 spike (revised per user's counter-proposal): prove the SMALLEST
possible debate loop, with the orchestrator as a non-expert chairperson.

Scenario (exactly as specified):
    User Request
         |
    Architect A -> Proposal
         |
    Architect B (Critic) -> Challenge
         |
    Architect A -> Rebuttal          <-- SAME agent instance, invoked AGAIN,
         |                               reading the challenge that didn't
         |                               exist on its first invocation
    Orchestrator -> Decision         <-- pure function over the blackboard,
                                          the orchestrator invents no content
                                          of its own (chairperson, not expert)

Proves five things, each asserted below:
  1. An agent can be invoked imperatively (not just declared in a static list).
  2. Dynamically produced state/context passes agent -> agent.
  3. An agent can be invoked conditionally (critic only runs because a
     proposal exists; rebuttal only runs because a challenge exists).
  4. The SAME agent can be invoked twice in one round trip, seeing new
     context the second time that did not exist the first time.
  5. State accumulates across rounds — proposal/challenge/rebuttal all
     coexist on the blackboard afterward; nothing is overwritten.

No database, frontend, GitHub, or code generation. No LLM calls — every
"expert" is a deterministic BaseAgent, same pattern as this repo's existing
decision_gate_agent/loop_exit_agent, so this proves the ADK mechanics only.
"""
import asyncio
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part


def _append(state: dict, key: str, item: dict) -> list:
    """Blackboard convention: list-valued keys stored as JSON strings in
    session.state (matches decision_gate_agent's json.dumps(...) pattern) —
    read-append-write since ADK state_delta is a dict merge, not a list push."""
    current = json.loads(state.get(key) or "[]")
    current.append(item)
    return current


class ArchitectAgent(BaseAgent):
    """Stands in for the real architect_agent. Behaves differently depending
    on whether a challenge already exists on the blackboard — this is what
    makes the SECOND invocation a genuine rebuttal, not a repeated proposal."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        challenges = json.loads(state.get("challenges") or "[]")

        if not challenges:
            # First invocation: propose.
            proposals = _append(state, "proposals", {
                "round": 1, "agent": self.name, "type": "proposal",
                "claim": "Create a new Rewards module",
                "confidence": 0.6,
            })
            yield Event(author=self.name, actions=EventActions(
                state_delta={"proposals": json.dumps(proposals)}
            ))
        else:
            # Second invocation: this agent has NEW context (the challenge)
            # that did not exist when it first ran. Rebut/revise.
            last_challenge = challenges[-1]
            rebuttals = _append(state, "rebuttals", {
                "round": 3, "agent": self.name, "type": "rebuttal",
                "target": last_challenge["agent"],
                "claim": "Extend existing Rewards capability instead of creating a new module",
                "reasoning_summary": f"Accepted objection: {last_challenge['claim']}",
                "confidence": 0.9,
            })
            yield Event(author=self.name, actions=EventActions(
                state_delta={"rebuttals": json.dumps(rebuttals)}
            ))


class CriticAgent(BaseAgent):
    """Stands in for a Senior Engineer / Critic. Only makes sense to run
    AFTER a proposal exists — the orchestrator enforces that ordering, not
    this agent (it just reads whatever proposal is on the blackboard)."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        proposals = json.loads(state.get("proposals") or "[]")
        target_proposal = proposals[-1]

        challenges = _append(state, "challenges", {
            "round": 2, "agent": self.name, "type": "challenge",
            "target": target_proposal["agent"],
            "claim": "posReward* capabilities already exist — a new module duplicates them",
            "evidence": ["repo:smartloans_backend/modules/posReward*"],
            "confidence": 0.85,
        })
        yield Event(author=self.name, actions=EventActions(
            state_delta={"challenges": json.dumps(challenges)}
        ))


class DebateOrchestratorAgent(BaseAgent):
    """Chairperson, NOT an expert: it selects who speaks next and records the
    final decision as a pure function over the blackboard's contents. It
    never introduces its own claim, evidence, or opinion — every field in
    the decision event is copied or derived from what the experts said."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        architect, critic = self.sub_agents

        # Round 1 — PROPOSE
        async for event in architect.run_async(ctx):
            yield event

        # Round 2 — CHALLENGE (conditional: only because a proposal exists)
        if json.loads(ctx.session.state.get("proposals") or "[]"):
            async for event in critic.run_async(ctx):
                yield event

        # Round 3 — REBUT (SAME architect instance, invoked again, now sees
        # the challenge written in round 2 — conditional on it existing)
        if json.loads(ctx.session.state.get("challenges") or "[]"):
            async for event in architect.run_async(ctx):
                yield event

        # Round 4 — DECIDE: chairperson records, does not invent.
        rebuttals = json.loads(ctx.session.state.get("rebuttals") or "[]")
        proposals = json.loads(ctx.session.state.get("proposals") or "[]")
        if rebuttals:
            winning = rebuttals[-1]
            decision = {
                "round": 4, "agent": self.name, "type": "decision",
                "selected_claim": winning["claim"],
                "rationale": winning["reasoning_summary"],
                "confidence": winning["confidence"],
            }
            rejected = [{
                "claim": p["claim"], "reason": "superseded by rebuttal after challenge",
            } for p in proposals if p["claim"] != winning["claim"]]
            yield Event(author=self.name, actions=EventActions(state_delta={
                "decisions": json.dumps([decision]),
                "rejected_alternatives": json.dumps(rejected),
            }))
            yield Event(author=self.name, actions=EventActions(escalate=True))


async def _run_debate() -> dict:
    architect = ArchitectAgent(name="architect")
    critic = CriticAgent(name="critic")
    orchestrator = DebateOrchestratorAgent(
        name="debate_orchestrator", sub_agents=[architect, critic]
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=orchestrator, app_name="spike2", session_service=session_service)
    session = await session_service.create_session(app_name="spike2", user_id="u1", state={})

    trace = []
    async for event in runner.run_async(
        user_id="u1", session_id=session.id,
        new_message=Content(role="user", parts=[Part(text="create a new module for rewards")]),
    ):
        trace.append((event.author, list(event.actions.state_delta.keys()), event.actions.escalate))

    final = await session_service.get_session(app_name="spike2", user_id="u1", session_id=session.id)
    state = final.state

    return {"trace": trace, "state": state}


def test_same_agent_debate_loop_converges_to_extend_not_create():
    """Proves the five properties listed in the module docstring using
    ADK's real Runner/InvocationContext/SessionService — not a mock."""
    result = asyncio.run(_run_debate())
    trace = result["trace"]
    state = result["state"]

    print("Event trace (author, state keys written, escalate):")
    for row in trace:
        print(" ", row)

    proposals = json.loads(state["proposals"])
    challenges = json.loads(state["challenges"])
    rebuttals = json.loads(state["rebuttals"])
    decisions = json.loads(state["decisions"])
    rejected = json.loads(state["rejected_alternatives"])

    # 1+2: imperative invocation with dynamically produced context flowing through.
    assert len(proposals) == 1 and proposals[0]["agent"] == "architect"
    assert len(challenges) == 1 and challenges[0]["target"] == "architect"

    # 3: conditional invocation — critic ran because (and only because) a proposal existed.
    assert challenges[0]["claim"].startswith("posReward*")

    # 4: SAME agent invoked twice, second call sees context absent on the first call.
    assert len(rebuttals) == 1
    assert rebuttals[0]["agent"] == "architect"
    assert "posReward*" in rebuttals[0]["reasoning_summary"]

    # 5: nothing overwritten — proposal, challenge, AND rebuttal all still present together.
    assert proposals[0]["claim"] == "Create a new Rewards module"
    assert challenges[0]["claim"].startswith("posReward*")
    assert rebuttals[0]["claim"] == "Extend existing Rewards capability instead of creating a new module"

    # Chairperson recorded a decision derived from the rebuttal, not invented itself,
    # and kept the rejected alternative instead of deleting it.
    assert decisions[0]["selected_claim"] == rebuttals[0]["claim"]
    assert rejected[0]["claim"] == "Create a new Rewards module"

    print("\nFinal decision:", decisions[0]["selected_claim"])
    print("Rejected alternative kept:", rejected[0])
