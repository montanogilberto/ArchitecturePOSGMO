"""
Frontend API call edges, extracted from POSVending's src/api/*.ts files.

Line-scanning regex, not a real TypeScript parser — Python has no ast
equivalent for TS, and pulling in a full TS toolchain for this would be
exactly the kind of infrastructure-before-value tradeoff this whole
graph has avoided so far. This works because the actual code is
consistently shaped (verified against clientsApi.ts, incomeApi.ts,
rewardsApi.ts, expensesApi.ts, 2026-09-15): a top-level
"export const name = async (...) => { ... fetch(`${BASE}/path`, "
"{ method: 'X', ... }) ... }".

Real, stated limitation: this only resolves LITERAL path segments after
the interpolated base URL (`${API_BASE_URL}/clients` -> "/clients"). A
dynamically-built path (`${API_BASE_URL}/${pluralModule}` — see
posRewardsApi.ts's `crud()` helper) can't be resolved to a literal string
here; such calls are reported with path=None rather than a guessed value,
same "honest gap, not a wrong answer" posture as backend_routes.py.
"""
from __future__ import annotations

import os
import re

_EXPORT_FUNC_RE = re.compile(r"^export\s+(?:const|async function|function)\s+(\w+)")
_FETCH_LITERAL_RE = re.compile(r"fetch\(\s*`\$\{[^}]+\}(/[a-zA-Z0-9_\-./]*)`")
_FETCH_DYNAMIC_RE = re.compile(r"fetch\(\s*`\$\{[^}]+\}\$\{")
_METHOD_RE = re.compile(r"method:\s*['\"](\w+)['\"]")
_LOOKAHEAD_LINES = 12  # how far past a fetch( call to search for its method: 'X'


def extract_frontend_edges(file_path: str) -> list[dict]:
    """One src/api/*.ts file -> the fetch() calls inside its exported
    functions.

    Returns:
        List of {"frontend_func", "path", "method", "source_file"}.
        "path" is None for a dynamically-built endpoint (see module
        docstring) — still returned, so a caller can see the call exists
        even though its target can't be statically resolved.
    """
    lines = open(file_path, encoding="utf-8").read().splitlines()
    edges = []
    current_func = None

    for i, line in enumerate(lines):
        export_match = _EXPORT_FUNC_RE.match(line.strip())
        if export_match:
            current_func = export_match.group(1)

        if _FETCH_DYNAMIC_RE.search(line):
            method = _look_ahead_method(lines, i)
            edges.append({
                "frontend_func": current_func, "path": None, "method": method,
                "source_file": os.path.basename(file_path),
                # Confidence is derived, not asserted: a dynamic path is an
                # honest gap (see module docstring), never labeled VERIFIED.
                "confidence": "UNKNOWN",
            })
            continue

        literal_match = _FETCH_LITERAL_RE.search(line)
        if literal_match:
            method = _look_ahead_method(lines, i)
            edges.append({
                "frontend_func": current_func, "path": literal_match.group(1),
                "method": method, "source_file": os.path.basename(file_path),
                "confidence": "VERIFIED",
            })

    return edges


def _look_ahead_method(lines: list[str], from_index: int) -> str:
    for j in range(from_index, min(from_index + _LOOKAHEAD_LINES, len(lines))):
        m = _METHOD_RE.search(lines[j])
        if m:
            return m.group(1).upper()
    return "GET"  # fetch()'s own default when no method is specified


def extract_frontend_edges_for_modules(frontend_repo_path: str, api_files: list[str]) -> list[dict]:
    """Scans specific src/api/*.ts files by basename.

    Args:
        frontend_repo_path: Absolute path to the POSVending checkout.
        api_files: Basenames to scan, e.g. ["clientsApi.ts", "incomeApi.ts"].

    Returns:
        Combined edge list across all requested files.
    """
    api_dir = os.path.join(frontend_repo_path, "src", "api")
    edges = []
    for name in api_files:
        path = os.path.join(api_dir, name)
        if os.path.isfile(path):
            edges.extend(extract_frontend_edges(path))
    return edges
