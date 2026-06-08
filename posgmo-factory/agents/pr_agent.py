"""
PR Agent

Final step in the pipeline. Reads all generated artifacts from session state,
writes files to disk in a git branch, and opens a Pull Request via the GitHub API.

Requires GITHUB_TOKEN, GITHUB_REPO_OWNER, and repo name env vars.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

# ---------------------------------------------------------------------------
# GitHub API helpers (called as ADK FunctionTools)
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"


def _gh_headers() -> dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_create_branch(repo: str, branch_name: str, base_branch: str = "main") -> dict:
    """
    Creates a new git branch in the given GitHub repository.

    Args:
        repo:        Full repo name, e.g. "montanogilberto/checkInPOS".
        branch_name: Name of the branch to create, e.g. "feat/supplier-module".
        base_branch: Branch to fork from. Defaults to "main".

    Returns:
        GitHub API response dict with ref and sha.
    """
    with httpx.Client() as client:
        # Get base SHA
        r = client.get(f"{_GH_API}/repos/{repo}/git/ref/heads/{base_branch}",
                       headers=_gh_headers())
        r.raise_for_status()
        sha = r.json()["object"]["sha"]

        # Create branch
        r2 = client.post(
            f"{_GH_API}/repos/{repo}/git/refs",
            headers=_gh_headers(),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        r2.raise_for_status()
        return r2.json()


def github_push_file(repo: str, branch: str, path: str, content: str, message: str) -> dict:
    """
    Creates or updates a single file in a GitHub repository branch.

    Args:
        repo:    Full repo name, e.g. "montanogilberto/checkInPOS".
        branch:  Target branch name.
        path:    File path relative to repo root, e.g. "src/api/supplierApi.ts".
        content: Full file content as a plain string.
        message: Commit message for this file.

    Returns:
        GitHub API response dict.
    """
    encoded = base64.b64encode(content.encode()).decode()
    with httpx.Client() as client:
        # Check if file already exists (get its SHA if so)
        sha: str | None = None
        existing = client.get(
            f"{_GH_API}/repos/{repo}/contents/{path}",
            headers=_gh_headers(),
            params={"ref": branch},
        )
        if existing.status_code == 200:
            sha = existing.json()["sha"]

        payload: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r = client.put(
            f"{_GH_API}/repos/{repo}/contents/{path}",
            headers=_gh_headers(),
            json=payload,
        )
        r.raise_for_status()
        return r.json()


def github_create_pr(repo: str, branch: str, title: str, body: str,
                     base_branch: str = "main") -> dict:
    """
    Opens a Pull Request on GitHub.

    Args:
        repo:        Full repo name.
        branch:      Head branch (the feature branch).
        title:       PR title.
        body:        PR description in markdown.
        base_branch: Target branch. Defaults to "main".

    Returns:
        GitHub API response dict including "html_url" of the PR.
    """
    with httpx.Client() as client:
        r = client.post(
            f"{_GH_API}/repos/{repo}/pulls",
            headers=_gh_headers(),
            json={"title": title, "body": body, "head": branch, "base": base_branch},
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

INSTRUCTION = """
You are the PR Agent for POS GMO.

## Input (all from session state)
- "specification"       — SpecificationJSON
- "database_artifacts"  — { create_table, sp_upsert, sp_all, sp_one }
- "backend_artifacts"   — { model_file, schema_file, route_file }
- "frontend_artifacts"  — { api_file, page_file, css_file }
- "review_result"       — { scores, passed, issues, summary }

## Pre-condition
ONLY proceed if review_result.passed is true.
If passed is false, respond with:
{ "status": "blocked", "reason": "Review failed. Fix issues before PR." }

## Steps to execute (in order)
1. Read GITHUB_REPO_OWNER from env. Derive repo names:
   - Frontend repo: {GITHUB_REPO_OWNER}/checkInPOS
   - Backend repo:  {GITHUB_REPO_OWNER}/smartloans
2. Branch name: "feat/{{module}}-module"
3. Call github_create_branch for the frontend repo.
4. Call github_create_branch for the backend repo.
5. Push backend files (3 files from backend_artifacts) to the backend repo.
6. Push frontend files (3 files from frontend_artifacts) to the frontend repo.
7. Push database files as a single SQL file "sql_logic/sp_{{module}}.sql" to the backend repo.
   Combine: create_table + sp_upsert + sp_all + sp_one, separated by GO.
8. Create PR on frontend repo.
9. Create PR on backend repo.

## PR body template
```
## {{Module}} Module — Auto-generated by POS GMO AI Factory

### Review scores
- Database: {db_score}/100
- Backend:  {be_score}/100
- Frontend: {fe_score}/100

### Files changed
- `{api_file}`
- `{page_file}`
- `{css_file}`
- `{model_file}`
- `{schema_file}`
- `{route_file}`
- `sql_logic/sp_{{module}}.sql`

### Notes
Generated from PRD. Reviewer passed all checks.
```

## Output format
{
  "status": "created",
  "frontend_pr_url": "<url>",
  "backend_pr_url":  "<url>",
  "branch":          "feat/{{module}}-module"
}
"""


pr_agent = Agent(
    name="pr_agent",
    description=(
        "Pushes all generated module files to GitHub branches and opens "
        "Pull Requests on the frontend and backend repos."
    ),
    model="gemini-2.0-flash",
    instruction=INSTRUCTION,
    tools=[
        FunctionTool(func=github_create_branch),
        FunctionTool(func=github_push_file),
        FunctionTool(func=github_create_pr),
    ],
    output_key="pr_result",
)
