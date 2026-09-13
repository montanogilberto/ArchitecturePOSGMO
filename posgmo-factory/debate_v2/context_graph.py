"""
Phase 3 — Repository/context graph.

Extends Phase 2's filesystem-only evidence (draft PRDs, knowledge JSON) with
a cross-check against the CANONICAL, live-tracked database schema
(Database/structure_database.csv + Database/sql_relationships.json — the
same files CLAUDE.md names as the "live source of truth", also read by the
existing get_database_schema MCP tool). No live DB connection and no GitHub
API calls are made here — both require credentials this environment does
not have configured (LOCAL_DB_*, GITHUB_TOKEN); this stays local-file-only,
consistent with Phase 2's scope.

This closes a real gap Phase 2 left open: Phase 2 could report "the PRD's
own text claims an existing 'rewardBalances' table" (a true fact about the
PRD document), but never checked whether that claim is actually TRUE against
the real schema. A debate that only verifies "what the PRD says" instead of
"what the PRD says AND whether the DB backs it up" is exactly the kind of
half-verified evidence the doc's "existing system first" principle (§9)
warns against.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set

from debate_schema import ContextItem, ContextItemKind

_FACTORY_ROOT = Path(__file__).resolve().parent.parent   # posgmo-factory/
_KNOWLEDGE_ROOT = _FACTORY_ROOT.parent                     # repo root
_STRUCTURE_CSV = _KNOWLEDGE_ROOT / "Database" / "structure_database.csv"
_RELATIONSHIPS_JSON = _KNOWLEDGE_ROOT / "Database" / "sql_relationships.json"


@lru_cache(maxsize=1)
def load_schema_tables() -> Set[str]:
    """Distinct real table names from the canonical schema snapshot."""
    if not _STRUCTURE_CSV.exists():
        return set()
    tables: Set[str] = set()
    with open(_STRUCTURE_CSV, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1]:
                tables.add(row[1])
    return tables


@lru_cache(maxsize=1)
def load_relationships() -> List[dict]:
    if not _RELATIONSHIPS_JSON.exists():
        return []
    return json.loads(_RELATIONSHIPS_JSON.read_text(encoding="utf-8"))


def neighbors_of(table: str) -> Dict[str, List[str]]:
    """1-hop FK neighborhood: what this table is a child of, and what is a
    child of it — the minimal 'context graph' slice relevant to a new
    module's proposed relationships (doc §8)."""
    rels = load_relationships()
    parents = sorted({r["parent_table"] for r in rels if r["child_table"] == table})
    children = sorted({r["child_table"] for r in rels if r["parent_table"] == table})
    return {"parents": parents, "children": children}


def check_domain_has_no_matching_table(keyword: str) -> ContextItem:
    """The cross-check Phase 2 was missing: does ANY real table actually
    match this keyword? Reported as a verified fact either way — it's a
    fact about what IS in the schema snapshot, not a claim about the
    business domain's true state (the snapshot could be stale)."""
    tables = load_schema_tables()
    matches = sorted(t for t in tables if keyword.lower() in t.lower())
    if matches:
        return ContextItem(
            kind=ContextItemKind.verified_fact,
            claim=f"{len(matches)} real table(s) matching '{keyword}' exist in the schema "
                  f"snapshot: {', '.join(matches)}.",
            source="repo:Database/structure_database.csv",
        )
    return ContextItem(
        kind=ContextItemKind.verified_fact,
        claim=f"No table matching '{keyword}' exists in the current schema snapshot "
              f"({len(tables)} tables checked) — any PRD text claiming an existing "
              f"same-domain table should be treated as unverified against this source.",
        source="repo:Database/structure_database.csv",
    )


def check_referenced_parent_tables(parent_module_names: List[str]) -> List[ContextItem]:
    """For each parent table a draft PRD's relationships[] declares (e.g.
    'clients', 'companies'), confirm it's a real anchor in the schema and
    report its live neighborhood — doc §4's rule that FK targets must be
    verified from the actual project, never invented."""
    items: List[ContextItem] = []
    tables = load_schema_tables()
    for name in sorted(set(parent_module_names)):
        if name in tables:
            nb = neighbors_of(name)
            items.append(ContextItem(
                kind=ContextItemKind.verified_fact,
                claim=f"Parent table '{name}' exists in the schema; it already has "
                      f"{len(nb['children'])} child table(s) via FK.",
                source="repo:Database/sql_relationships.json",
            ))
        else:
            items.append(ContextItem(
                kind=ContextItemKind.assumption,
                claim=f"Parent table '{name}' referenced by a draft PRD was NOT found in "
                      f"the schema snapshot — unverified: either a naming mismatch or the "
                      f"table does not exist yet.",
            ))
    return items
