"""
Frontend file layout — the single source of truth for WHERE a generated
POSVending module's files go and how they import each other.

Mirrors the MVVM feature layout the POSVending repo itself uses (its own
CLAUDE.md §1-2, and the newest real features: finance/Expenses,
finance/Accounting, admin/Employees):

    src/api/{module}Api.ts                       typed fetch client (unchanged)
    src/pages/{area}/{Module}Page.tsx            router shell — imports CSS + View only
    src/pages/{area}/{Module}/{Module}View.tsx   JSX only:  const vm = use{Module}()
    src/pages/{area}/{Module}/{Module}Logic.ts   hook: ALL state / effects / API calls
    src/pages/{area}/{Module}/{Module}.css       styles, imported by the shell

`area` is a lowercase folder under src/pages (products, finance, admin, …).
Every stage that names a frontend path — spec reconciler, prompts, fixer,
reviewer, review fixer, PR agent — derives it from here, so the paths can't
drift between stages.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent
_AREA_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# Relative prefix from a file inside src/pages/{area}/{Module}/ back to src/.
FEATURE_TO_SRC = "../../../"

# Artifact keys the frontend agent returns, in push order.
FILE_KEYS = ("api_file", "page_file", "view_file", "logic_file", "css_file")
CODE_KEYS = ("api_file", "page_file", "view_file", "logic_file")   # TS/TSX, no CSS


def pascal(module: str) -> str:
    return module[:1].upper() + module[1:]


def _load(rel: str) -> list:
    try:
        data = json.loads((_KNOWLEDGE_ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def known_areas() -> list[str]:
    """src/pages/{area} folders that exist in POSVending, from knowledge_sync's
    feature folders + the page components its routes point at."""
    areas = {f["area"] for f in _load("Frontend/frontend_features.json")
             if isinstance(f, dict) and f.get("area")}
    for r in _load("Frontend/frontend_routes.json.json"):
        parts = str((r or {}).get("component") or "").split("/")
        if len(parts) >= 4 and parts[:2] == ["src", "pages"] and not r.get("stale"):
            areas.add(parts[2])
    return sorted(a for a in areas if _AREA_RE.match(a))


def resolve_area(module: str, requested: str | None) -> str:
    """The architect's requested area when it's a valid folder name, else
    the module name lowercased (a new lowercase area folder)."""
    area = (requested or "").strip().strip("/").lower()
    return area if _AREA_RE.match(area) else module.lower()


def layout(module: str, area: str) -> dict[str, str]:
    """Every path + import line for one module."""
    M = pascal(module)
    feature_dir = f"src/pages/{area}/{M}"
    return {
        "area": area,
        "api_file": f"src/api/{module}Api.ts",
        "page_file": f"src/pages/{area}/{M}Page.tsx",
        "view_file": f"{feature_dir}/{M}View.tsx",
        "logic_file": f"{feature_dir}/{M}Logic.ts",
        "css_file": f"{feature_dir}/{M}.css",
        # import lines, as each file must write them
        "shell_css_import": f"import './{M}/{M}.css';",
        "shell_view_import": f"import {M}View from './{M}/{M}View';",
        "view_logic_import": f"import {{ use{M} }} from './{M}Logic';",
        "api_import_from_feature": f"from '{FEATURE_TO_SRC}api/{module}Api'",
        "header_import": f"import Header from '{FEATURE_TO_SRC}components/layout/Header';",
        "app_import_line": f"import {M}Page from './pages/{area}/{M}Page';",
        "hook_name": f"use{M}",
        "vm_type": f"{M}VM",
    }


def normalize_spec_frontend(spec: dict) -> tuple[dict, dict | None]:
    """Force spec["frontend"] paths to the MVVM layout. Deterministic.
    Returns (spec, change record or None when already correct)."""
    module = spec.get("module") or ""
    fe = spec.get("frontend")
    if not module or not isinstance(fe, dict):
        return spec, None
    area = resolve_area(module, fe.get("area"))
    want = layout(module, area)
    changed = {}
    for key in ("area", *FILE_KEYS):
        if fe.get(key) != want[key]:
            changed[key] = {"from": fe.get(key), "to": want[key]}
            fe[key] = want[key]
    return spec, (changed or None)
