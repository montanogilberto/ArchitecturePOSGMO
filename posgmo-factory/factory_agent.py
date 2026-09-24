"""
Factory Agent — Phase 5: the closed loop.

    raw request
        |
        v
    prd_builder_agent (Phase 4)          -- research + write the PRD
        |
        v
    PRDInput.model_validate (strict)     -- fail loudly, don't proceed on bad data
        |
        v
    run_local_export.run_local()         -- Architect -> Decision Gate ->
        |                                    Construction -> Reviewer ->
        |                                    Fix Loop (already exists,
        |                                    ADK LoopAgent, up to 3 iterations)
        v
    PASS/FAIL result, real artifacts
        |
        v
    factory_experience.build_index()     -- "Factory Memory": refresh the
                                             RAG index so this run's PRD +
                                             any local_export artifacts are
                                             retrievable by the NEXT call

Deliberately sandboxed, same as every other run in this whole project:
run_local() strips pr_agent -- no GitHub call of any kind, regardless of
whether construction passes. Flipping that to a real push is a separate,
explicit decision this script does not make on its own.

Deliberately does NOT retry on a failed construction run. This project's
own standing discipline (established Milestone 1, restated every milestone
since): retrying to chase a lucky pass "measures API-call stochasticity,
not learn anything new about the architecture." A FAIL is reported
honestly, with the real review_result, not hidden behind another attempt.

"Factory Memory" is real but bounded: build_index() mechanically re-embeds
whatever is already on disk (PRDs, milestone findings, ADRs, local_export
artifacts) -- it does NOT write new milestone narrative. Turning a raw run
outcome into the kind of readable finding docs/commercial-app-milestones.md
contains still needs a person (or Claude) to write it, the same as every
milestone in this series so far. This script closes the MECHANICAL loop
(request -> PRD -> construction -> memory refresh), not the NARRATIVE one.

Usage:
    python factory_agent.py "I need a module for X" [--target commercial|pos]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from pydantic import ValidationError

from agents.prd_builder import prd_builder_agent
from prd_schema import PRDInput
from run_local_export import run_local
import factory_experience

_prd_builder_sessions = InMemorySessionService()
_prd_builder_runner = Runner(
    agent=prd_builder_agent, app_name="factory_agent_prd_builder", session_service=_prd_builder_sessions
)


async def _build_prd(request: str, user_id: str = "factory") -> str:
    """Runs prd_builder_agent on a raw request, returns its raw text
    response (either a PRD JSON string, or a plain-text clarifying
    question -- see prd_builder's own prompt for the `{`-prefix
    convention this function does not interpret, only returns)."""
    session = await _prd_builder_sessions.create_session(
        app_name="factory_agent_prd_builder", user_id=user_id, state={}
    )
    message = Content(role="user", parts=[Part(text=request)])
    final_text = ""
    async for event in _prd_builder_runner.run_async(user_id=user_id, session_id=session.id, new_message=message):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    final_text += part.text
    return final_text.strip()


async def run_factory_agent(request: str, user_id: str = "factory", target: str = "commercial") -> dict:
    """
    The closed loop, end to end. Returns one of:
      {"status": "needs_clarification", "question": str}
      {"status": "prd_invalid", "raw_output": str, "errors": str}
      {"status": "constructed", "module": str, "prd": dict, "review_result": dict, ...}
    """
    prd_output = await _build_prd(request, user_id=user_id)

    if not prd_output.startswith("{"):
        return {"status": "needs_clarification", "question": prd_output}

    try:
        prd_dict = json.loads(prd_output)
    except json.JSONDecodeError as e:
        return {"status": "prd_invalid", "raw_output": prd_output, "errors": f"not valid JSON: {e}"}

    try:
        prd = PRDInput.model_validate(prd_dict)
    except ValidationError as e:
        # Strict (extra="forbid") -- see prd_schema.py. Fails loudly here
        # rather than silently proceeding with malformed/incomplete data,
        # the exact failure mode Phase 4 found and closed.
        return {"status": "prd_invalid", "raw_output": prd_output, "errors": str(e)}

    prd_path = Path(__file__).parent / "tests" / f"prd_{prd.module}.json"
    if not prd_path.exists():
        prd_path.write_text(json.dumps(prd_dict, indent=2), encoding="utf-8")

    state = await run_local(prd_dict, user_id=user_id, target=target)

    review_raw = state.get("review_result", "{}")
    review_result = review_raw if isinstance(review_raw, dict) else json.loads(review_raw or "{}")

    # Factory Memory: refresh the RAG index so this run's PRD (and, if
    # construction succeeded, its local_export artifacts) are retrievable
    # by the next call. Best-effort -- a memory-refresh failure must never
    # be reported as a construction failure; the construction result above
    # is already final and correct regardless of whether this succeeds.
    memory_refreshed = False
    memory_error = None
    try:
        factory_experience.build_index()
        memory_refreshed = True
    except Exception as e:
        memory_error = str(e)

    return {
        "status": "constructed",
        "module": prd.module,
        "prd": prd_dict,
        "review_result": review_result,
        "memory_refreshed": memory_refreshed,
        "memory_error": memory_error,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=str, help="Raw, informal description of what to build")
    parser.add_argument("--target", choices=["commercial", "pos"], default="commercial")
    args = parser.parse_args()

    result = asyncio.run(run_factory_agent(args.request, target=args.target))

    print("\n=== FACTORY AGENT RESULT ===")
    print(json.dumps(result, indent=2, default=str))
