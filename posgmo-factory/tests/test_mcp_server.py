"""Smoke tests for the MCP server — verifies every tool returns valid data."""

import pytest
import sys
from pathlib import Path

# Make the factory root importable when running from the tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

import decision_registry
from debate_schema import Decision
from mcp_server.server import (
    get_frontend_patterns,
    get_api_contracts,
    get_ui_patterns,
    get_component_catalog,
    get_backend_patterns,
    get_backend_routes,
    get_sp_patterns,
    get_db_schema,
    get_table_list,
    get_table_columns,
    get_relationships_for_table,
    get_generation_rules,
    get_decisions,
    get_decisions_for_module,
    search_decisions,
)


@pytest.fixture(autouse=True)
def _isolated_decision_registry(tmp_path, monkeypatch):
    """These decision-tool tests write real ADRs — isolate from the real
    decision_registry/ the same way tests/test_run_agentic_factory.py does."""
    monkeypatch.setattr(decision_registry, "_REGISTRY_DIR", tmp_path / "decision_registry")


def test_get_frontend_patterns_has_required_keys():
    result = get_frontend_patterns()
    assert "architecture" in result
    assert "modules" in result
    assert "routes" in result
    assert "ui_patterns" in result
    assert "components" in result


def test_get_api_contracts_is_list():
    result = get_api_contracts()
    assert isinstance(result, list)
    assert len(result) > 0


def test_get_ui_patterns_has_utc_pattern():
    patterns = get_ui_patterns()
    ids = [p["patternId"] for p in patterns]
    assert "utc_timezone_normalization" in ids


def test_get_component_catalog_not_empty():
    result = get_component_catalog()
    assert len(result) > 0


def test_get_backend_patterns_has_required_keys():
    result = get_backend_patterns()
    assert "architecture" in result
    assert "models" in result


def test_get_backend_routes_is_list():
    routes = get_backend_routes()
    assert isinstance(routes, list)
    assert any(r["path"] == "/products" for r in routes)


def test_get_sp_patterns_is_list():
    sps = get_sp_patterns()
    assert isinstance(sps, list)
    names = [sp["name"] for sp in sps]
    assert "sp_login" in names


def test_get_db_schema_has_columns_and_relationships():
    schema = get_db_schema()
    assert "columns" in schema
    assert "relationships" in schema
    assert len(schema["columns"]) > 0


def test_get_table_list_contains_known_tables():
    tables = get_table_list()
    assert "products" in tables
    assert "users" in tables
    assert "income" in tables
    assert "cashRegisterSessions" in tables


def test_get_table_columns_returns_columns():
    cols = get_table_columns("users")
    col_names = [c["column"] for c in cols]
    assert "userId" in col_names
    assert "email" in col_names


def test_get_table_columns_unknown_table_returns_empty():
    cols = get_table_columns("nonexistentTable")
    assert cols == []


def test_get_relationships_for_income():
    rels = get_relationships_for_table("income")
    assert "as_parent" in rels
    assert "as_child" in rels
    # income is parent of incomeDetails
    parent_children = [r["child_table"] for r in rels["as_parent"]]
    assert "incomeDetails" in parent_children


def test_get_generation_rules_has_all_sections():
    rules = get_generation_rules()
    assert "global" in rules
    assert "database" in rules
    assert "backend" in rules
    assert "frontend" in rules
    assert "reviewer_thresholds" in rules
    assert rules["reviewer_thresholds"]["min_score_to_pass"] == 90


def _make_decision(claim="Reward events must reference incomeId", confidence=0.88):
    return Decision(
        round=2, selected_claim=claim, rationale="Prevents orphaned reward events",
        evidence=["repo:modules/rewards.py"], confidence=confidence, decided_by="debate",
    )


def test_get_decisions_empty_registry_returns_empty_list():
    assert get_decisions() == []


def test_get_decisions_returns_recorded_decision():
    decision_registry.record_decision(request="add rewards redemption", decision=_make_decision(), module="posRewardTransaction")
    results = get_decisions()
    assert len(results) == 1
    assert results[0]["id"] == "ADR-001"
    assert results[0]["module"] == "posRewardTransaction"


def test_get_decisions_for_module_filters_case_insensitively():
    decision_registry.record_decision(request="add rewards redemption", decision=_make_decision(), module="posRewardTransaction")
    decision_registry.record_decision(request="add supplier payments", decision=_make_decision("Use DECIMAL(10,2) for money"), module="supplier")

    matches = get_decisions_for_module("POSREWARDTRANSACTION")
    assert len(matches) == 1
    assert matches[0]["module"] == "posRewardTransaction"

    assert get_decisions_for_module("nonexistentModule") == []


def test_search_decisions_matches_keyword_in_claim():
    decision_registry.record_decision(request="add rewards redemption", decision=_make_decision(), module="posRewardTransaction")
    assert len(search_decisions("reward")) == 1
    assert search_decisions("nonexistent-keyword-xyz") == []
