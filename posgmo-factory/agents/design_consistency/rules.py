# Design Consistency Agent — tool functions.
# fetch_design_reference fetches real pages from GitHub and extracts patterns.

from __future__ import annotations

import base64
import os
import re

import httpx
from google.adk.tools.tool_context import ToolContext

_GH_API = "https://api.github.com"

# Representative pages to sample — varied complexity
_REFERENCE_PAGES = [
    "src/pages/ClientsPage.tsx",          # simple CRUD list
    "src/pages/ExpensesPage.tsx",         # financial module
    "src/pages/UsersPage.tsx",            # admin module with roles
]

_REFERENCE_CSS = [
    "src/pages/ClientsPage.css",
    "src/pages/ExpensesPage.css",
]


def _gh_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_file(client: httpx.Client, repo: str, path: str) -> str | None:
    """Fetch a single file from GitHub main branch. Returns content or None."""
    for attempt in range(3):
        try:
            r = client.get(
                f"{_GH_API}/repos/{repo}/contents/{path}",
                headers=_gh_headers(),
                params={"ref": "main"},
                timeout=30.0,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return base64.b64decode(r.json()["content"]).decode("utf-8")
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            if attempt == 2:
                return None  # give up after 3 attempts, don't crash the pipeline


def _extract_patterns(source: str, filename: str) -> dict:
    """Extract key patterns from a TSX source file."""
    lines = source.splitlines()

    # Ionic components used
    ionic_imports = re.findall(r'Ion\w+', source)
    ionic_components = sorted(set(ionic_imports))

    # State declarations
    use_states = [ln.strip() for ln in lines if "useState" in ln]

    # useEffect blocks (just first line of each)
    use_effects = [ln.strip() for ln in lines if "useEffect" in ln]

    # Modal pattern detection
    has_modal = "IonModal" in source
    modal_trigger = ""
    if has_modal:
        for ln in lines:
            if "IonModal" in ln and "isOpen" in ln:
                modal_trigger = ln.strip()
                break

    # CSS class names used
    css_classes = re.findall(r'className=["\']([^"\']+)["\']', source)
    css_classes = sorted(set(css_classes))

    # API call patterns (fetch/api functions called)
    api_calls = re.findall(r'await\s+(\w+)\(', source)
    api_calls = sorted(set(api_calls))

    # Form field patterns
    ion_inputs = [ln.strip() for ln in lines if "<IonInput" in ln]
    ion_selects = [ln.strip() for ln in lines if "<IonSelect" in ln]

    # IonInfiniteScroll pattern
    infinite_scroll_snippet = ""
    for i, ln in enumerate(lines):
        if "IonInfiniteScroll" in ln and "onIonInfinite" in ln:
            infinite_scroll_snippet = "\n".join(lines[i:i+5])
            break

    # IonToast / IonAlert error handling pattern
    toast_pattern = next((ln.strip() for ln in lines if "<IonToast" in ln), "")
    alert_pattern = next((ln.strip() for ln in lines if "<IonAlert" in ln), "")

    # Header component usage
    header_usage = next((ln.strip() for ln in lines if "<Header" in ln), "")

    # canAccess usage
    can_access = [ln.strip() for ln in lines if "canAccess" in ln]

    # Search / filter pattern
    searchbar = next((ln.strip() for ln in lines if "IonSearchbar" in ln), "")

    return {
        "file": filename,
        "ionic_components": ionic_components,
        "state_declarations": use_states[:8],
        "use_effects": use_effects[:4],
        "has_modal": has_modal,
        "modal_trigger_pattern": modal_trigger,
        "css_class_names": css_classes[:15],
        "api_calls": api_calls[:10],
        "ion_input_patterns": ion_inputs[:3],
        "ion_select_patterns": ion_selects[:2],
        "infinite_scroll_pattern": infinite_scroll_snippet,
        "toast_pattern": toast_pattern,
        "alert_pattern": alert_pattern,
        "header_usage": header_usage,
        "can_access_usage": can_access[:2],
        "searchbar_pattern": searchbar,
        "total_lines": len(lines),
    }


def _extract_css_patterns(source: str, filename: str) -> dict:
    """Extract CSS class naming conventions and structure from a CSS file."""
    # Extract class names and their first property
    classes = re.findall(r'\.([a-zA-Z][\w-]*)\s*\{([^}]*)\}', source, re.DOTALL)
    class_summary = []
    for cls, body in classes[:20]:
        props = [p.strip() for p in body.strip().splitlines() if p.strip()][:2]
        class_summary.append({"class": cls, "sample_props": props})

    # Detect naming prefix (e.g. "clients-", "expenses-")
    names = [c[0] for c in classes]
    prefix = ""
    if names:
        parts = names[0].split("-")
        if len(parts) > 1:
            prefix = parts[0] + "-"

    return {
        "file": filename,
        "naming_prefix": prefix,
        "class_count": len(classes),
        "classes": class_summary,
    }


def fetch_design_reference(tool_context: ToolContext) -> dict:
    """
    Fetches representative pages from the frontend GitHub repo and extracts
    design patterns. Stores results in session state under 'design_context'.

    Returns:
        dict with patterns extracted from each reference file.
    """
    repo = os.getenv("GITHUB_REPO_NAME", "")
    if "github.com/" in repo:
        repo = repo.split("github.com/", 1)[1].rstrip("/").removesuffix(".git")

    if not repo:
        return {"error": "GITHUB_REPO_NAME not set"}

    results: dict = {"repo": repo, "pages": [], "css": [], "summary": {}}

    with httpx.Client(timeout=60) as client:
        # Fetch TSX pages
        for path in _REFERENCE_PAGES:
            content = _fetch_file(client, repo, path)
            if content:
                patterns = _extract_patterns(content, path)
                results["pages"].append(patterns)

        # Fetch CSS files
        for path in _REFERENCE_CSS:
            content = _fetch_file(client, repo, path)
            if content:
                patterns = _extract_css_patterns(content, path)
                results["css"].append(patterns)

    if not results["pages"]:
        return {"error": f"Could not fetch any reference pages from {repo}"}

    # Build a cross-page summary
    all_ionic = set()
    all_api_calls = set()
    uses_header = False
    uses_infinite_scroll = False
    uses_modal = False

    for page in results["pages"]:
        all_ionic.update(page["ionic_components"])
        all_api_calls.update(page["api_calls"])
        if page["header_usage"]:
            uses_header = True
        if page["infinite_scroll_pattern"]:
            uses_infinite_scroll = True
        if page["has_modal"]:
            uses_modal = True

    results["summary"] = {
        "common_ionic_components": sorted(all_ionic),
        "common_api_patterns": sorted(all_api_calls),
        "uses_header_component": uses_header,
        "uses_infinite_scroll": uses_infinite_scroll,
        "uses_modal_pattern": uses_modal,
        "pages_analyzed": len(results["pages"]),
        "css_files_analyzed": len(results["css"]),
    }

    # Store in session state for Frontend Agent
    import json
    tool_context.state["design_context"] = json.dumps(results, default=str)
    return results


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
