# PR Agent — GitHub API helpers.
# Functions: github_create_branch, github_push_file, patch_app_tsx, patch_main_py, etc.

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx

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
    icon_name: str = "",
) -> dict:
    """
    Fetches App.tsx from the frontend repo on the given branch, inserts the
    new module's import, icon (into ionicons/icons import), PrivateRoute,
    and IonMenuToggle menu item, then pushes the updated file back.

    Args:
        repo:          Frontend repo slug, e.g. "montanogilberto/POSVending".
        branch:        Feature branch to push to.
        import_line:   Full import statement, e.g. "import SupplierPage from './pages/SupplierPage';"
        private_route: Full PrivateRoute JSX line.
        menu_item:     Full IonMenuToggle JSX block (may be multi-line).
        menu_section:  IonItemDivider label to insert AFTER, e.g. "Catálogo".
        icon_name:     Outline icon variable name WITHOUT 'Outline' suffix (e.g. "storefront").
                       Will be imported as "{icon_name}Outline" from ionicons/icons.

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

    # --- 0. Add icon to ionicons/icons import block ---
    if icon_name:
        icon_outline = f"{icon_name}Outline"
        # Check if icon already imported
        already_icon = any(icon_outline in ln for ln in lines)
        if not already_icon:
            # Find the ionicons/icons import line(s) and insert the icon
            for i, line in enumerate(lines):
                if "from 'ionicons/icons'" in line or 'from "ionicons/icons"' in line:
                    # Single-line: `import { a, b } from 'ionicons/icons';`
                    if "{" in line and "}" in line:
                        lines[i] = line.replace("} from", f"  {icon_outline},\n}} from", 1)
                    else:
                        # Multi-line import — find closing brace line
                        for j in range(i, min(i + 30, len(lines))):
                            if "}" in lines[j]:
                                stripped = lines[j].rstrip()
                                lines[j] = stripped.rstrip("}").rstrip().rstrip(",") + f",\n  {icon_outline},\n}}\n"
                                break
                    break

        content = "".join(lines)
        lines = content.splitlines(keepends=True)

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


def patch_ui_feature_type(
    repo: str,
    branch: str,
    feature_code: str,
    type_file_path: str = "src/config/rolePermissions.ts",
) -> dict:
    """
    Fetches the file that declares 'export type UiFeature' and adds the new
    feature code as a union member (| 'feature_code'), then pushes it back.

    Args:
        repo:           Frontend repo slug, e.g. "montanogilberto/POSVending".
        branch:         Feature branch to push to.
        feature_code:   Plural lowercase code, e.g. "suppliers".
        type_file_path: Repo-relative path to the file containing UiFeature.
                        Defaults to "src/config/rolePermissions.ts". Try
                        "src/utils/canAccess.ts" or "src/types/roles.ts" if 404.

    Returns:
        dict with "status".
    """
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{_GH_API}/repos/{repo}/contents/{type_file_path}",
            headers=_gh_headers(),
            params={"ref": branch},
        )
        if r.status_code == 404:
            # Try alternate locations in priority order
            for alt in ("src/utils/canAccess.ts", "src/types/roles.ts"):
                r = client.get(
                    f"{_GH_API}/repos/{repo}/contents/{alt}",
                    headers=_gh_headers(),
                    params={"ref": branch},
                )
                if r.status_code == 200:
                    type_file_path = alt
                    break
            else:
                return {"status": "skipped", "detail": f"UiFeature type file not found at {type_file_path} or alternates"}
            type_file_path = alt
        r.raise_for_status()
        data = r.json()
        file_sha = data["sha"]
        original = base64.b64decode(data["content"]).decode("utf-8")

    # Idempotent
    if f"'{feature_code}'" in original:
        return {"status": "already_present", "feature": feature_code}

    lines = original.splitlines(keepends=True)

    # Find the UiFeature type declaration and insert before its closing semicolon
    # Pattern:
    #   export type UiFeature =
    #     | 'existing'
    #     | 'another';     ← insert new entry before the final semicolon member
    in_ui_feature = False
    last_member_line = -1
    for i, line in enumerate(lines):
        if "export type UiFeature" in line:
            in_ui_feature = True
        if in_ui_feature:
            stripped = line.strip()
            if stripped.startswith("|") and ("'" in stripped or '"' in stripped):
                last_member_line = i
            # Stop at blank line or next export/const that closes the type
            if i > 0 and in_ui_feature and last_member_line >= 0:
                next_stripped = line.strip()
                if next_stripped and not next_stripped.startswith("|") and not next_stripped.startswith("export type UiFeature"):
                    break

    if last_member_line == -1:
        return {"status": "error", "detail": "Could not locate UiFeature union members"}

    # Detect indentation from existing member lines
    indent = "  "
    ref_line = lines[last_member_line]
    indent = " " * (len(ref_line) - len(ref_line.lstrip()))

    # Remove trailing semicolon from last member if present, add comma/union
    lines[last_member_line] = lines[last_member_line].rstrip().rstrip(";") + "\n"
    lines.insert(last_member_line + 1, f"{indent}| '{feature_code}';\n")

    new_content = "".join(lines)
    encoded = base64.b64encode(new_content.encode()).decode()

    with httpx.Client(timeout=30) as client:
        r = client.put(
            f"{_GH_API}/repos/{repo}/contents/{type_file_path}",
            headers=_gh_headers(),
            json={
                "message": f"feat: add '{feature_code}' to UiFeature type",
                "content": encoded,
                "branch": branch,
                "sha": file_sha,
            },
        )
        r.raise_for_status()
        return {"status": "patched", "file": type_file_path, "added": feature_code}


def patch_main_py(
    repo: str,
    branch: str,
    module: str,
    route_module: str,
) -> dict:
    """
    Fetches main.py from the backend repo, inserts the new router's import
    and app.include_router() call, then pushes the updated file back.

    Args:
        repo:         Backend repo slug, e.g. "montanogilberto/smartloans_backend".
        branch:       Feature branch to push to.
        module:       Module name (singular snake_case), e.g. "supplier".
        route_module: Python module name inside routes_/, e.g. "supplier"
                      (becomes `from routes_ import ... , supplier`).

    Returns:
        dict with "status" and GitHub push response.
    """
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{_GH_API}/repos/{repo}/contents/main.py",
            headers=_gh_headers(),
            params={"ref": branch},
        )
        r.raise_for_status()
        data = r.json()
        file_sha = data["sha"]
        original = base64.b64decode(data["content"]).decode("utf-8")

    # Idempotent — skip if already patched
    if f" {route_module}," in original or f" {route_module}\n" in original or f",{route_module}" in original:
        return {"status": "already_present", "module": route_module}

    lines = original.splitlines(keepends=True)

    # --- 1. Add to the from routes_ import (...) block ---
    # Find the closing paren of the import block
    import_close = -1
    in_import = False
    for i, line in enumerate(lines):
        if "from routes_ import" in line:
            in_import = True
        if in_import and ")" in line:
            import_close = i
            break

    if import_close == -1:
        return {"status": "error", "detail": "Could not locate 'from routes_ import' block in main.py"}

    # Detect indentation from the line above the closing paren
    indent = "    "
    if import_close > 0:
        prev = lines[import_close - 1]
        indent = " " * (len(prev) - len(prev.lstrip()))

    # Insert new import entry before the closing paren line
    lines.insert(import_close, f"{indent}{route_module},\n")

    content = "".join(lines)
    lines = content.splitlines(keepends=True)

    # --- 2. Add app.include_router() call ---
    # Find the last app.include_router line and insert after it
    last_router = -1
    for i, line in enumerate(lines):
        if "app.include_router(" in line:
            last_router = i

    if last_router == -1:
        return {"status": "error", "detail": "Could not locate app.include_router() calls in main.py"}

    router_line = f"app.include_router({route_module}.router)\n"
    # Idempotent check
    if not any(f"include_router({route_module}" in ln for ln in lines):
        lines.insert(last_router + 1, router_line)

    new_content = "".join(lines)
    encoded = base64.b64encode(new_content.encode()).decode()

    with httpx.Client(timeout=30) as client:
        r = client.put(
            f"{_GH_API}/repos/{repo}/contents/main.py",
            headers=_gh_headers(),
            json={
                "message": f"feat: register {route_module} router in main.py",
                "content": encoded,
                "branch": branch,
                "sha": file_sha,
            },
        )
        r.raise_for_status()
        return {"status": "patched", "file": "main.py", "added": route_module}


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
        if r.status_code == 422:
            # PR already exists for this branch — fetch it and return its URL
            existing = client.get(
                f"{_GH_API}/repos/{repo}/pulls",
                headers=_gh_headers(),
                params={"head": branch, "state": "open"},
            )
            if existing.status_code == 200 and existing.json():
                pr = existing.json()[0]
                return {"status": "already_exists", "html_url": pr["html_url"], "number": pr["number"]}
            return {"status": "already_exists", "html_url": "", "detail": r.text}
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
