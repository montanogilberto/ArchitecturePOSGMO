"""
PRD Parser — tool functions.
Extracted from prd_parser_agent.py for package structure.
"""
from __future__ import annotations
import json
import os

from google.adk.tools.tool_context import ToolContext


# MUST agree with orchestrator.py's _REPO_ENV_VARS. This function runs after
# orchestrator.py's _build_session_state has already picked a target/repo
# pair — if this dict disagreed, store_prd_context would silently overwrite
# that choice back to the "pos" pair on every run, regardless of what target
# was actually requested.
_REPO_ENV_VARS = {
    "pos": ("GITHUB_REPO_NAME", "GITHUB_BACKEND_REPO_NAME"),
    "commercial": ("GITHUB_COMMERCIAL_FRONTEND_REPO", "GITHUB_COMMERCIAL_BACKEND_REPO"),
}


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
        parent: Optional parent module name.

    Returns:
        Confirmation dict with the stored keys.
    """
    Module = module[:1].upper() + module[1:] if module else ""
    Parent = parent[:1].upper() + parent[1:] if parent else ""

    # Read the target orchestrator.py's _build_session_state already picked —
    # never re-derive it independently, or the two can disagree.
    target = tool_context.state.get("target_repo", "pos")
    frontend_env, backend_env = _REPO_ENV_VARS.get(target, _REPO_ENV_VARS["pos"])

    tool_context.state.update({
        "module": module,
        "plural": plural,
        "Module": Module,
        "table": f"{Module}s",
        "Table": f"{Module}s",
        "id": f"{module}Id",
        "parent": parent,
        "Parent": Parent,
        "col": "col",
        "pk": "pk",
        "fk_table": "fk_table",
        "fk_column": "fk_column",
        "loading": "loading",
        "error": "error",
        "target_repo": target,
        "GITHUB_FRONTEND_REPO": _gh_slug(frontend_env),
        "GITHUB_BACKEND_REPO": _gh_slug(backend_env),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        "GITHUB_REPO_OWNER": os.getenv("GITHUB_REPO_OWNER", ""),
        "GITHUB_REPO_NAME": _gh_slug(frontend_env),
    })
    return {"status": "stored", "module": module, "plural": plural, "Module": Module}