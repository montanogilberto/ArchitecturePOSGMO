"""
Runs the extractors, merges their output into the knowledge files the MCP
server reads, and writes a drift report.

Merge rules (curated knowledge is never lost):
  * matched entry   → extracted fields refreshed, curated fields kept
  * new entry       → added with "source": "knowledge_sync"
  * vanished entry  → kept with "stale": true (MCP getters filter these out)
  * failed source   → its knowledge file is left untouched, failure reported
Live-DB files (schema CSV, relationships) are replaced outright: the live
database is the authority for them.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from knowledge_sync import conventions, extractors
from knowledge_sync.config import FACTORY_ROOT, KNOWLEDGE_ROOT, repo_paths

SCANNER_VERSION = "knowledge_sync/1.0.0"

FILES = {
    "backend_routes": "Backend/backend_routes.json.json",
    "stored_procedures": "Backend/backend_stored_procedures.json.json",
    "schema_csv": "Database/structure_database.csv",
    "relationships": "Database/sql_relationships.json",
    "frontend_routes": "Frontend/frontend_routes.json.json",
    "components": "Frontend/frontend_components.json.json",
    "api_clients": "Frontend/frontend_api_clients.json",
    "features": "Frontend/frontend_features.json",
    "agents": "Agents/agents_catalog.json",
    "conventions": "Conventions/repo_conventions.json",
}
MANIFEST = FACTORY_ROOT / "knowledge_sync" / "manifest.json"
REPORT = FACTORY_ROOT / "knowledge_sync" / "last_report.md"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_json(rel: str, default):
    p = KNOWLEDGE_ROOT / rel
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def _dump(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def merge(existing: list[dict], extracted: list[dict], key: str,
          refresh: tuple[str, ...], rename_key: str | None = None,
          covered=None) -> tuple[list[dict], dict]:
    """Merge `extracted` into `existing` by `key`. Only fields in `refresh`
    are overwritten on matched entries; everything else on them is curated.

    rename_key: an old entry whose `key` vanished but whose `rename_key`
        matches exactly one unclaimed extracted entry is treated as MOVED
        (e.g. a component relocated to a subfolder) — `key` is updated and
        curated fields survive.
    covered(old_entry, found) -> bool: an old entry not found by key but
        still represented (e.g. a router prefix whose full paths were found)
        is kept as-is instead of going stale.

    Returns (merged list, {"added", "stale", "revived", "moved"})."""
    found = {e[key]: e for e in extracted}
    by_rename: dict = {}
    if rename_key:
        for e in extracted:
            by_rename.setdefault(e.get(rename_key), []).append(e[key])
    existing_keys = {o.get(key) for o in existing}
    merged, seen = [], set()
    diff = {"added": [], "stale": [], "revived": [], "moved": []}
    for old in existing:
        k = old.get(key)
        if k in seen:
            continue
        seen.add(k)
        new = dict(old)
        if k not in found and rename_key:
            cands = [c for c in by_rename.get(old.get(rename_key), [])
                     if c not in existing_keys and c not in seen]
            if len(cands) == 1:
                diff["moved"].append(f"{k} → {cands[0]}")
                k = new[key] = cands[0]
                seen.add(k)
        if k in found:
            for f in refresh:
                if f in found[k]:
                    new[f] = found[k][f]
            if new.pop("stale", None):
                diff["revived"].append(k)
        elif covered and covered(old, found):
            new.pop("stale", None)
        else:
            if not old.get("stale"):
                diff["stale"].append(k)
            new["stale"] = True
        merged.append(new)
    for k, e in found.items():
        if k not in seen:
            merged.append({**e, "source": "knowledge_sync"})
            diff["added"].append(k)
    return merged, diff


def _active(entries: list[dict]) -> int:
    return sum(1 for e in entries if not e.get("stale"))


# ---------------------------------------------------------------------------
# per-file builders: each returns (new content as text, summary dict)
# ---------------------------------------------------------------------------

def _build_backend_routes(paths):
    old = _read_json(FILES["backend_routes"], {"routes": []})
    old_routes = old.get("routes", []) if isinstance(old, dict) else old
    # The hand-written file held one placeholder per router file ("/tickets"
    # → routes_/tickets.py) or a router prefix ("/stripe"). Those stay alive
    # while their file / any path under them still exists, and their curated
    # tags carry over to the real paths extracted from the same file.
    extracted = extractors.backend_routes(paths["backend"])
    curated_tags = {r["file"]: r["tags"] for r in old_routes if r.get("tags") and r.get("file")}
    for r in extracted:
        if r["tags"] == [Path(r["file"]).stem] and r["file"] in curated_tags:
            r["tags"] = curated_tags[r["file"]]
    live_files = {r["file"] for r in extracted}
    routes, diff = merge(
        old_routes, extracted, "path", refresh=("file", "methods", "handlers"),
        covered=lambda old, found: old.get("file") in live_files
        or any(p.startswith(old["path"].rstrip("/") + "/") for p in found))
    return _dump({**(old if isinstance(old, dict) else {}), "routes": routes}), \
        {"before": _active(old_routes), "after": _active(routes), **diff}


def _build_sps(paths, live):
    old = _read_json(FILES["stored_procedures"], {"stored_procedures": []})
    old_sps = old.get("stored_procedures", []) if isinstance(old, dict) else old
    bindings = extractors.sp_module_bindings(paths["backend"])
    extracted = [{"name": n, "module_binding": bindings.get(n), "parameters": params}
                 for n, params in sorted(live["procedures"].items())]
    sps, diff = merge(old_sps, extracted, "name", refresh=("parameters",))
    for sp in sps:  # a module binding found in code beats a missing one
        if not sp.get("module_binding") and bindings.get(sp["name"]):
            sp["module_binding"] = bindings[sp["name"]]
    return _dump({**(old if isinstance(old, dict) else {}), "stored_procedures": sps}), \
        {"before": _active(old_sps), "after": _active(sps), **diff}


def _build_schema_csv(live):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(live["columns"])
    old_path = KNOWLEDGE_ROOT / FILES["schema_csv"]
    old_tables = set()
    if old_path.is_file():
        with open(old_path, encoding="utf-8-sig") as f:
            old_tables = {r[1].lower() for r in csv.reader(f) if len(r) > 1}
    new_tables = {r[1].lower() for r in live["columns"]}  # SQL Server names are case-insensitive
    return buf.getvalue(), {"before": len(old_tables), "after": len(new_tables),
                            "added": sorted(new_tables - old_tables),
                            "stale": sorted(old_tables - new_tables), "revived": [],
                            "columns": len(live["columns"])}


def _build_relationships(live):
    old = _read_json(FILES["relationships"], [])
    key = lambda r: (r.get("parent_table"), r.get("child_table"), r.get("fk_constraint_name"))  # noqa: E731
    old_keys, new_keys = {key(r) for r in old}, {key(r) for r in live["relationships"]}
    return _dump(live["relationships"]), {
        "before": len(old), "after": len(live["relationships"]),
        "added": [f"{p}→{c}" for p, c, _ in sorted(new_keys - old_keys)],
        "stale": [f"{p}→{c}" for p, c, _ in sorted(old_keys - new_keys)], "revived": []}


def _build_frontend_routes(paths):
    old = _read_json(FILES["frontend_routes"], [])
    routes, diff = merge(old, extractors.frontend_routes(paths["frontend"]), "path",
                         refresh=("component", "authenticated", "feature"))
    return _dump(routes), {"before": _active(old), "after": _active(routes), **diff}


def _build_components(paths):
    old = _read_json(FILES["components"], [])
    extracted = extractors.frontend_components(paths["frontend"])
    for c in extracted:  # defaults for new entries only — merge keeps curated ones
        c.setdefault("type", "ui" if c["folder"].startswith("ui") else (c["folder"] or "shared"))
        c.setdefault("reusable", c["folder"] in ("", "ui") or c["folder"].startswith("ui"))
    comps, diff = merge(old, extracted, "filePath", refresh=("componentName", "folder"),
                        rename_key="componentName")
    for c in comps:  # scanned props fill in when nothing curated exists
        if not c.get("props"):
            match = next((e for e in extracted if e["filePath"] == c["filePath"]), None)
            if match:
                c["props"] = match["props"]
    return _dump(comps), {"before": _active(old), "after": _active(comps), **diff}


def _build_generated(rel_key, data, ident):
    old = _read_json(FILES[rel_key], [])
    old_ids = {ident(e) for e in old} if isinstance(old, list) else set()
    new_ids = {ident(e) for e in data}
    return _dump(data), {"before": len(old_ids), "after": len(new_ids),
                         "added": sorted(new_ids - old_ids), "stale": sorted(old_ids - new_ids),
                         "revived": []}


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def sync_knowledge(check_only: bool = False, verbose: bool = True) -> dict:
    """Refresh every knowledge file from the real repos + live DB.
    Returns the report dict; writes nothing when check_only."""
    paths = repo_paths()
    report = {"scanner": SCANNER_VERSION, "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "repos": {k: {"path": str(p), **conventions.git_info(p)} for k, p in paths.items()},
              "files": {}, "errors": {}, "written": []}
    missing = [k for k, p in paths.items() if not p.is_dir()]
    for k in missing:
        report["errors"][f"repo:{k}"] = f"not found at {paths[k]} (set the env var in .env)"

    outputs: dict[str, str] = {}

    def attempt(name, fn, needs=()):
        if any(n in missing for n in needs):
            report["errors"][name] = "skipped: repo missing"
            return
        try:
            text, summary = fn()
            outputs[name] = text
            report["files"][name] = summary
        except Exception as e:  # noqa: BLE001 -- one bad source must not block the rest
            report["errors"][name] = f"{type(e).__name__}: {str(e)[:200]}"

    attempt("backend_routes", lambda: _build_backend_routes(paths), ("backend",))

    try:
        live = extractors.live_database()
    except Exception as e:  # noqa: BLE001
        live = None
        report["errors"]["live_database"] = f"{type(e).__name__}: {str(e)[:200]} — schema/SP files kept as-is"
    if live:
        attempt("stored_procedures", lambda: _build_sps(paths, live), ("backend",))
        attempt("schema_csv", lambda: _build_schema_csv(live))
        attempt("relationships", lambda: _build_relationships(live))

    attempt("frontend_routes", lambda: _build_frontend_routes(paths), ("frontend",))
    attempt("components", lambda: _build_components(paths), ("frontend",))
    attempt("api_clients", lambda: _build_generated(
        "api_clients", extractors.frontend_api_clients(paths["frontend"]), lambda e: e["file"]), ("frontend",))
    attempt("features", lambda: _build_generated(
        "features", extractors.frontend_features(paths["frontend"]), lambda e: e["folder"]), ("frontend",))
    attempt("agents", lambda: _build_generated(
        "agents", extractors.agents_catalog(paths["agents"]), lambda e: e["folder"]), ("agents",))
    attempt("conventions", lambda: (_dump(conventions.repo_conventions(paths)),
                                    {"before": None, "after": None, "added": [], "stale": [], "revived": []}),
            ("frontend", "backend", "agents"))

    if not check_only:
        for name, text in outputs.items():
            target = KNOWLEDGE_ROOT / FILES[name]
            current = target.read_text(encoding="utf-8-sig") if target.is_file() else None
            if current != text:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                report["written"].append(FILES[name])
        if report["written"]:
            MANIFEST.write_text(_dump({k: report[k] for k in ("scanner", "ranAt", "repos", "written")}),
                                encoding="utf-8")
        REPORT.write_text(render_report(report), encoding="utf-8")

    if verbose:
        print(render_summary(report, check_only), flush=True)
    return report


def run_before_factory() -> None:
    """Best-effort hook for orchestrator.run_factory — never blocks a run."""
    if os.getenv("FACTORY_SKIP_KNOWLEDGE_SYNC", "").lower() in ("1", "true", "yes"):
        print("[knowledge_sync] skipped (FACTORY_SKIP_KNOWLEDGE_SYNC)", flush=True)
        return
    try:
        sync_knowledge(verbose=True)
    except Exception as e:  # noqa: BLE001
        print(f"[knowledge_sync] failed, continuing with existing knowledge: {e}", flush=True)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def render_summary(report: dict, check_only: bool = False) -> str:
    parts = []
    for name, s in report["files"].items():
        if s.get("after") is None:
            continue
        delta = f"+{len(s['added'])}" + (f" moved {len(s['moved'])}" if s.get("moved") else "") \
            + (f" stale {len(s['stale'])}" if s["stale"] else "")
        parts.append(f"{name} {s['before']}→{s['after']} ({delta})")
    head = "[knowledge_sync] " + ("CHECK " if check_only else "")
    tail = f" | wrote {len(report['written'])} file(s)" if not check_only else ""
    errs = f" | errors: {', '.join(report['errors'])}" if report["errors"] else ""
    return head + "; ".join(parts) + tail + errs


def render_report(report: dict) -> str:
    lines = [f"# Knowledge sync report — {report['ranAt']}", "",
             f"Scanner `{report['scanner']}`.", "", "## Repositories", "",
             "| Repo | Branch | Commit | Commit date |", "|---|---|---|---|"]
    for k, r in report["repos"].items():
        lines.append(f"| {k} | {r.get('branch')} | {r.get('commit')} | {r.get('commitDate')} |")
    lines += ["", "## Drift", "", "| Knowledge | Before | After | Added | Moved | Stale | Revived |",
              "|---|---|---|---|---|---|---|"]
    for name, s in report["files"].items():
        if s.get("after") is None:
            continue
        lines.append(f"| {FILES[name]} | {s['before']} | {s['after']} | {len(s['added'])} | "
                     f"{len(s.get('moved', []))} | {len(s['stale'])} | {len(s['revived'])} |")
    for name, s in report["files"].items():
        if s.get("added") or s.get("stale"):
            lines += ["", f"### {FILES[name]}"]
            if s["added"]:
                lines.append(f"- **Added ({len(s['added'])}):** " + ", ".join(f"`{a}`" for a in s["added"][:40])
                             + (" …" if len(s["added"]) > 40 else ""))
            if s.get("moved"):
                lines.append(f"- **Moved ({len(s['moved'])}):** " + ", ".join(f"`{a}`" for a in s["moved"][:40]))
            if s["stale"]:
                lines.append(f"- **Stale ({len(s['stale'])}):** " + ", ".join(f"`{a}`" for a in s["stale"][:40])
                             + (" …" if len(s["stale"]) > 40 else ""))
    if report["errors"]:
        lines += ["", "## Errors", ""] + [f"- **{k}:** {v}" for k, v in report["errors"].items()]
    lines += ["", "## Written", ""] + ([f"- `{w}`" for w in report["written"]] or ["- nothing changed"])
    return "\n".join(lines) + "\n"
