"""
GMO Ecosystem Graph — combines the three extraction layers
(sql_dependencies, backend_routes, frontend_calls) into one edge list and
a reverse-lookup traversal: "what breaks if I change X".

Scope discipline (see ecosystem_graph/__init__.py): MODULES_IN_SCOPE below
lists only the modules already deeply verified elsewhere this session.
Extending coverage to the rest of the ~270 backend routes is real,
valuable future work — but each addition should be spot-checked the same
way clients/income/expenses/rewards were (compare extracted edges against
what you already know is true), not bulk-generated and trusted.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ecosystem_graph.backend_routes import extract_backend_edges, resolve_route_to_sp
from ecosystem_graph.frontend_calls import extract_frontend_edges_for_modules
from ecosystem_graph.sql_dependencies import get_sp_table_dependencies

# Bumped when the extraction logic itself changes meaningfully (new layer,
# changed confidence rules) -- lets a stored/exported graph say which
# version of this code produced it, per the versioning requirement that a
# graph must know "this describes the repos as of commit X, scanned by
# scanner version Y".
SCANNER_VERSION = "ecosystem_graph/0.2.0"


def _git_info(repo_path: str) -> dict:
    """Best-effort git metadata for one repo checkout: commit SHA + branch.

    Returns None for a field (never raises) if the path isn't a git repo,
    git isn't on PATH, or the command times out -- a graph should still
    build from a repo with no git metadata, just without version-awareness
    for that one source, rather than fail outright.
    """
    info: dict = {"commit": None, "branch": None}
    commands = {
        "commit": ["rev-parse", "HEAD"],
        "branch": ["rev-parse", "--abbrev-ref", "HEAD"],
    }
    for key, args in commands.items():
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, *args],
                capture_output=True, text=True, timeout=5, check=True,
            )
            info[key] = result.stdout.strip()
        except Exception:
            pass
    return info

# module basename -> its frontend src/api/*.ts file(s). One module can map
# to several API files (income has both incomeApi.ts and an action-only
# variant) or a differently-named file (rewards' REAL frontend caller is
# rewardsApi.ts, not "rewards.ts" — kept explicit here rather than guessed
# from the module name, since that guess would be wrong for several of
# these).
MODULES_IN_SCOPE: dict[str, list[str]] = {
    "clients": ["clientsApi.ts"],
    "income": ["incomeApi.ts"],
    "expenses": ["expensesApi.ts"],
    "rewards": ["rewardsApi.ts"],
}


@dataclass
class EcosystemNode:
    kind: str  # "frontend_call" | "backend_route" | "stored_procedure" | "table"
    identifier: str  # e.g. "clientsApi.ts:createOrUpdateClient", "POST /clients", "sp_clients", "clients"
    detail: dict = field(default_factory=dict)


@dataclass
class EcosystemGraph:
    frontend_to_route: list[dict]  # [{"frontend_node", "path", "method"}]
    route_to_sp: list[dict]        # [{"path", "method", "stored_procedures", ...}]
    sp_to_table: list[dict]        # [{"procedure", "table"}]
    # Version-awareness (step 11): which commit of each source repo this
    # graph was built from, and when. {} / "" for a graph built without
    # build_graph() (e.g. the synthetic fixtures in this module's own
    # tests) -- callers that care about staleness should treat missing
    # source info as "unknown provenance", not "repo unchanged".
    sources: dict = field(default_factory=dict)
    scanner_version: str = SCANNER_VERSION
    scanned_at: str = ""


def build_graph(
    backend_repo_path: str,
    frontend_repo_path: str,
    modules_in_scope: dict[str, list[str]] | None = None,
) -> EcosystemGraph:
    """Builds the full ecosystem graph for the given module scope.

    Args:
        backend_repo_path: Absolute path to smartloans_backend.
        frontend_repo_path: Absolute path to POSVending.
        modules_in_scope: module -> [api ts filenames]; defaults to
            MODULES_IN_SCOPE. Pass a narrower dict to build/verify just
            one module at a time while extending coverage.

    Returns:
        EcosystemGraph with all three edge layers, already resolved
        against real source and live DB — not raw extraction output.
    """
    scope = modules_in_scope if modules_in_scope is not None else MODULES_IN_SCOPE
    module_names = list(scope.keys())

    scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sources = {
        "backend": {"path": backend_repo_path, **_git_info(backend_repo_path)},
        "frontend": {"path": frontend_repo_path, **_git_info(frontend_repo_path)},
    }

    backend_extraction = extract_backend_edges(backend_repo_path, modules_in_scope=module_names)
    route_to_sp = resolve_route_to_sp(backend_extraction)

    all_sp_names = sorted({sp for r in route_to_sp for sp in r["stored_procedures"]})
    sp_to_table = get_sp_table_dependencies(all_sp_names) if all_sp_names else []

    frontend_to_route = []
    for module, api_files in scope.items():
        edges = extract_frontend_edges_for_modules(frontend_repo_path, api_files)
        for e in edges:
            frontend_to_route.append({
                "frontend_node": f"{e['source_file']}:{e['frontend_func'] or '?'}",
                "path": e["path"], "method": e["method"], "module": module,
            })

    return EcosystemGraph(
        frontend_to_route=frontend_to_route,
        route_to_sp=route_to_sp,
        sp_to_table=sp_to_table,
        sources=sources,
        scanned_at=scanned_at,
    )


def what_breaks_if_changed(graph: EcosystemGraph, node_kind: str, identifier: str) -> dict:
    """Reverse-lookup: given a changed node, what upstream things call it
    (and, for a table, what's downstream doesn't apply — tables are leaves
    in this graph's direction; a table change's blast radius is "every SP
    in sp_to_table naming this table", which this also returns).

    Args:
        node_kind: "table", "stored_procedure", or "route" (identifier
            format "METHOD /path" for a route).
        identifier: The table name, SP name, or "METHOD /path" string.

    Returns:
        {"directly_affects": [...], "transitively_affects": [...]} —
        human-readable strings naming the real affected nodes, empty
        lists (not an error) if this node has no known callers in the
        current MODULES_IN_SCOPE coverage. An empty result does NOT mean
        nothing depends on it — it means nothing in scope has been
        extracted yet; say that plainly rather than implying safety.
    """
    direct: list[str] = []
    transitive: list[str] = []

    if node_kind == "table":
        procs = sorted({d["procedure"] for d in graph.sp_to_table if d["table"] == identifier})
        direct = [f"stored procedure {p}" for p in procs]
        for p in procs:
            routes = [r for r in graph.route_to_sp if p in r["stored_procedures"]]
            for r in routes:
                transitive.append(f"route {r['method']} {r['path']}")
                fe = [f for f in graph.frontend_to_route if f["path"] == r["path"] and f["method"] == r["method"]]
                transitive.extend(f"frontend call {f['frontend_node']}" for f in fe)

    elif node_kind == "stored_procedure":
        routes = [r for r in graph.route_to_sp if identifier in r["stored_procedures"]]
        direct = [f"route {r['method']} {r['path']}" for r in routes]
        for r in routes:
            fe = [f for f in graph.frontend_to_route if f["path"] == r["path"] and f["method"] == r["method"]]
            transitive.extend(f"frontend call {f['frontend_node']}" for f in fe)

    elif node_kind == "route":
        method, _, path = identifier.partition(" ")
        fe = [f for f in graph.frontend_to_route if f["path"] == path and f["method"] == method.upper()]
        direct = [f"frontend call {f['frontend_node']}" for f in fe]

    return {"directly_affects": sorted(set(direct)), "transitively_affects": sorted(set(transitive))}
