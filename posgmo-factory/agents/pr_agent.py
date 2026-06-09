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
from pathlib import Path
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


def save_sql_locally(module: str, sql_content: str) -> dict:
    """
    Saves the combined SQL (CREATE TABLE + SPs) to a local file so the user
    can run it manually against SQL Server.

    Args:
        module:      Module name, e.g. "supplier".
        sql_content: Full SQL string (CREATE TABLE + sp_upsert + sp_all + sp_one separated by GO).

    Returns:
        dict with "path" of the saved file.
    """
    out_dir = Path(__file__).parent.parent / "generated" / module
    out_dir.mkdir(parents=True, exist_ok=True)
    sql_path = out_dir / f"sp_{module}.sql"
    sql_path.write_text(sql_content, encoding="utf-8")
    return {"path": str(sql_path)}


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

        # Create branch (422 = already exists — safe to continue)
        r2 = client.post(
            f"{_GH_API}/repos/{repo}/git/refs",
            headers=_gh_headers(),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        if r2.status_code == 422:
            return {"status": "already_exists", "ref": f"refs/heads/{branch_name}"}
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


def patch_app_tsx(
    repo: str,
    branch: str,
    import_line: str,
    private_route: str,
    menu_item: str,
    menu_section: str,
) -> dict:
    """
    Fetches App.tsx from the frontend repo on the given branch, inserts the
    new module's import, PrivateRoute, and IonMenuToggle menu item, then
    pushes the updated file back.

    Args:
        repo:          Frontend repo slug, e.g. "montanogilberto/POSVending".
        branch:        Feature branch to push to.
        import_line:   Full import statement, e.g. "import SupplierPage from './pages/SupplierPage';"
        private_route: Full PrivateRoute JSX line, e.g. '<PrivateRoute exact path="/suppliers" component={SupplierPage} />'
        menu_item:     Full IonMenuToggle JSX block (may be multi-line).
        menu_section:  IonItemDivider label to insert AFTER, e.g. "Catálogo".

    Returns:
        dict with "status" and GitHub push response.
    """
    with httpx.Client(timeout=30) as client:
        # 1. Fetch current App.tsx
        r = client.get(
            f"{_GH_API}/repos/{repo}/contents/src/App.tsx",
            headers=_gh_headers(),
            params={"ref": branch},
        )
        r.raise_for_status()
        data = r.json()
        file_sha = data["sha"]
        original = base64.b64decode(data["content"]).decode("utf-8")

    lines = original.splitlines(keepends=True)

    # --- 1. Insert import after last "./pages/" import line ---
    last_page_import = -1
    for i, line in enumerate(lines):
        if "from './pages/" in line and line.strip().startswith("import "):
            last_page_import = i
    if last_page_import == -1:
        return {"status": "error", "detail": "Could not locate page import block in App.tsx"}
    if import_line + "\n" not in lines:
        lines.insert(last_page_import + 1, import_line + "\n")

    # Rebuild after first mutation
    content = "".join(lines)
    lines = content.splitlines(keepends=True)

    # --- 2. Insert PrivateRoute before closing </IonRouterOutlet> inside IonTabs ---
    # Find the IonRouterOutlet that is inside IonTabs (not the root one)
    in_tabs = False
    router_outlet_close = -1
    for i, line in enumerate(lines):
        if "<IonTabs>" in line:
            in_tabs = True
        if in_tabs and "</IonRouterOutlet>" in line:
            router_outlet_close = i
            break

    if router_outlet_close == -1:
        return {"status": "error", "detail": "Could not locate IonRouterOutlet closing tag inside IonTabs"}

    route_stripped = private_route.strip()
    already_has_route = any(route_stripped in ln for ln in lines)
    if not already_has_route:
        # Determine indentation from surrounding lines
        indent = "            "
        lines.insert(router_outlet_close, indent + route_stripped + "\n")

    content = "".join(lines)
    lines = content.splitlines(keepends=True)

    # --- 3. Insert menu item after the correct IonItemDivider ---
    divider_idx = -1
    for i, line in enumerate(lines):
        if f"<IonItemDivider>{menu_section}</IonItemDivider>" in line:
            divider_idx = i
            break

    if divider_idx == -1:
        return {"status": "error", "detail": f"IonItemDivider '{menu_section}' not found in App.tsx"}

    # Find the first IonMenuToggle AFTER this divider and insert our item before it
    insert_at = divider_idx + 1
    for i in range(divider_idx + 1, len(lines)):
        if "<IonMenuToggle" in lines[i]:
            insert_at = i
            break

    # Check it's not already there
    # Extract route path from private_route (e.g. "/client-face-recognition") for duplicate check
    parts = private_route.split('"')
    menu_check = parts[1] if len(parts) >= 2 else ""
    already_has_menu = any(menu_check in ln for ln in lines) if menu_check else False
    if not already_has_menu:
        indent = "            "
        menu_lines = [indent + ln + "\n" for ln in menu_item.splitlines()]
        menu_lines.append("\n")
        for j, ml in enumerate(menu_lines):
            lines.insert(insert_at + j, ml)

    new_content = "".join(lines)

    # --- 4. Push updated App.tsx ---
    encoded = base64.b64encode(new_content.encode()).decode()
    with httpx.Client(timeout=30) as client:
        r = client.put(
            f"{_GH_API}/repos/{repo}/contents/src/App.tsx",
            headers=_gh_headers(),
            json={
                "message": f"feat: add {import_line.split('from')[0].strip().replace('import ', '')} route and menu item",
                "content": encoded,
                "branch": branch,
                "sha": file_sha,
            },
        )
        r.raise_for_status()
        return {"status": "patched", "file": "src/App.tsx", "response": r.json().get("content", {}).get("name")}


def patch_setting_tsx(
    repo: str,
    branch: str,
    section: str,
    code: str,
    label: str,
    icon: str,
) -> dict:
    """
    Fetches src/pages/Setting.tsx from the frontend repo, adds the new module
    feature entry inside the correct MODULES section, then pushes it back.

    Args:
        repo:    Frontend repo slug, e.g. "montanogilberto/POSVending".
        branch:  Feature branch to push to.
        section: MODULES section name, e.g. "Catálogo".
        code:    UiFeature code, e.g. "suppliers".
        label:   Spanish display label, e.g. "Proveedores".
        icon:    Outline icon variable name, e.g. "peopleOutline".

    Returns:
        dict with "status" and push result.
    """
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{_GH_API}/repos/{repo}/contents/src/pages/Setting.tsx",
            headers=_gh_headers(),
            params={"ref": branch},
        )
        r.raise_for_status()
        data = r.json()
        file_sha = data["sha"]
        original = base64.b64decode(data["content"]).decode("utf-8")

    # Check if already present
    if f"code: '{code}'" in original:
        return {"status": "already_present", "code": code}

    lines = original.splitlines(keepends=True)

    # Find the section block: name: '<section>'
    section_line = -1
    for i, line in enumerate(lines):
        if f"name: '{section}'" in line:
            section_line = i
            break

    if section_line == -1:
        return {"status": "error", "detail": f"Section '{section}' not found in MODULES"}

    # Find the closing `]` of that section's features array
    # Walk forward to find the features array open then its close
    depth = 0
    in_features = False
    insert_before = -1
    for i in range(section_line, len(lines)):
        line = lines[i]
        if 'features:' in line:
            in_features = True
        if in_features:
            depth += line.count('[') - line.count(']')
            if depth <= 0 and in_features and i > section_line:
                # This line closes the features array — insert before it
                insert_before = i
                break

    if insert_before == -1:
        return {"status": "error", "detail": f"Could not find end of features array for section '{section}'"}

    # Detect indentation from nearby feature lines
    indent = "      "
    for i in range(section_line, insert_before):
        if "{ code:" in lines[i]:
            indent = " " * (len(lines[i]) - len(lines[i].lstrip()))
            break

    new_entry = f"{indent}{{ code: '{code}', label: '{label}', icon: {icon} }},\n"
    lines.insert(insert_before, new_entry)

    new_content = "".join(lines)
    encoded = base64.b64encode(new_content.encode()).decode()

    with httpx.Client(timeout=30) as client:
        r = client.put(
            f"{_GH_API}/repos/{repo}/contents/src/pages/Setting.tsx",
            headers=_gh_headers(),
            json={
                "message": f"feat: add {code} to Setting.tsx permissions matrix",
                "content": encoded,
                "branch": branch,
                "sha": file_sha,
            },
        )
        r.raise_for_status()
        return {"status": "patched", "file": "src/pages/Setting.tsx", "added": code}


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
- "database_artifacts"  — {{ create_table, sp_upsert, sp_all, sp_one }}
- "backend_artifacts"   — {{ module_file, route_file, docs_files }}
- "frontend_artifacts"  — {{ api_file, page_file, css_file }}
- "review_result"       — {{ scores, passed, issues, summary }}

## Pre-condition
Check BOTH conditions before doing anything:
1. If gate_result.status is "BLOCKED":
   respond with {{ "status": "blocked", "reason": gate_result.reason, "fix": gate_result.fix }} and stop.
2. If review_result.passed is false:
   respond with {{ "status": "blocked", "reason": "Review failed. Fix issues before PR.", "issues": review_result.issues }} and stop.
Only proceed if gate_result.status is "APPROVED" AND review_result.passed is true.

## Steps to execute (in order)
1. Read repo names from session state:
   - Frontend repo: {{GITHUB_FRONTEND_REPO}}
   - Backend repo:  {{GITHUB_BACKEND_REPO}}
2. Branch name: "feat/{{module}}-module"
3. Call github_create_branch for the frontend repo.
4. Call github_create_branch for the backend repo.
5. Push backend files to the backend repo:
   - backend_artifacts.module_file  → modules/{{module}}.py
   - backend_artifacts.route_file   → routes_/{{module}}.py
   - For each entry in backend_artifacts.docs_files → push to that entry's path
6. Push the 3 module frontend files (api_file, page_file, css_file) to the frontend repo.
7. Call patch_app_tsx with:
   - repo: frontend repo slug
   - branch: the feature branch just created
   - import_line: frontend_artifacts.app_patches.import_line
   - private_route: frontend_artifacts.app_patches.private_route
   - menu_item: frontend_artifacts.app_patches.menu_item
   - menu_section: frontend_artifacts.app_patches.menu_section
   This patches src/App.tsx: adds import, PrivateRoute, and side-menu IonMenuToggle.
8. Call patch_setting_tsx with:
   - repo: frontend repo slug
   - branch: the feature branch
   - section: frontend_artifacts.setting_patch.section
   - code: frontend_artifacts.setting_patch.code
   - label: frontend_artifacts.setting_patch.label
   - icon: frontend_artifacts.setting_patch.icon
   This patches src/pages/Setting.tsx: adds the feature to the MODULES permissions matrix.
9. Push database SQL as "sql_logic/sp_{{module}}.sql" to the backend repo.
   Combine: create_table + sp_upsert + sp_all + sp_one, each separated by a GO line.
9. Save the same SQL file locally using save_sql_locally.
10. Create PR on frontend repo.
11. Create PR on backend repo.

Note: step numbers shifted — renumber 9→10→11→12 accordingly.

## PR body template

If review_result.passed is true, use this body:
```
## {{Module}} Module — Auto-generated by POS GMO AI Factory

### Review scores ✅
| Artifact | Score |
|---|---|
| Database | {{review_result.scores.database}}/100 |
| Backend  | {{review_result.scores.backend}}/100  |
| Frontend | {{review_result.scores.frontend}}/100 |

### Files changed
- src/api/{{module}}Api.ts
- src/pages/{{Module}}Page.tsx
- src/pages/{{Module}}Page.css
- src/App.tsx ← import + PrivateRoute + menu item
- src/pages/Setting.tsx ← feature added to permissions
- modules/{{plural}}.py
- routes_/{{module}}.py
- docs_description/{{plural}}*.txt (×3)
- sql_logic/sp_{{plural}}.sql
```

If review_result.passed is false, use this body (add the issues section):
```
## {{Module}} Module — Auto-generated by POS GMO AI Factory
> ⚠️ **Review found issues — human review required before merging.**

### Review scores
| Artifact | Score | Status |
|---|---|---|
| Database | {{review_result.scores.database}}/100 | {{pass/fail}} |
| Backend  | {{review_result.scores.backend}}/100  | {{pass/fail}} |
| Frontend | {{review_result.scores.frontend}}/100 | {{pass/fail}} |

### Issues to fix
For each item in review_result.issues, add a line:
- ❌ [artifact] `file` — message

### Files changed
- src/api/{{module}}Api.ts
- src/pages/{{Module}}Page.tsx
- src/pages/{{Module}}Page.css
- src/App.tsx ← import + PrivateRoute + menu item
- src/pages/Setting.tsx ← feature added to permissions
- modules/{{plural}}.py
- routes_/{{module}}.py
- docs_description/{{plural}}*.txt (×3)
- sql_logic/sp_{{plural}}.sql
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
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[
        FunctionTool(func=save_sql_locally),
        FunctionTool(func=github_create_branch),
        FunctionTool(func=github_push_file),
        FunctionTool(func=patch_app_tsx),
        FunctionTool(func=patch_setting_tsx),
        FunctionTool(func=github_create_pr),
    ],
    output_key="pr_result",
)
