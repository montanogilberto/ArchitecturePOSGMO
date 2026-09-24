"""
POS GMO AI Factory — Local export run (no GitHub, no branches, no PRs).

Runs the exact same root_agent pipeline as orchestrator.py, but with
pr_agent removed from the sequence before execution. Dumps
database_artifacts / backend_artifacts / frontend_artifacts / review_result
to a JSON file so the files can be applied manually to the two repos and
the user opens the PRs themselves.

Usage:
    python run_local_export.py tests/prd_notificationDispatch.json
    python run_local_export.py tests/prd_pricingPlan.json --target commercial
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from orchestrator import _build_session_state, _REPO_ENV_VARS
from prd_schema import PRDInput
from agents import root_agent
from agents.agent import generation_stage
from agents.pr import pr_agent
from agents.design_consistency import design_consistency_agent
from artifact_contracts import check_backend_endpoint_completeness

def _strip_pr_and_design_consistency() -> None:
    """Removes pr_agent (no GitHub calls of any kind) and
    design_consistency_agent (GITHUB_TOKEN is invalid, confirmed: GET /user
    -> 401 Bad credentials, so this read-only call fails the same way a
    push would) from the SHARED root_agent/generation_stage singletons
    (agents/__init__.py) -- the same objects orchestrator.py's run_factory()
    uses for real runs. Idempotent and called explicitly from run_local(),
    not at bare module-import time: a bare-import mutation would silently
    strip pr_agent globally the moment ANYTHING imports this module for any
    reason (confirmed: a test importing _parse_maybe_fenced_json broke
    unrelated tests asserting root_agent still has pr_agent, since Python
    only runs a module's top level once per process and the mutation is
    on a shared object, not a copy)."""
    if pr_agent in root_agent.sub_agents:
        assert root_agent.sub_agents[-1] is pr_agent, "pr_agent is no longer last in root_agent.sub_agents"
        root_agent.sub_agents = root_agent.sub_agents[:-1]
    if any(a is design_consistency_agent for a in generation_stage.sub_agents):
        generation_stage.sub_agents = [
            a for a in generation_stage.sub_agents if a is not design_consistency_agent
        ]


_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name="posgmo_factory_local", session_service=_session_service)


def _parse_maybe_fenced_json(raw) -> dict | None:
    """backend_artifacts is a JSON string, sometimes wrapped in ```json
    fences the LLM adds despite being told not to -- same shape orchestrator.py's
    run_factory() already has to handle for this exact check."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    body = raw.strip()
    if body.startswith("```"):
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("```")).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


async def run_local(prd_dict: dict, user_id: str = "factory", target: str = "pos") -> dict:
    _strip_pr_and_design_consistency()
    prd = PRDInput.model_validate(prd_dict)
    session = await _session_service.create_session(
        app_name="posgmo_factory_local",
        user_id=user_id,
        state=_build_session_state(prd, target=target),
    )
    message = Content(role="user", parts=[Part(text=json.dumps(prd.model_dump()))])

    async for event in _runner.run_async(user_id=user_id, session_id=session.id, new_message=message):
        pass

    updated = await _session_service.get_session(
        app_name="posgmo_factory_local", user_id=user_id, session_id=session.id
    )
    result = dict(updated.state)

    # Artifact contract: did backend_artifacts actually implement every
    # custom endpoint the PRD asked for? This was silently missing from
    # every run_local_export.py run (Experiment 5's exact gap:
    # backend_agent can succeed and produce valid, review-passing code that
    # still omits a custom endpoint entirely) — only orchestrator.py's
    # run_factory() had this check. Ported directly from there.
    be_artifact = _parse_maybe_fenced_json(result.get("backend_artifacts", ""))
    endpoint_completeness = check_backend_endpoint_completeness(prd.model_dump(), be_artifact)
    result["backend_endpoint_completeness"] = endpoint_completeness
    if endpoint_completeness["status"] != "SATISFIED":
        print(f"[artifact-contract] {endpoint_completeness['status']} — {endpoint_completeness['detail']}", flush=True)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("prd_path", type=Path)
    parser.add_argument("--target", choices=sorted(_REPO_ENV_VARS), default="pos")
    parsed = parser.parse_args()

    prd_data = json.loads(parsed.prd_path.read_text(encoding="utf-8"))
    module = prd_data["module"]

    state = asyncio.run(run_local(prd_data, target=parsed.target))

    out_dir = Path(__file__).parent / "local_export" / module
    out_dir.mkdir(parents=True, exist_ok=True)

    keep_keys = ["database_artifacts", "backend_artifacts", "frontend_artifacts", "design_brief", "review_result"]
    dump = {k: state.get(k, "{}") for k in keep_keys}
    dump["backend_endpoint_completeness"] = state.get("backend_endpoint_completeness", {})
    (out_dir / "artifacts.json").write_text(json.dumps(dump, indent=2), encoding="utf-8")

    print(f"\n=== LOCAL EXPORT COMPLETE for '{module}' ===")
    print(f"Artifacts written to: {out_dir / 'artifacts.json'}")
    print("No GitHub call was made. No branch was created. Nothing was pushed.")
