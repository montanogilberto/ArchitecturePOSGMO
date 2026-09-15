"""
Decision Registry — durable persistence for debate_v2 Decisions.

debate_v2 already produces a real `Decision` (debate_schema.py: round,
selected_claim, rationale, evidence, confidence, decided_by) every time a
debate converges. Until now nothing kept it: run_agentic_factory.py only
wrote debate_v2_output/SOLUTION_PACKAGE.md, a SINGLE file overwritten on
every run — so a decision made last week was unrecoverable the moment a
different request was debated.

This module is the fix: one immutable JSON file per converged decision,
under decision_registry/, each with a stable ADR-NNN id assigned once and
never reused. It does not change how debate_v2 decides anything — it only
gives an already-real Decision object a permanent home, so a later
question like "why did you create RewardLedger" can be answered by
reading an actual file instead of nothing.

Usage:
    python decision_registry.py                # list every recorded decision
    python decision_registry.py ADR-003         # show one decision in full
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from debate_schema import Decision

_REGISTRY_DIR = Path(__file__).parent / "decision_registry"


def _next_id() -> str:
    existing = sorted(_REGISTRY_DIR.glob("ADR-*.json")) if _REGISTRY_DIR.exists() else []
    if not existing:
        return "ADR-001"
    last_num = max(int(p.stem.split("-")[1]) for p in existing)
    return f"ADR-{last_num + 1:03d}"


def record_decision(*, request: str, decision: Decision, module: Optional[str] = None) -> dict:
    """Persists an approved debate Decision as a new, immutable entry.
    Call this once, right after a debate converges (see
    run_agentic_factory.py's GATE: CONVERGED branch) — never to edit an
    existing decision; a changed mind is a NEW decision, not a rewritten one.

    Args:
        request: The free-text request the debate was run over.
        decision: The Decision object debate_v2 converged on (from
            read_blackboard(state, "decisions")[0]).
        module: The PRD module this decision was implemented as, once known
            (omit if no PRD has been validated against it yet).

    Returns:
        The full record written, including its assigned "id".
    """
    _REGISTRY_DIR.mkdir(exist_ok=True)
    adr_id = _next_id()
    record = {
        "id": adr_id,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request": request,
        "module": module,
        "selectedClaim": decision.selected_claim,
        "rationale": decision.rationale,
        "evidence": decision.evidence,
        "confidence": decision.confidence,
        "decidedBy": decision.decided_by,
        "round": decision.round,
    }
    (_REGISTRY_DIR / f"{adr_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def get_decision(adr_id: str) -> Optional[dict]:
    """Fetches one decision by id, or None if it doesn't exist."""
    path = _REGISTRY_DIR / f"{adr_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_decisions() -> list[dict]:
    """Every recorded decision, oldest first."""
    if not _REGISTRY_DIR.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(_REGISTRY_DIR.glob("ADR-*.json"))
    ]


def get_decisions_for_module(module_name: str) -> list[dict]:
    """Every recorded decision whose `module` matches module_name
    (case-insensitive), oldest first. Shared by mcp_server/server.py's MCP
    tool of the same name and agents/decision_gate/rules.py's pure-Python
    gate — one filter, two callers, so they can never drift apart."""
    needle = module_name.lower().strip()
    return [d for d in list_decisions() if (d.get("module") or "").lower() == needle]


def search_decisions(keyword: str) -> list[dict]:
    """Lexical (substring, case-insensitive) search over request/
    selectedClaim/rationale — same keyword-match-only philosophy as
    LoanAgents_SmartLoans/retrieval/keyword_search.py: exact-term matching,
    no semantic understanding, say plainly if nothing matched."""
    needle = keyword.lower()
    return [
        r for r in list_decisions()
        if needle in r["request"].lower()
        or needle in r["selectedClaim"].lower()
        or needle in r["rationale"].lower()
    ]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        found = get_decision(sys.argv[1])
        if found is None:
            print(f"No decision found with id {sys.argv[1]!r}")
            sys.exit(1)
        print(json.dumps(found, indent=2))
    else:
        records = list_decisions()
        if not records:
            print("No decisions recorded yet.")
        for r in records:
            print(f"{r['id']}  ({r['createdAt']})  module={r['module']}  {r['selectedClaim']}")
