"""
POS GMO AI Factory — Partial Re-run

Runs the pipeline starting from a specific agent, reusing session state
from a previous full run (saved via --state flag or stdin).

Usage:
    # Re-run from database agent onward (skips PRD parse, schema analysis, architect, gate)
    python run_partial.py --from database --state last_state.json

    # Re-run from backend agent onward (database already correct)
    python run_partial.py --from backend --state last_state.json

    # Re-run from reviewer onward (regenerate review + PR only)
    python run_partial.py --from reviewer --state last_state.json

Available --from values (in pipeline order):
    prd_parser | schema_analyst | architect | gate | database | backend |
    design | frontend | reviewer | pr

How to get the state file:
    python orchestrator.py tests/prd_clientFaceRecognition.json > last_state.json
    # OR save the "FACTORY RESULT" JSON block printed at the end of a run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

load_dotenv()

# ---------------------------------------------------------------------------
# Agent registry — ordered as in agent.py
# ---------------------------------------------------------------------------

def _build_agent_map():
    from google.adk.agents import ParallelAgent
    from agents.prd_parser_agent import prd_parser_agent
    from agents.schema_analyst_agent import schema_analyst_agent
    from agents.architect_agent import architect_agent
    from agents.decision_gate_agent import decision_gate_agent
    from agents.database_agent import database_agent
    from agents.backend_agent import backend_agent
    from agents.design_consistency_agent import design_consistency_agent
    from agents.frontend_agent import frontend_agent
    from agents.reviewer_agent import reviewer_agent
    from agents.pr_agent import pr_agent

    generation_stage = ParallelAgent(
        name="generation_stage",
        description="Concurrent SQL, Python, and design extraction",
        sub_agents=[database_agent, backend_agent, design_consistency_agent],
    )

    return {
        "prd_parser":     prd_parser_agent,
        "schema_analyst": schema_analyst_agent,
        "architect":      architect_agent,
        "gate":           decision_gate_agent,
        "generation":     generation_stage,   # database + backend + design in parallel
        "frontend":       frontend_agent,
        "reviewer":       reviewer_agent,
        "pr":             pr_agent,
    }

_AGENT_ORDER = [
    "prd_parser", "schema_analyst", "architect", "gate",
    "generation", "frontend", "reviewer", "pr",
]

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_partial(from_agent: str, seed_state: dict, user_id: str = "factory") -> dict:
    agent_map = _build_agent_map()

    if from_agent not in _AGENT_ORDER:
        raise ValueError(f"Unknown agent '{from_agent}'. Choose from: {_AGENT_ORDER}")

    start_idx = _AGENT_ORDER.index(from_agent)
    agents_to_run = [agent_map[k] for k in _AGENT_ORDER[start_idx:]]

    partial_pipeline = SequentialAgent(
        name="posgmo_factory_partial",
        description="Partial POS GMO pipeline re-run",
        sub_agents=agents_to_run,
    )

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="posgmo_factory_partial",
        user_id=user_id,
        state=seed_state,
    )

    runner = Runner(
        agent=partial_pipeline,
        app_name="posgmo_factory_partial",
        session_service=session_service,
    )

    # Send an empty trigger message — session state already has everything the agents need
    trigger = Content(role="user", parts=[Part(text="run")])

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=trigger,
    ):
        if event.is_final_response() and event.content:
            pass

    updated = await session_service.get_session(
        app_name="posgmo_factory_partial",
        user_id=user_id,
        session_id=session.id,
    )
    return dict(updated.state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Re-run pipeline from a specific agent")
    parser.add_argument(
        "--from", dest="from_agent", required=True,
        choices=_AGENT_ORDER,
        help="Agent to start from (all subsequent agents also run)",
    )
    parser.add_argument(
        "--state", required=True,
        help="Path to JSON file containing the saved session state from a previous run",
    )
    parser.add_argument(
        "--out", default=None,
        help="Optional path to write the resulting state JSON (default: stdout)",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"ERROR: state file not found: {state_path}", file=sys.stderr)
        sys.exit(1)

    seed_state = json.loads(state_path.read_text(encoding="utf-8"))

    print(f"Re-running from: {args.from_agent}", file=sys.stderr)
    print(f"Agents in run:   {_AGENT_ORDER[_AGENT_ORDER.index(args.from_agent):]}", file=sys.stderr)

    result = asyncio.run(run_partial(args.from_agent, seed_state))

    output = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Result saved to {args.out}", file=sys.stderr)
    else:
        print("\n=== PARTIAL RUN RESULT ===")
        print(output)


if __name__ == "__main__":
    main()
