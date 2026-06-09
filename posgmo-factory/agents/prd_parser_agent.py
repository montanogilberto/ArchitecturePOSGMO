"""
PRD Parser Agent

First agent in the pipeline (adk web AND CLI).
Reads the PRD JSON from the user message, extracts naming variables,
and writes them to session state so downstream agent instructions
can use {module}, {plural}, {Module}, etc. via inject_session_state.

This is required because adk web does not call orchestrator._build_session_state.
"""

from __future__ import annotations

import json
import os

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext


def _gh_slug(env_var: str) -> str:
    raw = os.getenv(env_var, "").rstrip("/").removesuffix(".git")
    if "github.com/" in raw:
        raw = raw.split("github.com/", 1)[1]
    return raw


def store_prd_context(module: str, plural: str, tool_context: ToolContext, parent: str = "") -> dict:
    """
    Store PRD-derived variables in session state for downstream agents.

    Args:
        module: Singular camelCase module name, e.g. "supplier".
        plural: Plural form, e.g. "suppliers".

    Returns:
        Confirmation dict with the stored keys.
    """
    Module = module[:1].upper() + module[1:] if module else ""
    Parent = parent[:1].upper() + parent[1:] if parent else ""
    tool_context.state.update({
        # Core naming
        "module": module,
        "plural": plural,
        "Module": Module,
        # DB helpers
        "table": f"{Module}s",
        "Table": f"{Module}s",
        "id": f"{module}Id",
        # Parent module (optional, empty string for top-level modules)
        "parent": parent,
        "Parent": Parent,
        # Generic placeholders (prevent inject_session_state KeyErrors)
        "col": "col",
        "fk_table": "fk_table",
        "fk_column": "fk_column",
        "loading": "loading",
        "error": "error",
        # GitHub slugs read from env
        "GITHUB_FRONTEND_REPO": _gh_slug("GITHUB_REPO_NAME"),
        "GITHUB_BACKEND_REPO": _gh_slug("GITHUB_BACKEND_REPO_NAME"),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        "GITHUB_REPO_OWNER": os.getenv("GITHUB_REPO_OWNER", ""),
        "GITHUB_REPO_NAME": _gh_slug("GITHUB_REPO_NAME"),
    })
    return {"status": "stored", "module": module, "plural": plural, "Module": Module}


INSTRUCTION = """
You are the PRD Parser — the very first step of the POS GMO AI Factory pipeline.

## Your ONLY job
1. Read the PRD JSON from the user message.
2. Extract:
   - module: the camelCase singular name (e.g. "supplier")
   - plural: the plural form (e.g. "suppliers" — usually module + "s")
   - parent: parent module if present in the PRD, otherwise empty string ""
3. Call store_prd_context(module=..., plural=..., parent=...) IMMEDIATELY.
4. Output ONLY a JSON confirmation, nothing else:
   {"status": "ready", "module": "<module>", "plural": "<plural>"}

Do NOT call any other tool. Do NOT analyze the PRD further — that is the Architect Agent's job.
"""


prd_parser_agent = Agent(
    name="prd_parser_agent",
    description=(
        "Parses the incoming PRD JSON, extracts module naming variables, "
        "and writes them to session state so all downstream agents can "
        "use {module}, {plural}, {Module}, etc. in their instructions."
    ),
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[FunctionTool(func=store_prd_context)],
    output_key="prd_context",
)
