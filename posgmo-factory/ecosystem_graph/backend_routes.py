"""
Route -> handler -> stored-procedure edges, extracted from
smartloans_backend's real source via Python's `ast` module — not regex
over the whole file, which can't reliably scope "which EXEC call belongs
to which function" the way a real parse tree can.

Two extraction passes, mirroring the repo's own documented layering
(routes_/ = ingress only, modules/ = business logic that calls the SP):
    1. routes_/{module}.py -> which route path/method delegates to which
       module-level function (e.g. POST /clients -> clients_sp).
    2. modules/{module}.py -> which stored procedure each function
       actually EXECs (e.g. clients_sp -> sp_clients).
Combining both gives route -> SP, without ever running the backend code.
"""
from __future__ import annotations

import ast
import os
import re

_SP_NAME_RE = re.compile(r"EXEC\s+(?:\[dbo\]\.)?\[?(\w+)\]?", re.IGNORECASE)
_HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def _extract_routes_from_file(file_path: str) -> list[dict]:
    """One routes_/*.py file -> its @router.<method>(...) definitions."""
    tree = ast.parse(open(file_path, encoding="utf-8").read(), filename=file_path)
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in _HTTP_METHODS):
                continue
            path = None
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                path = dec.args[0].value
            # Every plain function call by name inside the handler body --
            # deliberately broad (catches "return clients_sp(json)" and
            # similar shapes) rather than trying to prove it's the ONE
            # real delegate; extract_backend_edges() resolves against
            # real sp_calls afterward, so an over-broad guess here just
            # fails to resolve rather than producing a wrong edge.
            delegates = sorted({
                n.func.id for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            })
            routes.append({
                "path": path, "method": dec.func.attr.upper(),
                "handler_func": node.name, "delegates_to": delegates,
                "source_file": os.path.basename(file_path),
            })
    return routes


def _extract_function_info_from_file(file_path: str) -> dict[str, dict]:
    """One modules/*.py file -> {function_name: {"sp_names": [...],
    "calls": [...]}} — "sp_names" are real SPs EXECed directly in that
    function's own body; "calls" are other local function names it
    invokes (e.g. rewards_sp calling the private _sp() helper that does
    the actual EXEC). Kept separate, not pre-merged, because a function
    can indirect through several private helpers (see resolve_route_to_sp's
    BFS) and collapsing here would lose that structure."""
    tree = ast.parse(open(file_path, encoding="utf-8").read(), filename=file_path)
    result: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        sp_names: set[str] = set()
        calls: set[str] = set()
        for n2 in ast.walk(node):
            if isinstance(n2, ast.Constant) and isinstance(n2.value, str):
                sp_names.update(_SP_NAME_RE.findall(n2.value))
            elif isinstance(n2, ast.Call) and isinstance(n2.func, ast.Name) and n2.func.id != node.name:
                calls.add(n2.func.id)
        if sp_names or calls:
            result[node.name] = {"sp_names": sorted(sp_names), "calls": sorted(calls)}
    return result


def extract_backend_edges(backend_repo_path: str, modules_in_scope: list[str] | None = None) -> dict:
    """Scans smartloans_backend's routes_/ and modules/ folders.

    Args:
        backend_repo_path: Absolute path to the smartloans_backend checkout.
        modules_in_scope: Module basenames (without .py) to scan, e.g.
            ["clients", "income", "expenses", "rewards"] — matches both
            routes_/{name}.py and modules/{name}.py. None scans every .py
            file in both folders (expensive, 272+ routes worth — prefer
            an explicit scope).

    Returns:
        {"routes": [...], "sp_calls": {func_name: [sp_names]}} — raw
        extraction output; see resolve_route_to_sp() to combine them into
        final route -> SP edges.
    """
    routes_dir = os.path.join(backend_repo_path, "routes_")
    modules_dir = os.path.join(backend_repo_path, "modules")

    if modules_in_scope:
        route_files = [os.path.join(routes_dir, f"{m}.py") for m in modules_in_scope]
        module_files = [os.path.join(modules_dir, f"{m}.py") for m in modules_in_scope]
    else:
        route_files = [os.path.join(routes_dir, f) for f in os.listdir(routes_dir) if f.endswith(".py")]
        module_files = [os.path.join(modules_dir, f) for f in os.listdir(modules_dir) if f.endswith(".py")]

    all_routes = []
    for f in route_files:
        if os.path.isfile(f):
            all_routes.extend(_extract_routes_from_file(f))

    function_info: dict[str, dict] = {}
    for f in module_files:
        if os.path.isfile(f):
            function_info.update(_extract_function_info_from_file(f))

    return {"routes": all_routes, "function_info": function_info}


def _reachable_sp_names(start_functions: list[str], function_info: dict[str, dict], max_hops: int = 4) -> set[str]:
    """BFS through the local call graph (function -> functions it calls)
    to find every SP EXECed anywhere in the chain — handles indirection
    through a shared private helper (e.g. rewards_sp -> _sp -> EXEC
    sp_rewards) that a single-hop lookup misses. max_hops bounds it
    against an accidental cycle; the real call chains here are 1-2 hops
    deep, 4 is generous headroom, not a tuned value."""
    sp_names: set[str] = set()
    visited: set[str] = set()
    frontier = list(start_functions)
    hops = 0
    while frontier and hops < max_hops:
        next_frontier = []
        for func_name in frontier:
            if func_name in visited:
                continue
            visited.add(func_name)
            info = function_info.get(func_name)
            if not info:
                continue
            sp_names.update(info["sp_names"])
            next_frontier.extend(c for c in info["calls"] if c not in visited)
        frontier = next_frontier
        hops += 1
    return sp_names


def resolve_route_to_sp(extraction: dict) -> list[dict]:
    """Combines extract_backend_edges()'s two passes into final
    route -> stored-procedure edges, following indirection through
    private helper functions (see _reachable_sp_names).

    Returns:
        List of {"path", "method", "handler_func", "stored_procedures",
        "source_file"} — "stored_procedures" is [] for a route whose
        delegate chain genuinely resolves to nothing in scope (e.g. it
        delegates to a function in a module outside modules_in_scope, or
        does something with no SP at all, like an Azure Blob upload) —
        an honest empty list, not a guess.
    """
    function_info = extraction["function_info"]
    resolved = []
    for route in extraction["routes"]:
        sps = _reachable_sp_names(route["delegates_to"], function_info)
        resolved.append({
            "path": route["path"], "method": route["method"],
            "handler_func": route["handler_func"],
            "stored_procedures": sorted(sps),
            "source_file": route["source_file"],
            # A route resolving to no SP in scope is an honest gap (see
            # module docstring) -- distinct from a route that genuinely
            # calls nothing (e.g. a pure Blob upload), which this layer
            # cannot yet tell apart. UNKNOWN covers both until that's
            # disambiguated.
            "confidence": "VERIFIED" if sps else "UNKNOWN",
        })
    return resolved
