"""
POS GMO AI Factory — Root Orchestrator

Pipeline:
    PRDInput JSON 
        → root_agent (SequentialAgent: Architect → Database → Backend → Frontend → Reviewer → PR)

Usage:
    python orchestrator.py tests/prd_supplier.json
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv


from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agents import root_agent
from prd_schema import PRDInput

load_dotenv()

# ---------------------------------------------------------------------------
# Runner Configuration
# ---------------------------------------------------------------------------

_session_service = InMemorySessionService()

_runner = Runner(
    agent=root_agent,
    app_name="posgmo_factory",
    session_service=_session_service,
)


def _gh_repo_slug(env_var: str) -> str:
    """Extract 'owner/repo' from a full GitHub URL or a bare slug stored in an env var."""
    raw = os.getenv(env_var, "")
    # Strip trailing .git and leading https://github.com/
    raw = raw.rstrip("/").removesuffix(".git")
    if "github.com/" in raw:
        raw = raw.split("github.com/", 1)[1]
    return raw


def _build_session_state(prd: PRDInput) -> dict[str, str]:
    """
    Build required ADK template context for agent instruction placeholders.
    """
    module = prd.module or ""
    module_capitalized = module[:1].upper() + module[1:] if module else ""

    # Intentamos extraer un parent del PRD si existe, de lo contrario dejamos fallback vacío
    # Esto evita romper los formateadores de strings si el prompt usa {parent}
    parent_val = getattr(prd, "parent", "") or ""
    parent_capitalized = parent_val[:1].upper() + parent_val[1:] if parent_val else ""

    frontend_repo = _gh_repo_slug("GITHUB_REPO_NAME")
    backend_repo  = _gh_repo_slug("GITHUB_BACKEND_REPO_NAME")

    return {
        # Mapeos estándar del módulo
        "module": module,
        "Module": module_capitalized,
        "plural": f"{module}s",
        "id": f"{module}Id",

        # Mapeos de base de datos / tablas
        "table": f"{module_capitalized}s",
        "Table": f"{module_capitalized}s",

        # Contexto jerárquico (Solución al KeyError: 'parent')
        "parent": parent_val,
        "Parent": parent_capitalized,

        # Llaves genéricas adicionales por si otros agentes las buscan en el prompt
        "description": getattr(prd, "description", "") or "",

        # GitHub repo slugs (owner/repo) derived from env vars — used by PR Agent
        "GITHUB_FRONTEND_REPO": frontend_repo,
        "GITHUB_BACKEND_REPO":  backend_repo,

        # Placeholders usados como literales en instrucciones de agentes
        # (evita KeyError durante inject_session_state cuando aparezcan {col}, etc.)
        "col": "col",
        "fk_table": "fk_table",
        "fk_column": "fk_column",
        "loading": "loading",
        "error": "error",
        "GITHUB_REPO_OWNER": os.getenv("GITHUB_REPO_OWNER", ""),
        "GITHUB_REPO_NAME": os.getenv("GITHUB_REPO_NAME", ""),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
    }


async def run_factory(prd_dict: dict, user_id: str = "factory") -> dict:
    """
    Runs the full generation pipeline for a PRD using the pre-built root_agent.
    """
    prd = PRDInput.model_validate(prd_dict)

    session = await _session_service.create_session(
        app_name="posgmo_factory",
        user_id=user_id,
        state=_build_session_state(prd),
    )

    message = Content(
        role="user",
        parts=[Part(text=json.dumps(prd.model_dump()))],
    )

    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            pass  

    updated = await _session_service.get_session(
        app_name="posgmo_factory",
        user_id=user_id,
        session_id=session.id,
    )
    return dict(updated.state)


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

    # Save state for partial re-runs: python run_partial.py --from database --state last_state.json
    state_path = Path("last_state.json")
    state_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"Session state saved → {state_path}", flush=True)

    print("\n=== FACTORY RESULT ===")
    print(json.dumps(result, indent=2, default=str))