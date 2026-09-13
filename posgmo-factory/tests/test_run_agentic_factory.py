"""Phase 8 — the feature-flagged bridge to the real factory. No real LLM
calls (run_debate is mocked) and the real factory (orchestrator.run_factory,
which ends in a GitHub push) is ALSO mocked in every case — these tests
prove the gating logic never calls it unless every condition is met AND
--execute was passed, without ever risking a real push."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from debate_schema import Decision, DebateStatus, seed_blackboard_state, write_status
from run_agentic_factory import run_agentic_gate


def _escalated_state(request="make it better"):
    state = seed_blackboard_state()
    state["request"] = request
    state["status"] = write_status(DebateStatus(
        needs_user_input=True, escalation_reason="too vague", open_questions=["Which module?"],
    ))
    return state


def _converged_state(request="create a new module for rewards", claim="Extend existing capability"):
    state = seed_blackboard_state()
    state["request"] = request
    decision = Decision(round=4, selected_claim=claim, rationale="because evidence",
                         evidence=["repo:a"], confidence=0.9)
    state["decisions"] = json.dumps([decision.model_dump(mode="json")])
    state["status"] = write_status(DebateStatus(round=4, confidence=0.9, needs_user_input=False))
    return state


def _valid_prd_file(tmp_path):
    prd = {
        "module": "supplier", "description": "Manages product suppliers for POS GMO companies.",
        "fields": [{"name": "supplierName", "type": "string"}],
    }
    path = tmp_path / "prd_supplier.json"
    path.write_text(json.dumps(prd), encoding="utf-8")
    return path


def test_escalated_debate_stops_before_any_prd_or_factory_step(tmp_path):
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_escalated_state())), \
         patch("orchestrator.run_factory", new=AsyncMock()) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("make it better", prd_path=None, execute=True))
    assert exit_code == 1
    mock_factory.assert_not_called()


def test_converged_debate_without_prd_does_not_call_factory():
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_converged_state())), \
         patch("orchestrator.run_factory", new=AsyncMock()) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("create a new module for rewards", prd_path=None, execute=True))
    assert exit_code == 0
    mock_factory.assert_not_called()


def test_converged_debate_with_valid_prd_but_no_execute_flag_is_a_dry_run(tmp_path):
    prd_path = _valid_prd_file(tmp_path)
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_converged_state())), \
         patch("orchestrator.run_factory", new=AsyncMock()) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("create a new module for rewards", prd_path=prd_path, execute=False))
    assert exit_code == 0
    mock_factory.assert_not_called()  # the whole point of the default: nothing runs


def test_converged_debate_with_valid_prd_and_execute_calls_the_real_factory_exactly_once(tmp_path):
    prd_path = _valid_prd_file(tmp_path)
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_converged_state())), \
         patch("orchestrator.run_factory", new=AsyncMock(return_value={"ok": True})) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("create a new module for rewards", prd_path=prd_path, execute=True))
    assert exit_code == 0
    mock_factory.assert_called_once()
    called_prd = mock_factory.call_args.args[0]
    assert called_prd["module"] == "supplier"


def test_invalid_prd_never_reaches_the_factory_even_with_execute(tmp_path):
    bad_path = tmp_path / "bad_prd.json"
    bad_path.write_text(json.dumps({"module": "Bad", "description": "x", "fields": []}), encoding="utf-8")
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_converged_state())), \
         patch("orchestrator.run_factory", new=AsyncMock()) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("create a new module for rewards", prd_path=bad_path, execute=True))
    assert exit_code == 1
    mock_factory.assert_not_called()


def test_missing_prd_file_never_reaches_the_factory(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with patch("run_agentic_factory.run_debate", new=AsyncMock(return_value=_converged_state())), \
         patch("orchestrator.run_factory", new=AsyncMock()) as mock_factory:
        exit_code = asyncio.run(run_agentic_gate("create a new module for rewards", prd_path=missing, execute=True))
    assert exit_code == 1
    mock_factory.assert_not_called()
