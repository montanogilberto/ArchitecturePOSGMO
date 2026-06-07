"""
POS GMO AI Factory — Root Orchestrator

Pipeline:
    PRDInput JSON
        → ArchitectAgent        (spec)
        → ParallelAgent         (database + backend in parallel)
        → FrontendAgent         (depends on spec + backend)
        → ReviewerAgent         (validates all artifacts)
        → PRAgent               (opens GitHub PRs if review passed)

Usage:
    from orchestrator import run_factory
    import asyncio, json

    prd = json.load(open("examples/prd_supplier.json"))
    result = asyncio.run(run_factory(prd))
    print(result)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import ParallelAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agents.architect_agent  import architect_agent
from agents.backend_agent    import backend_agent
from agents.database_agent   import database_agent
from agents.frontend_agent   import frontend_agent
from agents.pr_agent         import pr_agent
from agents.reviewer_agent   import reviewer_agent
from prd_schema import PRDInput

load_dotenv()

# ---------------------------------------------------------------------------
# Pipeline assembly
# ---------------------------------------------------------------------------

_parallel_codegen = ParallelAgent(
    name="parallel_codegen",
    description="Runs Database Agent and Backend Agent concurrently.",
    sub_agents=[database_agent, backend_agent],
)

factory_pipeline = SequentialAgent(
    name="pos_gmo_factory",
    description="Full POS GMO module generation pipeline.",
    sub_agents=[
        architect_agent,
        _parallel_codegen,
        frontend_agent,
        reviewer_agent,
        pr_agent,
    ],
)

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_session_service = InMemorySessionService()

_runner = Runner(
    agent=factory_pipeline,
    app_name="posgmo_factory",
    session_service=_session_service,
)


async def run_factory(prd_dict: dict, user_id: str = "factory") -> dict:
    """
    Runs the full generation pipeline for a PRD.

    Args:
        prd_dict: Raw dict matching the PRDInput schema.
        user_id:  Logical user identifier for session isolation.

    Returns:
        Dict with keys: specification, database_artifacts, backend_artifacts,
        frontend_artifacts, review_result, pr_result.

    Raises:
        pydantic.ValidationError: If prd_dict fails PRDInput validation.
    """
    # Gate: validate PRD before touching any agent
    prd = PRDInput.model_validate(prd_dict)

    session = await _session_service.create_session(
        app_name="posgmo_factory",
        user_id=user_id,
    )

    message = Content(
        role="user",
        parts=[Part(text=json.dumps(prd.model_dump()))],
    )

    final_state: dict = {}
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            pass  # final agent text (pr_agent output)

    # Collect all output_key values from session state
    updated = await _session_service.get_session(
        app_name="posgmo_factory",
        user_id=user_id,
        session_id=session.id,
    )
    final_state = dict(updated.state)
    return final_state


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <path/to/prd.json>")
        sys.exit(1)

    prd_path = Path(sys.argv[1])
    prd_data = json.loads(prd_path.read_text(encoding="utf-8"))

    result = asyncio.run(run_factory(prd_data))

    print("\n=== FACTORY RESULT ===")
    print(json.dumps(result, indent=2, default=str))
