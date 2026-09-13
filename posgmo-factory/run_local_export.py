"""
POS GMO AI Factory — Local export run (no GitHub, no branches, no PRs).

Runs the exact same root_agent pipeline as orchestrator.py, but with
pr_agent removed from the sequence before execution. Dumps
database_artifacts / backend_artifacts / frontend_artifacts / review_result
to a JSON file so the files can be applied manually to the two repos and
the user opens the PRs themselves.

Usage:
    python run_local_export.py tests/prd_notificationDispatch.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from orchestrator import _build_session_state
from prd_schema import PRDInput
from agents import root_agent
from agents.agent import generation_stage
from agents.pr import pr_agent
from agents.design_consistency import design_consistency_agent

# Run the real pipeline, minus the PR stage — no GitHub calls of any kind.
assert root_agent.sub_agents[-1] is pr_agent, "pr_agent is no longer last in root_agent.sub_agents"
root_agent.sub_agents = root_agent.sub_agents[:-1]

# design_consistency_agent's only job is fetching reference pages from the
# frontend GitHub repo (read-only) to learn styling patterns. The configured
# GITHUB_TOKEN is invalid (confirmed: GET /user -> 401 Bad credentials), so
# this call fails the same way a push would. Drop it for local-only runs —
# the PRD's frontend.components hints already specify the UI pattern.
generation_stage.sub_agents = [
    a for a in generation_stage.sub_agents if a is not design_consistency_agent
]

_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name="posgmo_factory_local", session_service=_session_service)


async def run_local(prd_dict: dict, user_id: str = "factory") -> dict:
    prd = PRDInput.model_validate(prd_dict)
    session = await _session_service.create_session(
        app_name="posgmo_factory_local",
        user_id=user_id,
        state=_build_session_state(prd),
    )
    message = Content(role="user", parts=[Part(text=json.dumps(prd.model_dump()))])

    async for event in _runner.run_async(user_id=user_id, session_id=session.id, new_message=message):
        pass

    updated = await _session_service.get_session(
        app_name="posgmo_factory_local", user_id=user_id, session_id=session.id
    )
    return dict(updated.state)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_local_export.py <path/to/prd.json>")
        sys.exit(1)

    prd_path = Path(sys.argv[1])
    prd_data = json.loads(prd_path.read_text(encoding="utf-8"))
    module = prd_data["module"]

    state = asyncio.run(run_local(prd_data))

    out_dir = Path(__file__).parent / "local_export" / module
    out_dir.mkdir(parents=True, exist_ok=True)

    keep_keys = ["database_artifacts", "backend_artifacts", "frontend_artifacts", "design_brief", "review_result"]
    dump = {k: state.get(k, "{}") for k in keep_keys}
    (out_dir / "artifacts.json").write_text(json.dumps(dump, indent=2), encoding="utf-8")

    print(f"\n=== LOCAL EXPORT COMPLETE for '{module}' ===")
    print(f"Artifacts written to: {out_dir / 'artifacts.json'}")
    print("No GitHub call was made. No branch was created. Nothing was pushed.")
