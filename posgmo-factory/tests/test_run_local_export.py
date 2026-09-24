"""
run_local_export.py's endpoint-completeness wiring.

Before this fix, run_local_export.py (used for every real run this entire
session) never called check_backend_endpoint_completeness at all -- only
orchestrator.py's run_factory() did. The gap was found as a side effect of
Phase 3 (Implementation RAG): a proof query for "a public endpoint that
doesn't require authentication" didn't retrieve pricingPlan's backend as
expected, traced to pricingPlan's real generated route_file genuinely never
containing the custom public endpoint its own PRD asked for.

_parse_maybe_fenced_json is tested directly since it's new, small, and
easy to get subtly wrong (the same JSON-string-maybe-markdown-fenced shape
this repo already has several independent copies of -- agents/reviewer/
rules.py, agents/fixer/rules.py, orchestrator.py, factory_experience.py's
_parse_artifact_json). check_backend_endpoint_completeness itself is tested
against pricingPlan's REAL PRD + REAL generated backend content (not a
synthetic fixture) -- pinning down the actual gap this fix exists to catch,
not a hypothetical one.
"""
import json

from run_local_export import _parse_maybe_fenced_json, _strip_pr_and_design_consistency
from artifact_contracts import check_backend_endpoint_completeness
from agents import root_agent
from agents.agent import generation_stage
from agents.pr import pr_agent
from agents.design_consistency import design_consistency_agent


def test_strip_pr_and_design_consistency_is_idempotent():
    """Regression test for a real bug this fix introduced and then had to
    fix again: the original module-level version of this mutation ran once
    at import time and broke unrelated tests (test_agents_import.py,
    test_debate_v2_no_factory_coupling.py) that assert root_agent still has
    pr_agent -- because Python only runs a module's top level once per
    process, and the mutation was on the SAME shared root_agent/
    generation_stage objects orchestrator.py also uses. Moved into this
    idempotent function, called explicitly from run_local(). Calling it
    twice must not raise and must not remove anything already removed."""
    _strip_pr_and_design_consistency()
    _strip_pr_and_design_consistency()  # must not raise on the second call
    assert pr_agent not in root_agent.sub_agents
    assert design_consistency_agent not in generation_stage.sub_agents


def test_parse_maybe_fenced_json_plain_json_string():
    assert _parse_maybe_fenced_json('{"a": 1}') == {"a": 1}


def test_parse_maybe_fenced_json_strips_markdown_fences():
    raw = '```json\n{"a": 1}\n```'
    assert _parse_maybe_fenced_json(raw) == {"a": 1}


def test_parse_maybe_fenced_json_dict_passthrough():
    assert _parse_maybe_fenced_json({"a": 1}) == {"a": 1}


def test_parse_maybe_fenced_json_malformed_returns_none():
    assert _parse_maybe_fenced_json("not json at all") is None


def test_parse_maybe_fenced_json_empty_string_returns_none():
    assert _parse_maybe_fenced_json("") is None
    assert _parse_maybe_fenced_json("   ") is None


def test_pricingplan_real_gap_is_detected_as_artifact_failure():
    """The actual real-world case this fix exists for, pinned down as a
    permanent regression test: pricingPlan's PRD declares a custom public
    endpoint (/pricingPlan/public); its real generated backend never
    implements it. Must be ARTIFACT_FAILURE with the specific path named,
    not NOT_VERIFIABLE (that status means "nothing to check", which is
    false here -- there IS backend content, it's just incomplete)."""
    prd = json.load(open("tests/prd_pricingPlan.json"))
    real_route_file_content = (
        "from fastapi import APIRouter\n"
        "from modules.pricingPlans import pricingPlans_sp, all_pricingPlans_sp, one_pricingPlans_sp\n\n\n"
        "router = APIRouter()\n\n"
        '@router.post("/pricingPlans", summary="pricingPlans CRUD")\n'
        "def pricingPlans(json: dict):\n"
        "    return pricingPlans_sp(json)\n\n\n"
        '@router.post("/all_pricingPlans", summary="all pricingPlans")\n'
        "def all_pricingPlans(json: dict):\n"
        "    return all_pricingPlans_sp(json)\n\n\n"
        '@router.post("/one_pricingPlans", summary="one pricingPlan")\n'
        "def one_pricingPlans(json: dict):\n"
        "    return one_pricingPlans_sp(json)\n"
    )
    backend_artifacts = {"route_file": {"path": "routes_/pricingPlan.py", "content": real_route_file_content}}

    result = check_backend_endpoint_completeness(prd, backend_artifacts)

    assert result["status"] == "ARTIFACT_FAILURE"
    assert "/pricingPlan/public" in result["missing"]
    assert result["found"] == []


def test_endpoint_completeness_not_verifiable_when_backend_artifacts_truly_empty():
    """Distinct from the ARTIFACT_FAILURE case above: when backend_agent
    produced NOTHING (the construction-layer stochastic failure documented
    since Milestone 1), the status must say NOT_VERIFIABLE -- "nothing to
    check" -- not silently claim the endpoint is missing as if it had been
    genuinely checked and failed."""
    prd = json.load(open("tests/prd_pricingPlan.json"))
    result = check_backend_endpoint_completeness(prd, {})
    assert result["status"] == "NOT_VERIFIABLE"
