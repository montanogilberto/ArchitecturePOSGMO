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

_KNOWN_LAYERS = ("database", "backend", "frontend", "tests")


class ConflictingConstraintsError(ValueError):
    """Raised when a decision supplies both `constraints` and
    `layer_constraints` — the registry refuses to guess which one is
    authoritative. This is an architectural control plane; silent ambiguity
    here would mean two different construction agents could legitimately
    read two different obligations out of the same decision."""


def expand_flat_constraints(constraints: list[str], applies_to: list[str]) -> dict[str, list[str]]:
    """A flat constraint list applies verbatim to every layer named in
    `applies_to` (or every known layer, if `applies_to` is empty)."""
    if not constraints:
        return {}
    layers = applies_to or list(_KNOWN_LAYERS[:-1])  # default: db/backend/frontend, not tests
    return {layer: list(constraints) for layer in layers}


def get_effective_constraints(record: dict) -> dict[str, list[str]]:
    """Normalizes any recorded decision -- however it was authored -- into
    one shape: {layer: [constraint, ...]}. Callers (decision_gate's generic
    propagation loop, or anything else) should always go through this rather
    than reading `constraints`/`layer_constraints` directly, so a future
    change to how a decision is authored never requires every reader to
    change too."""
    layer_constraints = record.get("layer_constraints") or {}
    if layer_constraints:
        return {layer: list(items) for layer, items in layer_constraints.items()}
    return expand_flat_constraints(record.get("constraints") or [], record.get("appliesTo") or [])


def _next_id() -> str:
    existing = sorted(_REGISTRY_DIR.glob("ADR-*.json")) if _REGISTRY_DIR.exists() else []
    if not existing:
        return "ADR-001"
    last_num = max(int(p.stem.split("-")[1]) for p in existing)
    return f"ADR-{last_num + 1:03d}"


def record_decision(*, request: str, decision: Decision, module: Optional[str] = None,
                     topic: Optional[str] = None, constraints: Optional[list[str]] = None,
                     layer_constraints: Optional[dict[str, list[str]]] = None,
                     applies_to: Optional[list[str]] = None) -> dict:
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
        topic: Short machine-readable key identifying which architectural
            question this resolves (e.g. "tenant_model", "duplicate_lead").
            Lets a caller like decision_gate_agent look up "has THIS specific
            question already been decided for this module" rather than just
            "has anything at all been decided" — added for the leadCapture
            companyId experiment (docs/experiment1-leadCapture-evaluation.md),
            where a single blanket rule was overriding an explicit exception.
        constraints: Concrete, enforceable rules construction agents must
            follow as a result of this decision, applied identically to
            every layer in `applies_to` (e.g. "public caller cannot provide
            companyId" — the same sentence is a valid obligation for
            database, backend, and frontend alike). Distinct from
            `evidence`, which supports WHY the decision was made — these are
            WHAT to do about it. Mutually exclusive with `layer_constraints`
            — a decision whose obligation genuinely differs per layer (e.g.
            duplicate-handling: the database enforces a constraint, the
            backend translates a result code, the frontend reads a
            response field) should use that instead, not force one sentence
            to serve three different meanings.
        layer_constraints: Per-layer obligations, e.g.
            {"database": [...], "backend": [...], "frontend": [...]}, for a
            decision whose enforcement genuinely differs by layer. Mutually
            exclusive with `constraints` — see get_effective_constraints for
            how either is normalized before decision_gate consumes it.
        applies_to: Which artifact layers `constraints` (the flat form)
            apply to, e.g. ["database", "backend", "frontend"]. Omit if it
            applies everywhere. Ignored when `layer_constraints` is used —
            layer_constraints' own keys already say which layers it applies to.

    Raises:
        ConflictingConstraintsError: if both `constraints` and
            `layer_constraints` are given. The registry is an architectural
            control plane; it will not guess which one a reader should trust.

    Returns:
        The full record written, including its assigned "id".
    """
    if constraints and layer_constraints:
        raise ConflictingConstraintsError(
            "record_decision() got both `constraints` and `layer_constraints`. "
            "Pick one: `constraints` for an obligation that's identical across every "
            "layer in `applies_to`, `layer_constraints` for one that genuinely differs "
            "per layer. Supplying both leaves it ambiguous which is authoritative."
        )

    _REGISTRY_DIR.mkdir(exist_ok=True)
    adr_id = _next_id()
    record = {
        "id": adr_id,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request": request,
        "module": module,
        "topic": topic,
        "selectedClaim": decision.selected_claim,
        "rationale": decision.rationale,
        "evidence": decision.evidence,
        "constraints": constraints or [],
        "layer_constraints": layer_constraints or {},
        "appliesTo": applies_to or [],
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


def get_decision_for_topic(module_name: str, topic: str) -> Optional[dict]:
    """The most recent recorded decision for this module on this specific
    topic (e.g. topic="tenant_model"), or None if that exact question has
    never been explicitly decided. Distinct from get_decisions_for_module:
    that answers "has anything been decided for this module" (surfaced today
    only as an informational warning); this answers "has THIS question been
    decided," which is what a gate needs before it can safely stop assuming
    an answer."""
    needle_topic = topic.lower().strip()
    matches = [d for d in get_decisions_for_module(module_name) if (d.get("topic") or "").lower() == needle_topic]
    return matches[-1] if matches else None


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
