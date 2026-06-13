"""
PRD Parser — tool functions.
Extracted from prd_parser_agent.py for package structure.
"""
from __future__ import annotations
import json
import os

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
        parent: Optional parent module name.

    Returns:
        Confirmation dict with the stored keys.
    """
    Module = module[:1].upper() + module[1:] if module else ""
    Parent = parent[:1].upper() + parent[1:] if parent else ""
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
        "GITHUB_FRONTEND_REPO": _gh_slug("GITHUB_REPO_NAME"),
        "GITHUB_BACKEND_REPO": _gh_slug("GITHUB_BACKEND_REPO_NAME"),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        "GITHUB_REPO_OWNER": os.getenv("GITHUB_REPO_OWNER", ""),
        "GITHUB_REPO_NAME": _gh_slug("GITHUB_REPO_NAME"),
    })
    return {"status": "stored", "module": module, "plural": plural, "Module": Module}