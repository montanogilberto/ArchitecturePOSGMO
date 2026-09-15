"""Decision Gate surfaces prior Decision Registry entries for the module
being generated — a pure lookup (no semantic judgment) threaded into
gate_result so every downstream agent that already reads gate_result can
see it, the same way mandatory_constraints already is."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import decision_registry
from debate_schema import Decision
from agents.decision_gate.rules import compute_gate_result


@pytest.fixture(autouse=True)
def _isolated_decision_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_registry, "_REGISTRY_DIR", tmp_path / "decision_registry")


def _state(module: str) -> dict:
    spec = {
        "module": module,
        "description": "Tracks reward point transactions",
        "db": {"columns": [{"name": "amount", "sql_type": "decimal(10,2)", "fk_table": None}]},
    }
    return {
        "specification": json.dumps(spec),
        "schema_analysis": json.dumps({"valid_fk_targets": []}),
    }


def test_gate_result_includes_empty_applicable_decisions_when_none_recorded():
    result = compute_gate_result(_state("posRewardTransaction"))
    assert result["status"] == "APPROVED"
    assert result["applicable_decisions"] == []


def test_gate_result_surfaces_a_recorded_decision_for_the_matching_module():
    decision = Decision(
        round=2, selected_claim="Reward events must reference incomeId",
        rationale="Prevents orphaned reward events", evidence=["repo:modules/rewards.py"],
        confidence=0.88, decided_by="debate",
    )
    decision_registry.record_decision(request="add rewards redemption", decision=decision, module="posRewardTransaction")

    result = compute_gate_result(_state("posRewardTransaction"))
    assert len(result["applicable_decisions"]) == 1
    assert result["applicable_decisions"][0]["id"] == "ADR-001"
    assert any("ADR-001" in w for w in result["warnings"])


def test_gate_result_does_not_leak_decisions_from_a_different_module():
    decision = Decision(
        round=2, selected_claim="Reward events must reference incomeId",
        rationale="Prevents orphaned reward events", evidence=[], confidence=0.88, decided_by="debate",
    )
    decision_registry.record_decision(request="add rewards redemption", decision=decision, module="posRewardTransaction")

    result = compute_gate_result(_state("supplier"))
    assert result["applicable_decisions"] == []
    assert not any("ADR-" in w for w in result["warnings"])


def test_blocked_gate_result_still_has_applicable_decisions_key():
    state = _state("posRewardTransaction")
    # invalid FK target triggers the hard block path
    spec = json.loads(state["specification"])
    spec["db"]["columns"].append({"name": "incomeId", "sql_type": "int", "fk_table": "income"})
    state["specification"] = json.dumps(spec)

    result = compute_gate_result(state)
    assert result["status"] == "BLOCKED"
    assert result["applicable_decisions"] == []
