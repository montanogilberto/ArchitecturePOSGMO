"""
PR Agent target routing — orchestrator.py's _build_session_state and
agents/prd_parser/rules.py's store_prd_context must agree on which repo pair
a run targets. store_prd_context runs AFTER _build_session_state in the real
pipeline and used to independently re-derive GITHUB_FRONTEND_REPO /
GITHUB_BACKEND_REPO from hardcoded env var names, silently overwriting
whatever target _build_session_state picked. These tests pin down: (1) each
function's own default ("pos") behavior is unchanged, (2) "commercial"
target is honored, (3) the two functions never disagree when given the same
target_repo, so a commercial-platform module can never silently get routed
back to the POS repos partway through the pipeline.
"""
import os
from unittest.mock import MagicMock

import pytest

from orchestrator import _build_session_state, _REPO_ENV_VARS
from agents.prd_parser.rules import store_prd_context
from prd_schema import PRDInput


@pytest.fixture(autouse=True)
def _repo_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO_NAME", "https://github.com/montanogilberto/POSVending.git")
    monkeypatch.setenv("GITHUB_BACKEND_REPO_NAME", "https://github.com/montanogilberto/smartloans_backend.git")
    monkeypatch.setenv("GITHUB_COMMERCIAL_FRONTEND_REPO", "https://github.com/montanogilberto/factory-ai-gmo-commercial.git")
    monkeypatch.setenv("GITHUB_COMMERCIAL_BACKEND_REPO", "https://github.com/montanogilberto/factory-ai-gmo-commercial-backend.git")


def _minimal_prd() -> PRDInput:
    return PRDInput.model_validate({
        "module": "supplier",
        "description": "Manages product suppliers for testing.",
        "fields": [{"name": "supplierName", "type": "string", "required": True}],
    })


def test_build_session_state_defaults_to_pos_repos():
    state = _build_session_state(_minimal_prd())
    assert state["target_repo"] == "pos"
    assert state["GITHUB_FRONTEND_REPO"] == "montanogilberto/POSVending"
    assert state["GITHUB_BACKEND_REPO"] == "montanogilberto/smartloans_backend"


def test_build_session_state_commercial_target_routes_to_commercial_repos():
    state = _build_session_state(_minimal_prd(), target="commercial")
    assert state["target_repo"] == "commercial"
    assert state["GITHUB_FRONTEND_REPO"] == "montanogilberto/factory-ai-gmo-commercial"
    assert state["GITHUB_BACKEND_REPO"] == "montanogilberto/factory-ai-gmo-commercial-backend"


def test_store_prd_context_reads_target_from_state_not_hardcoded():
    """The regression this whole file exists to prevent: store_prd_context
    must respect an already-set target_repo rather than re-deriving the
    'pos' pair unconditionally."""
    tool_context = MagicMock()
    tool_context.state = {"target_repo": "commercial"}

    store_prd_context(module="pricingPlan", plural="pricingPlans", tool_context=tool_context)

    assert tool_context.state["GITHUB_FRONTEND_REPO"] == "montanogilberto/factory-ai-gmo-commercial"
    assert tool_context.state["GITHUB_BACKEND_REPO"] == "montanogilberto/factory-ai-gmo-commercial-backend"


def test_store_prd_context_defaults_to_pos_when_target_missing():
    """Backward compatibility: a session state with no target_repo key at all
    (e.g. an older caller) must behave exactly as before this change."""
    tool_context = MagicMock()
    tool_context.state = {}

    store_prd_context(module="supplier", plural="suppliers", tool_context=tool_context)

    assert tool_context.state["GITHUB_FRONTEND_REPO"] == "montanogilberto/POSVending"
    assert tool_context.state["GITHUB_BACKEND_REPO"] == "montanogilberto/smartloans_backend"


@pytest.mark.parametrize("target", sorted(_REPO_ENV_VARS))
def test_orchestrator_and_prd_parser_never_disagree(target):
    """For every known target, _build_session_state's choice must be exactly
    what store_prd_context reproduces when handed that same target_repo —
    the two are a single source of truth split across two files by
    necessity, not two independent decisions."""
    initial_state = _build_session_state(_minimal_prd(), target=target)

    tool_context = MagicMock()
    tool_context.state = dict(initial_state)
    store_prd_context(module="supplier", plural="suppliers", tool_context=tool_context)

    assert tool_context.state["GITHUB_FRONTEND_REPO"] == initial_state["GITHUB_FRONTEND_REPO"]
    assert tool_context.state["GITHUB_BACKEND_REPO"] == initial_state["GITHUB_BACKEND_REPO"]
