"""
Requirement Trace / Consistency layer.

Contracts (agent_contracts.py) answer "did the agent execute its assigned
operation." Diagnostics (pipeline_diagnostics.py) answer "did the model
produce something observable." Neither answers the question Experiments 2
and 3 kept surfacing: does the generated system actually satisfy a specific
business/security requirement, end to end, across every stage that touches
it?

This module traces a small set of named requirements through PRD -> Decision
-> Database -> Backend -> Frontend -> Tests, using deterministic checks
(regex/keyword over the already-generated artifacts, same style as
agents/reviewer/rules.py and agents/decision_gate/rules.py) and reports a
verdict per requirement per stage:

  PASS             -- this stage's artifact satisfies the requirement
  FAIL             -- this stage's artifact actively violates the requirement
  UNKNOWN          -- the artifact exists and was checked, but no decision or
                       PRD language addresses this requirement at all -- a
                       genuine architectural silence, not a tooling gap
  NOT_VERIFIABLE   -- this checker could not determine an answer, either
                       because the upstream artifact is missing/empty (an
                       earlier stage failed) or because the check itself
                       couldn't locate what it needed. Distinct from UNKNOWN
                       on purpose: "nobody decided this" and "we couldn't
                       check" are different findings and must not collapse
                       into one bucket, or a checker limitation would read
                       as an architectural fact.
  NOT_APPLICABLE   -- this requirement doesn't apply to this stage,
                      or (for "Tests") no such stage exists in this factory

This is a standalone verification tool run AFTER generation, on artifacts
that already exist. It is not fed into any agent and does not change
generation behavior -- it answers "did construction honor the decisions,"
which is a different question from "did the agent execute" (agent_contracts)
or "is this good POS GMO code" (reviewer_agent).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
NOT_VERIFIABLE = "NOT_VERIFIABLE"
NOT_APPLICABLE = "N/A"

STAGES = ["prd", "decision", "database", "backend", "frontend", "tests"]


def _parse(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _find_function(content: str, name_hint: str) -> str:
    """Best-effort extraction of the function whose name contains name_hint
    (case-insensitive), across the different function-naming conventions
    we've observed generation use run to run."""
    if not content:
        return ""
    m = re.search(
        rf"((?:async\s+)?def\s+\w*{re.escape(name_hint)}\w*\(.*?)(?=\n(?:async\s+)?def\s|\Z)",
        content, re.S | re.I,
    )
    return m.group(1) if m else ""


@dataclass
class Verdict:
    stage: str
    verdict: str
    evidence: str


Checker = Callable[[dict], Verdict]


@dataclass
class Requirement:
    id: str
    text: str
    checkers: dict[str, Checker]


# ---------------------------------------------------------------------------
# REQ-001 — Public lead creation must be unauthenticated.
# ---------------------------------------------------------------------------

def _req001_prd(ctx: dict) -> Verdict:
    endpoints = (ctx["prd"].get("backend") or {}).get("endpoints") or []
    for ep in endpoints:
        if "public" in (ep.get("path") or "").lower() and "unauthenticated" in (ep.get("description") or "").lower():
            return Verdict("prd", PASS, f"backend.endpoints[].description names it unauthenticated: {ep['path']}")
    return Verdict("prd", UNKNOWN, "No PRD endpoint explicitly marked public+unauthenticated")


def _req001_decision(ctx: dict) -> Verdict:
    endpoints = ((ctx["specification"] or {}).get("prd_hints") or {}).get("backend_endpoints") or []
    for ep in endpoints:
        if "unauthenticated" in (ep.get("description") or "").lower():
            return Verdict("decision", PASS, "prd_hints.backend_endpoints forwarded the unauthenticated requirement verbatim")
    if not ctx["specification"]:
        return Verdict("decision", NOT_VERIFIABLE, "specification is empty this run -- architect_agent's artifact failed")
    return Verdict("decision", UNKNOWN, "specification.prd_hints carries no explicit auth requirement")


def _req001_backend(ctx: dict) -> Verdict:
    be = ctx["backend_artifacts"] or {}
    if not be:
        return Verdict("backend", NOT_VERIFIABLE, "backend_artifacts empty this run -- backend_agent's artifact failed")
    route_content = (be.get("route_file") or {}).get("content", "")
    public_route = _find_function(route_content, "public")
    if not public_route:
        # module_file public function + route wiring may not use "def" pattern we can isolate;
        # fall back to searching the whole route file for the public path.
        public_route = route_content
    if not public_route:
        return Verdict("backend", NOT_VERIFIABLE, "Could not locate a public route in route_file")
    if re.search(r"require_worker_key|Depends\(", public_route):
        return Verdict("backend", FAIL, "Public route has an auth dependency")
    return Verdict("backend", PASS, "No auth dependency found on the public route")


REQ_001 = Requirement(
    id="REQ-001",
    text="Public lead creation must be unauthenticated.",
    checkers={
        "prd": _req001_prd,
        "decision": _req001_decision,
        "database": lambda ctx: Verdict("database", NOT_APPLICABLE, "Auth is not a database-layer concern"),
        "backend": _req001_backend,
        "frontend": lambda ctx: Verdict("frontend", NOT_APPLICABLE, "Not checked at this layer"),
        "tests": lambda ctx: Verdict("tests", NOT_APPLICABLE, "No test-generation stage exists in this pipeline"),
    },
)


# ---------------------------------------------------------------------------
# REQ-002 — Public callers must not control tenant identity (companyId).
# ---------------------------------------------------------------------------

def _decision_gate_tenant_verdict(ctx: dict) -> Verdict:
    """Shared by REQ-002 and REQ-003: reads gate_result.tenant_model directly
    when present (the fix recorded as ADR-001 / agents/decision_gate/rules.py
    _classify_tenant_model), falling back to sniffing the old blanket-rule
    text for saved states from before that fix existed (Experiments 1-3),
    so this checker gives a correct verdict against both old and new runs."""
    gate = ctx["gate_result"] or {}
    if not gate:
        return Verdict("decision", NOT_VERIFIABLE, "gate_result is empty this run -- decision_gate_agent's artifact failed")

    tenant_model = gate.get("tenant_model")
    if tenant_model == "TENANT_INDEPENDENT":
        return Verdict(
            "decision", PASS,
            f"gate_result.tenant_model=TENANT_INDEPENDENT ({gate.get('tenant_model_reason', '')})",
        )
    if tenant_model in ("TENANT_SCOPED", "TENANT_DERIVED"):
        return Verdict(
            "decision", FAIL,
            f"gate_result.tenant_model={tenant_model} -- companyId is being required despite the PRD's stated exception "
            f"({gate.get('tenant_model_reason', '')})",
        )
    if gate.get("status") == "BLOCKED" and "tenant" in (gate.get("reason") or "").lower():
        return Verdict(
            "decision", FAIL,
            "Correctly blocked pending an explicit tenant_model decision -- construction has not "
            "proceeded, which is the intended behavior, but the requirement is not yet satisfied "
            f"({gate.get('reason')})",
        )

    # Pre-fix gate_result shape (Experiments 1-3): no tenant_model field at all,
    # just the old unconditional rule baked into mandatory_constraints text.
    db_rules = " ".join((gate.get("mandatory_constraints") or {}).get("database") or [])
    if "companyid" in db_rules.lower() and "must be present" in db_rules.lower():
        return Verdict(
            "decision", FAIL,
            "decision_gate.mandatory_constraints.database universally requires companyId "
            "with no per-module override -- this is a hardcoded rule "
            "(agents/decision_gate/rules.py:_build_mandatory_constraints), not a decision "
            "derived from this module's tenancy model.",
        )
    return Verdict("decision", UNKNOWN, "No companyId/tenant_model rule found in gate_result")


def _req002_prd(ctx: dict) -> Verdict:
    if not ctx["prd"]:
        return Verdict("prd", NOT_VERIFIABLE, "No PRD available to check")
    desc = ctx["prd"].get("description", "")
    endpoints = (ctx["prd"].get("backend") or {}).get("endpoints") or []
    names_companyid_forbidden = any(
        "companyid" in (ep.get("description") or "").lower()
        and "public" in (ep.get("path") or "").lower()
        for ep in endpoints
    )
    if names_companyid_forbidden:
        return Verdict("prd", PASS, "Public endpoint description explicitly forbids companyId")
    if "no existing companyid relationship" in desc.lower():
        return Verdict(
            "prd", PASS,
            "description names the tenancy exception, but the public endpoint's own "
            "forbidden-field list never explicitly named companyId -- a real gap in the "
            "PRD itself, found only by writing this check.",
        )
    return Verdict("prd", UNKNOWN, "PRD does not address tenant identity for public submission")


def _req002_database(ctx: dict) -> Verdict:
    db = ctx["database_artifacts"] or {}
    create_table = db.get("create_table", "")
    if not create_table:
        return Verdict("database", NOT_VERIFIABLE, "database_artifacts empty this run -- database_agent's artifact failed")
    if re.search(r"companyId\s+INT\s+NOT\s+NULL", create_table, re.I):
        return Verdict("database", FAIL, "companyId is INT NOT NULL with no default -- every INSERT, including public ones, must supply it")
    return Verdict("database", PASS, "companyId is not a hard requirement in this schema")


def _req002_backend(ctx: dict) -> Verdict:
    be = ctx["backend_artifacts"] or {}
    if not be:
        return Verdict("backend", NOT_VERIFIABLE, "backend_artifacts empty this run -- backend_agent's artifact failed")
    content = (be.get("module_file") or {}).get("content", "")
    public_fn = _find_function(content, "public")
    if not public_fn:
        return Verdict("backend", NOT_VERIFIABLE, "Could not isolate the public submission function")
    # companyId is a tenancy/system field, never a business field this endpoint is
    # meant to accept -- if it appears anywhere in this function's logic at all
    # (allow-list, existence check, default-if-missing), it was read from the
    # anonymous caller. The correct implementation never mentions it here.
    if "companyId" in public_fn:
        return Verdict("backend", FAIL, "Public function references companyId at all -- it is being read from, defaulted from, or validated against the anonymous caller's own payload")
    return Verdict("backend", PASS, "Public function never references companyId -- not read from caller input")


def _req002_frontend(ctx: dict) -> Verdict:
    fe = ctx["frontend_artifacts"] or {}
    if not fe:
        return Verdict("frontend", NOT_VERIFIABLE, "frontend_artifacts empty this run -- frontend_agent's artifact failed")
    content = (fe.get("api_file") or {}).get("content", "")
    if not content:
        return Verdict("frontend", NOT_VERIFIABLE, "api_file has no content this run")
    if "public" not in content.lower():
        # Don't fall back to scanning the whole file here: the ordinary
        # internal-CRUD interface legitimately includes companyId (it's an
        # authenticated admin call), and a naive whole-file scan would read
        # that as a violation of a requirement about code that was never
        # generated at all. "No public function exists" is a different,
        # separate finding (requirement fidelity, not tenant-identity), and
        # gets caught by REQ-001 -- this check has nothing to verify.
        return Verdict("frontend", NOT_VERIFIABLE, "No public-facing function/type found in api_file at all this run -- nothing to check")
    m = re.search(r"Public\w*(?:Payload|Create\w*)\s*[={][^;{}]*\{(.*?)\}", content, re.S)
    if not m:
        return Verdict("frontend", NOT_VERIFIABLE, "A public reference exists but the payload type could not be isolated by this checker")
    block = m.group(1)
    if re.search(r"companyId", block):
        return Verdict("frontend", FAIL, "Public payload type/interface includes companyId as a caller-supplied field")
    return Verdict("frontend", PASS, "Public payload type does not include companyId")


REQ_002 = Requirement(
    id="REQ-002",
    text="Public callers must not control tenant identity (companyId).",
    checkers={
        "prd": _req002_prd,
        "decision": _decision_gate_tenant_verdict,
        "database": _req002_database,
        "backend": _req002_backend,
        "frontend": _req002_frontend,
        "tests": lambda ctx: Verdict("tests", NOT_APPLICABLE, "No test-generation stage exists in this pipeline"),
    },
)


# ---------------------------------------------------------------------------
# REQ-003 — Lead does not have an existing companyId relationship
#           (structural: no FK to companies).
# ---------------------------------------------------------------------------

def _req003_prd(ctx: dict) -> Verdict:
    if not ctx["prd"]:
        return Verdict("prd", NOT_VERIFIABLE, "No PRD available to check")
    fields = ctx["prd"].get("fields") or []
    for f in fields:
        if f.get("name") == "companyName" and "no existing companyid" in (f.get("description") or "").lower():
            return Verdict("prd", PASS, "companyName field description states no existing companyId relationship")
    if "no existing companyid relationship" in ctx["prd"].get("description", "").lower():
        return Verdict("prd", PASS, "Top-level description states no existing companyId relationship")
    return Verdict("prd", UNKNOWN, "PRD does not address this")


def _req003_database(ctx: dict) -> Verdict:
    db = ctx["database_artifacts"] or {}
    create_table = db.get("create_table", "")
    if not create_table:
        return Verdict("database", NOT_VERIFIABLE, "database_artifacts empty this run -- database_agent's artifact failed")
    if re.search(r"FOREIGN\s+KEY\s*\(\s*companyId\s*\)\s*REFERENCES\s+dbo\.companies", create_table, re.I):
        return Verdict("database", FAIL, "An explicit FK to dbo.companies was added, hardening the tenancy assumption the PRD says doesn't apply")
    return Verdict("database", PASS, "No FK to companies -- companyId is present but not architecturally hard-linked")


REQ_003 = Requirement(
    id="REQ-003",
    text="Lead does not have an existing companyId relationship (no FK to companies).",
    checkers={
        "prd": _req003_prd,
        "decision": _decision_gate_tenant_verdict,
        "database": _req003_database,
        "backend": lambda ctx: Verdict("backend", NOT_APPLICABLE, "Structural DB-schema question"),
        "frontend": lambda ctx: Verdict("frontend", NOT_APPLICABLE, "Structural DB-schema question"),
        "tests": lambda ctx: Verdict("tests", NOT_APPLICABLE, "No test-generation stage exists in this pipeline"),
    },
)


# ---------------------------------------------------------------------------
# REQ-004 — Public payload cannot set status or assignment.
# ---------------------------------------------------------------------------

def _req004_prd(ctx: dict) -> Verdict:
    if not ctx["prd"]:
        return Verdict("prd", NOT_VERIFIABLE, "No PRD available to check")
    endpoints = (ctx["prd"].get("backend") or {}).get("endpoints") or []
    for ep in endpoints:
        d = (ep.get("description") or "").lower()
        if "public" in (ep.get("path") or "").lower() and "status" in d and "assignedto" in d:
            return Verdict("prd", PASS, "Public endpoint description explicitly forbids status/assignedTo")
    return Verdict("prd", UNKNOWN, "PRD does not address this for the public endpoint")


def _req004_backend(ctx: dict) -> Verdict:
    be = ctx["backend_artifacts"] or {}
    if not be:
        return Verdict("backend", NOT_VERIFIABLE, "backend_artifacts empty this run -- backend_agent's artifact failed")
    content = (be.get("module_file") or {}).get("content", "")
    public_fn = _find_function(content, "public")
    if not public_fn:
        return Verdict("backend", NOT_VERIFIABLE, "Could not isolate the public submission function")
    hardcodes_status = re.search(r'\[?["\']status["\']\]?\s*[:=]\s*["\']new["\']', public_fn)
    mentions_assignedto_as_input = re.search(r'payload\.get\(\s*["\']assignedTo["\']', public_fn)
    if hardcodes_status and not mentions_assignedto_as_input:
        return Verdict("backend", PASS, "status is server-hardcoded and assignedTo is never read from the public payload")
    if mentions_assignedto_as_input:
        return Verdict("backend", FAIL, "Public function reads assignedTo from caller input")
    return Verdict("backend", NOT_VERIFIABLE, "Could not conclusively determine status/assignedTo handling from this function's shape")


def _req004_frontend(ctx: dict) -> Verdict:
    fe = ctx["frontend_artifacts"] or {}
    if not fe:
        return Verdict("frontend", NOT_VERIFIABLE, "frontend_artifacts empty this run -- frontend_agent's artifact failed")
    content = (fe.get("api_file") or {}).get("content", "")
    if not content:
        return Verdict("frontend", NOT_VERIFIABLE, "api_file has no content this run")
    m = re.search(r"Public\w*(?:Payload|Create\w*)\s*[={][^;{}]*\{(.*?)\}", content, re.S)
    block = m.group(1) if m else ""
    if not block:
        return Verdict("frontend", NOT_VERIFIABLE, "Could not isolate the public payload type")
    if re.search(r"\bstatus\b", block) or re.search(r"\bassignedTo\b", block):
        return Verdict("frontend", FAIL, "Public payload type includes status or assignedTo")
    return Verdict("frontend", PASS, "Public payload type excludes status and assignedTo")


REQ_004 = Requirement(
    id="REQ-004",
    text="Public payload cannot set status or assignment.",
    checkers={
        "prd": _req004_prd,
        "decision": lambda ctx: Verdict("decision", NOT_APPLICABLE, "decision_gate has no field-level allow-list concept"),
        "database": lambda ctx: Verdict("database", NOT_APPLICABLE, "DB layer doesn't distinguish caller origin"),
        "backend": _req004_backend,
        "frontend": _req004_frontend,
        "tests": lambda ctx: Verdict("tests", NOT_APPLICABLE, "No test-generation stage exists in this pipeline"),
    },
)


# ---------------------------------------------------------------------------
# REQ-005 — Duplicate handling must follow the selected policy.
# ---------------------------------------------------------------------------

def _req005_prd(ctx: dict) -> Verdict:
    if not ctx["prd"]:
        return Verdict("prd", NOT_VERIFIABLE, "No PRD available to check")
    desc = ctx["prd"].get("description", "")
    if "duplicate" in desc.lower():
        return Verdict("prd", PASS, "Raised explicitly as an open design question")
    return Verdict("prd", UNKNOWN, "PRD does not raise duplicate handling")


def _req005_decision(ctx: dict) -> Verdict:
    """Reads gate_result.applicable_decisions for an explicit topic=
    'duplicate_policy' record (ADR-002-style), the same pattern
    _decision_gate_tenant_verdict uses for REQ-002/003 -- not a text scan
    over specification, for the same reason that was wrong there: a keyword
    match can't distinguish "this was decided" from "this word appears
    somewhere nearby." UNKNOWN here is a real, valuable finding (nobody
    made this decision explicit), not a tooling gap -- see the module
    docstring on why that must never collapse into PASS or FAIL."""
    gate = ctx["gate_result"] or {}
    if not gate:
        return Verdict("decision", NOT_VERIFIABLE, "gate_result is empty this run -- decision_gate_agent's artifact failed")
    decisions = gate.get("applicable_decisions") or []
    for d in decisions:
        if (d.get("topic") or "").lower() == "duplicate_policy":
            return Verdict(
                "decision", PASS,
                f"Explicit decision {d.get('id')}: {d.get('selectedClaim')} ({d.get('rationale', '')})",
            )
    return Verdict(
        "decision", UNKNOWN,
        "No explicit duplicate_policy decision recorded for this module in gate_result.applicable_decisions. "
        "Whatever the Database Agent decides on its own is a real behavior but not an explicit, "
        "checkable architectural decision -- this is a genuine architectural gap, not a tooling limitation.",
    )


def _req005_database(ctx: dict) -> Verdict:
    db = ctx["database_artifacts"] or {}
    if not db:
        return Verdict("database", NOT_VERIFIABLE, "database_artifacts empty this run -- database_agent's artifact failed")
    sp = db.get("sp_upsert", "")
    if not sp:
        return Verdict("database", NOT_VERIFIABLE, "sp_upsert has no content this run")
    has_unique_index = bool(re.search(r"UNIQUE\s+NONCLUSTERED\s+INDEX", db.get("create_table", ""), re.I))
    has_reject_message = bool(re.search(r"already exists", sp, re.I))
    has_group_by_check = bool(re.search(r"GROUP\s+BY[^;]*HAVING\s+COUNT\s*\(\s*\*\s*\)\s*>\s*1", sp, re.I | re.S))
    if has_unique_index and has_reject_message:
        return Verdict("database", PASS, "A concrete, enforced duplicate policy exists at the schema level: unique index + explicit reject")
    if has_group_by_check:
        return Verdict(
            "database", PASS,
            "A duplicate policy exists as application-logic in sp_upsert (GROUP BY/HAVING COUNT check), "
            "not a persistent UNIQUE constraint -- weaker under concurrent requests than a schema-level "
            "constraint, but a real, deliberate policy, not an omission.",
        )
    return Verdict("database", FAIL, "No duplicate-detection mechanism found")


def _req005_backend(ctx: dict) -> Verdict:
    be = ctx["backend_artifacts"] or {}
    if not be:
        return Verdict("backend", NOT_VERIFIABLE, "backend_artifacts empty this run -- backend_agent's artifact failed")
    content = (be.get("module_file") or {}).get("content", "")
    if not content:
        return Verdict("backend", NOT_VERIFIABLE, "module_file has no content this run")
    # The SP embeds {"error": "1", "msg": "..."} in a 200 response; backend must
    # inspect that AND actually branch to a non-2xx status for the caller to see
    # it as a rejection -- checking for the concept, not one exact code style,
    # since Experiment 6 wrote this legitimately as `"error" in result` + a
    # 409/400 branch, which none of the earlier literal patterns matched.
    checks_error_key = bool(re.search(
        r'json_result\[.result.\]\[0\]\[.error.\]|result\.get\(.error.\)|"error"\s*==\s*"1"'
        r'|["\']error["\']\s+in\s+result|result\[["\']error["\']\]',
        content,
    ))
    branches_non_2xx = bool(re.search(r'status_code\s*=\s*(?:[4-5]\d\d)', content))
    if checks_error_key and branches_non_2xx:
        return Verdict("backend", PASS, "Backend inspects the SP's embedded error field and branches to a non-2xx status for it")
    if checks_error_key and not branches_non_2xx:
        return Verdict("backend", FAIL, "Backend reads the embedded error field but never returns a non-2xx status for it -- the caller still sees 200")
    return Verdict("backend", FAIL, "Backend returns the SP's raw 200 response regardless of its embedded error/duplicate flag")


def _req005_frontend(ctx: dict) -> Verdict:
    fe = ctx["frontend_artifacts"] or {}
    if not fe:
        return Verdict("frontend", NOT_VERIFIABLE, "frontend_artifacts empty this run -- frontend_agent's artifact failed")
    content = (fe.get("api_file") or {}).get("content", "")
    if not content:
        return Verdict("frontend", NOT_VERIFIABLE, "api_file has no content this run")
    # ADR-002's constraint is about this module's create call generally, not
    # specifically a function named "public" -- gating on that word (as an
    # earlier version of this check did) produced a false FAIL against
    # Experiment 6's retry, where the embedded-error check correctly lives in
    # the ordinary createLeadCapture() because the custom public endpoint
    # wasn't generated this run at all (a separate, already-tracked gap).
    # Same concept-not-syntax fix as artifact_contracts.check_frontend_duplicate_error_handling.
    checks_body_error = bool(re.search(r'\.error\b|["\']error["\']\s+in\s+\w+|result\[["\']error["\']\]', content))
    if checks_body_error:
        return Verdict("frontend", PASS, "Frontend inspects the response body for an embedded error, not just res.ok")
    if "res.ok" in content:
        return Verdict("frontend", FAIL, "Frontend only checks res.ok -- a duplicate rejection (HTTP 200 with an embedded error) would read as success")
    return Verdict("frontend", NOT_VERIFIABLE, "Could not determine how the frontend handles a duplicate response from this file's shape")


REQ_005 = Requirement(
    id="REQ-005",
    text="Duplicate handling must follow the selected policy.",
    checkers={
        "prd": _req005_prd,
        "decision": _req005_decision,
        "database": _req005_database,
        "backend": _req005_backend,
        "frontend": _req005_frontend,
        "tests": lambda ctx: Verdict("tests", NOT_APPLICABLE, "No test-generation stage exists in this pipeline"),
    },
)


REQUIREMENTS = [REQ_001, REQ_002, REQ_003, REQ_004, REQ_005]


def trace(prd: dict, specification: dict, gate_result: dict,
          database_artifacts: dict, backend_artifacts: dict,
          frontend_artifacts: dict) -> list[dict]:
    ctx = {
        "prd": prd or {},
        "specification": specification or {},
        "gate_result": gate_result or {},
        "database_artifacts": database_artifacts or {},
        "backend_artifacts": backend_artifacts or {},
        "frontend_artifacts": frontend_artifacts or {},
    }
    results = []
    for req in REQUIREMENTS:
        row = {"id": req.id, "text": req.text, "stages": {}}
        for stage in STAGES:
            checker = req.checkers.get(stage)
            if checker is None:
                row["stages"][stage] = {"verdict": NOT_APPLICABLE, "evidence": "No checker defined"}
                continue
            v = checker(ctx)
            row["stages"][stage] = {"verdict": v.verdict, "evidence": v.evidence}
        results.append(row)
    return results


def trace_from_state(state: dict) -> list[dict]:
    """Convenience entry point: pull PRD + artifacts straight out of a saved
    orchestrator.run_factory() session-state dump."""
    prd = _parse(state.get("prd_raw")) or _parse(state.get("prd")) or {"description": state.get("description", "")}
    return trace(
        prd=prd,
        specification=_parse(state.get("specification")) or {},
        gate_result=_parse(state.get("gate_result")) or {},
        database_artifacts=_parse(state.get("database_artifacts")) or {},
        backend_artifacts=_parse(state.get("backend_artifacts")) or {},
        frontend_artifacts=_parse(state.get("frontend_artifacts")) or {},
    )


def render_markdown(results: list[dict]) -> str:
    lines = ["| Req | " + " | ".join(s.upper() for s in STAGES) + " |",
             "|---|" + "---|" * len(STAGES)]
    for row in results:
        cells = [row["stages"][s]["verdict"] for s in STAGES]
        lines.append(f"| {row['id']} | " + " | ".join(cells) + " |")
    lines.append("")
    for row in results:
        lines.append(f"### {row['id']} — {row['text']}")
        for s in STAGES:
            cell = row["stages"][s]
            lines.append(f"- **{s}**: {cell['verdict']} — {cell['evidence']}")
        lines.append("")
    return "\n".join(lines)
