"""
Artifact contracts -- did the resulting artifact satisfy its declared
construction obligations?

Distinct from the other two verification layers:
  agent_contracts.py   -- did the agent execute its assigned tool/produce
                           its output_key at all?
  requirement_trace.py -- does a specific named business/security
                           requirement hold, across every stage that touches it?
  artifact_contracts.py (this module) -- given that an artifact WAS
                           produced, is it actually complete relative to
                           what the PRD asked for?

Root cause this addresses (Experiment 5): decision_gate._classify_backend_pattern()
only recognizes two endpoint categories -- standard CRUD paths, and
"connector" endpoints (calling an external service, detected by keyword).
A custom PRD endpoint that is neither (e.g. POST /leadCapture/public) is
silently dropped there and never appears in gate_result at all; separately,
agents/backend/prompt.py never references prd_hints.backend_endpoints in
any form. So there has never been an explicit, machine-checkable obligation
forcing backend_agent to implement a custom endpoint -- on the runs where it
did, that was incidental, not contracted. This module is that missing
obligation, on the verification side (it does not change what any agent is
told to do -- see agents/decision_gate/rules.py and agents/backend/prompt.py
if the fix should instead be upstream, in construction).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

SATISFIED = "SATISFIED"
ARTIFACT_FAILURE = "ARTIFACT_FAILURE"
NOT_VERIFIABLE = "NOT_VERIFIABLE"


def _endpoint_hint(path: str) -> str:
    """Last meaningful (non-parameter) path segment -- generated route/function
    names vary run to run ('public_leadCapture', 'public_lead_submission_connector',
    '/api/leadCapture/public'), but all of them contain this token."""
    segments = [s for s in (path or "").strip("/").split("/") if s and not s.startswith("{")]
    return segments[-1] if segments else (path or "")


@dataclass
class EndpointCompletenessResult:
    required: list[str]
    found: list[str]
    missing: list[str]
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "required": self.required,
            "found": self.found,
            "missing": self.missing,
            "status": self.status,
            "detail": self.detail,
        }


def check_backend_endpoint_completeness(prd: dict, backend_artifacts: Optional[dict]) -> dict:
    """
    Required endpoints come from the PRD directly (prd.backend.endpoints[]) --
    the ground truth of what was asked for, not specification.prd_hints
    (which is a downstream copy that could itself have been the point of
    loss; checking against the PRD catches that failure mode too, not just
    "did backend match whatever the architect forwarded").
    """
    required_eps = (prd.get("backend") or {}).get("endpoints") or []
    required = [
        {"path": ep.get("path", ""), "hint": _endpoint_hint(ep.get("path", ""))}
        for ep in required_eps
    ]

    if not required:
        return EndpointCompletenessResult(
            [], [], [], SATISFIED, "PRD declares no custom backend endpoints -- nothing to verify."
        ).as_dict()

    if not backend_artifacts:
        return EndpointCompletenessResult(
            [r["path"] for r in required], [], [r["path"] for r in required], NOT_VERIFIABLE,
            "backend_artifacts is missing/empty this run -- cannot verify endpoint completeness "
            "(this is an execution failure, see agent_contracts.py, not necessarily a completeness one).",
        ).as_dict()

    route_content = (backend_artifacts.get("route_file") or {}).get("content", "") or ""
    module_content = (backend_artifacts.get("module_file") or {}).get("content", "") or ""
    haystack = route_content + "\n" + module_content

    found, missing = [], []
    for r in required:
        if r["hint"] and re.search(re.escape(r["hint"]), haystack, re.I):
            found.append(r["path"])
        else:
            missing.append(r["path"])

    if missing:
        status, detail = ARTIFACT_FAILURE, (
            f"Required: {len(required)} custom endpoint(s). Found: {len(found)}. "
            f"Missing: {missing}."
        )
    else:
        status, detail = SATISFIED, f"All {len(required)} required custom endpoint(s) present."

    return EndpointCompletenessResult(
        [r["path"] for r in required], found, missing, status, detail
    ).as_dict()


# ---------------------------------------------------------------------------
# Observable duplicate-handling behavior (ADR-002 / REQ-005).
#
# Distinct from requirement_trace.py's REQ-005 checks: those answer "does
# this business requirement hold end to end," scored PASS/FAIL/NOT_VERIFIABLE
# per stage as part of a 5-requirement trace. These answer a narrower,
# code-level question in isolation -- "did the artifact do the specific
# observable thing ADR-002 obligates" -- independent of any particular named
# requirement, the same way check_backend_endpoint_completeness above isn't
# about a REQ-00N, it's about whether construction matched its own contract.
# ---------------------------------------------------------------------------

def check_backend_duplicate_error_propagation(backend_artifacts: Optional[dict]) -> dict:
    """Required: the create/upsert wrapper inspects the SP's embedded
    result.error field AND branches to a non-2xx status because of it.
    Checking for both, not just the first, is the point -- reading the field
    without acting on it (a real failure mode seen in Experiments 1/2) is not
    compliance."""
    if not backend_artifacts:
        return {"status": NOT_VERIFIABLE, "detail": "backend_artifacts is missing/empty this run -- cannot verify"}
    content = (backend_artifacts.get("module_file") or {}).get("content", "") or ""
    if not content:
        return {"status": NOT_VERIFIABLE, "detail": "module_file has no content this run"}

    checks_error_key = bool(re.search(
        r'json_result\[.result.\]\[0\]\[.error.\]|result\.get\(.error.\)|"error"\s*==\s*"1"'
        r'|["\']error["\']\s+in\s+result|result\[["\']error["\']\]',
        content,
    ))
    branches_non_2xx = bool(re.search(r'status_code\s*=\s*(?:[4-5]\d\d)', content))

    if checks_error_key and branches_non_2xx:
        return {"status": SATISFIED, "detail": "Inspects the embedded error field and branches to a non-2xx status for it."}
    if checks_error_key:
        return {"status": ARTIFACT_FAILURE, "detail": "Reads the embedded error field but never returns a non-2xx status for it -- the caller still sees 200."}
    return {"status": ARTIFACT_FAILURE, "detail": "Never inspects the SP's embedded error field at all -- returns its raw 200 response unconditionally."}


def check_frontend_duplicate_error_handling(frontend_artifacts: Optional[dict]) -> dict:
    """Required: the frontend does not rely on res.ok alone -- it must also
    inspect the response body for an embedded error/duplicate indication,
    since the backend can legitimately return HTTP 200 with an embedded
    error (the SP's own convention) even after ADR-002's backend fix ships
    (a 4xx/5xx makes this moot, but the frontend can't assume that without
    checking, and older/other endpoints in this codebase use the 200+embedded
    convention throughout)."""
    if not frontend_artifacts:
        return {"status": NOT_VERIFIABLE, "detail": "frontend_artifacts is missing/empty this run -- cannot verify"}
    content = (frontend_artifacts.get("api_file") or {}).get("content", "") or ""
    if not content:
        return {"status": NOT_VERIFIABLE, "detail": "api_file has no content this run"}

    checks_body_error = bool(re.search(r'\.error\b|["\']error["\']\s+in\s+\w+|result\[["\']error["\']\]', content))
    only_checks_res_ok = "res.ok" in content and not checks_body_error

    if checks_body_error:
        return {"status": SATISFIED, "detail": "Inspects the response body for an embedded error, not just res.ok."}
    if only_checks_res_ok:
        return {"status": ARTIFACT_FAILURE, "detail": "Only checks res.ok -- a 200 response with an embedded error/duplicate flag would read as success."}
    return {"status": NOT_VERIFIABLE, "detail": "Could not determine error-handling strategy from this file's shape."}
