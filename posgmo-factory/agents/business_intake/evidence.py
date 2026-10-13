"""
Deterministic evidence for the Business Intake analysis — zero LLM calls.

The analyst must decide REUSE / EXTEND / INVESTIGATE / CREATE / NOT APPLICABLE
from implementation evidence, not from names. This module builds that evidence:

  * candidate modules     — Product/GMO_MODULES.md entries matching the request
                            (a catalog entry is a CANDIDATE, never proof)
  * implementation check  — every route, stored procedure, table and frontend
                            file in a candidate's wiring is verified against the
                            repository knowledge (Backend/*.json, the schema
                            snapshot, ecosystem_graph's verified frontend files);
                            each candidate gets an evidenceLevel
  * dependencies          — real columns (NOT NULL marked) and FK neighbours of
                            the candidate's tables (domain ownership, e.g. a
                            required loanId ties a table to loans)
  * draft designs         — tests/prd_*.json descriptions and fields
  * repository inventory  — every backend route, stored procedure and table name,
                            so hidden implementations can be found (no "sale"
                            table, but income / tickets / cashRegister exist)
  * factory_experience    — optional (costs an embedding call; off by default)
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from debate_v2.context_graph import _STRUCTURE_CSV, load_schema_tables, neighbors_of

from agents.business_intake.modules import Module, load_modules, match_modules

_FACTORY_ROOT = Path(__file__).resolve().parent.parent.parent   # posgmo-factory/
_KNOWLEDGE_ROOT = _FACTORY_ROOT.parent                            # Agent_POSGMO/
_MAX_TABLES = 10
_MAX_COLUMNS = 30


@lru_cache(maxsize=1)
def _columns_by_table() -> Dict[str, List[str]]:
    columns: Dict[str, List[str]] = {}
    if not _STRUCTURE_CSV.exists():
        return columns
    with open(_STRUCTURE_CSV, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 4 and row[1] and row[2]:
                # row: schema, table, column, type, length, nullable, pk, fk
                required = len(row) > 5 and row[5].strip().upper() == "NO"
                columns.setdefault(row[1], []).append(f"{row[2]} {row[3]}{' NOT NULL' if required else ''}")
    return columns


@lru_cache(maxsize=1)
def backend_routes() -> List[str]:
    path = _KNOWLEDGE_ROOT / "Backend" / "backend_routes.json.json"
    try:
        return [r["path"] for r in json.loads(path.read_text(encoding="utf-8"))["routes"]]
    except Exception:
        return []


@lru_cache(maxsize=1)
def stored_procedures() -> List[str]:
    path = _KNOWLEDGE_ROOT / "Backend" / "backend_stored_procedures.json.json"
    try:
        return [p["name"] for p in json.loads(path.read_text(encoding="utf-8"))["stored_procedures"]]
    except Exception:
        return []


@lru_cache(maxsize=1)
def verified_frontend_files() -> List[str]:
    try:
        from ecosystem_graph.graph import MODULES_IN_SCOPE
        return sorted({f for files in MODULES_IN_SCOPE.values() for f in files})
    except Exception:
        return []


def _verify_wiring(module: Module) -> dict:
    """Which parts of a candidate's documented wiring exist in the repository knowledge."""
    wiring = " ".join(module.wiring.values())
    routes = set(backend_routes())
    sps = set(stored_procedures())
    tables = load_schema_tables()
    frontend = set(verified_frontend_files())

    claimed_routes = set(re.findall(r"(/[A-Za-z_][\w\-/]*)", module.wiring.get("backend", "")))
    claimed_sps = set(re.findall(r"\bsp_\w+", wiring))
    claimed_tables = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", module.wiring.get("database", "")) if w in tables}
    claimed_frontend = set(re.findall(r"\b\w+\.tsx?\b", module.wiring.get("frontend", "")))

    verified = {
        "routes": sorted(claimed_routes & routes),
        "storedProcedures": sorted(claimed_sps & sps),
        "tables": sorted(claimed_tables),
        "frontend": sorted(claimed_frontend & frontend),
    }
    unverified = sorted((claimed_routes - routes) | (claimed_sps - sps) | (claimed_frontend - frontend))
    has_code = bool(verified["routes"] or verified["storedProcedures"] or verified["frontend"])
    level = ("implementation-verified" if has_code and verified["tables"]
             else "partially-verified" if has_code or verified["tables"]
             else "agent-endpoint-documented" if module.kind == "agent" and "not documented" not in module.wiring.get("agents", "not documented")
             else "catalog-only")
    return {"verified": verified, "unverifiedClaims": unverified, "evidenceLevel": level}


def _status(text: str) -> str:
    """'available — note' / 'partial' / 'missing' from GMO_MODULES.md → AVAILABLE / PARTIAL / MISSING."""
    word = (text or "").strip().split(" ", 1)[0].lower().strip(".,;:—-")
    return {"available": "AVAILABLE", "partial": "PARTIAL", "missing": "MISSING"}.get(word, "UNKNOWN")


def _layer_readiness(module: Module, check: dict) -> dict:
    """Can a company use this capability today, per layer? Derived from evidence only;
    UNKNOWN whenever nothing confirms it (never assumed AVAILABLE)."""
    v = check["verified"]
    frontend_note = "API client found in the app; screens not verified" if v["frontend"] else ""
    readiness = {
        "mobile": _status(module.registry.get("mobile", "")),
        "web": _status(module.registry.get("web", "")),
        "backend": "AVAILABLE" if (v["routes"] or v["storedProcedures"]) else "UNKNOWN",
        "database": "AVAILABLE" if v["tables"] else "UNKNOWN",
    }
    for layer in ("mobile", "web"):
        if readiness[layer] == "UNKNOWN" and v["frontend"]:
            readiness[layer] = "PARTIAL"
    if module.kind == "agent":
        documented = "not documented" not in module.wiring.get("agents", "not documented")
        readiness["agent"] = "AVAILABLE" if documented else "UNKNOWN"
    readiness["configuration"] = module.registry.get("configuration", "not documented")
    if frontend_note:
        readiness["note"] = frontend_note
    return readiness


def _draft_designs(module: Module) -> List[dict]:
    tests_dir = _FACTORY_ROOT / "tests"
    designs = []
    for path in sorted(tests_dir.glob(f"prd_{module.id}*.json")) if tests_dir.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        designs.append({
            "file": f"posgmo-factory/tests/{path.name}",
            "description": data.get("description", "").strip().split("\n\n", 1)[0][:500],
            "fields": [f.get("name", "") for f in data.get("fields", [])][:15],
        })
    return designs[:2]


def _experience(query: str) -> List[dict]:
    try:
        from factory_experience import search  # needs GEMINI_API_KEY + a built index
        results = search(query, top_k=3)
    except Exception as exc:
        return [{"kind": "assumption", "claim": f"Factory experience search was unavailable ({type(exc).__name__})."}]
    return [
        {"kind": "evidence", "claim": f"Past {r.get('type', 'record')} for module '{r.get('module', '?')}': {r.get('finding', '')}",
         "source": r.get("source")}
        for r in results or [] if r.get("score", 0) >= 0.55
    ]


def gather_business_evidence(text: str, use_experience: bool = False) -> dict:
    """Plain JSON-serialisable evidence for the analyst (see module docstring)."""
    candidates = match_modules(text)
    candidate_ids = {m.id for m in candidates}
    verified_facts: List[dict] = []
    assumptions: List[dict] = []
    tables: Dict[str, dict] = {}
    candidate_evidence: List[dict] = []

    for module in candidates:
        check = _verify_wiring(module)
        designs = _draft_designs(module)
        candidate_evidence.append({**module.as_evidence(), **check, "readiness": _layer_readiness(module, check),
                                   "draftDesigns": designs})

        v = check["verified"]
        if any(v.values()):
            parts = [f"{k}: {', '.join(vals)}" for k, vals in v.items() if vals]
            verified_facts.append({"kind": "verified_fact",
                                   "claim": f"'{module.name}' implementation found — {'; '.join(parts)}.",
                                   "source": "Backend/*.json, Database/structure_database.csv, ecosystem_graph"})
        if check["evidenceLevel"] == "catalog-only":
            assumptions.append({"kind": "assumption",
                                "claim": f"'{module.name}' is listed in GMO_MODULES.md but no implementation was verified "
                                         f"in the repository knowledge (catalog only)."})
        for claim in check["unverifiedClaims"]:
            assumptions.append({"kind": "assumption", "claim": f"'{module.name}' lists {claim}, which is not in the repository knowledge files."})
        for design in designs:
            verified_facts.append({"kind": "verified_fact", "claim": f"Draft design for '{module.name}': {design['description']}",
                                   "source": design["file"]})
        for table in v["tables"]:
            if len(tables) < _MAX_TABLES and table not in tables:
                tables[table] = {"columns": _columns_by_table().get(table, [])[:_MAX_COLUMNS], **neighbors_of(table)}

    if not candidates:
        assumptions.append({"kind": "assumption",
                            "claim": "No GMO module matched the request's words; use the repository inventory to look for related implementations."})

    return {
        "candidateModules": candidate_evidence,
        "otherModules": [m.index_line() for m in load_modules() if m.id not in candidate_ids],
        "tables": tables,
        "repositoryInventory": {
            "backendRoutes": backend_routes(),
            "storedProcedures": stored_procedures(),
            "tables": sorted(load_schema_tables()),
            "verifiedFrontendFiles": verified_frontend_files(),
        },
        "verifiedFacts": verified_facts,
        "assumptions": assumptions,
        "evidence": _experience(text) if use_experience else [],
    }
