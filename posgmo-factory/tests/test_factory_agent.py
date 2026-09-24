"""
factory_agent.py — Phase 5's closed-loop orchestration.

_build_prd (the only function that makes a live LLM call) is mocked here so
this file stays fast and deterministic — the actual end-to-end proof (a real
raw request producing a real PRD and a real construction result) is a live
run, documented in docs/factory-knowledge-roadmap.md's Phase 5 section, not
reproduced as a mocked "integration" test that wouldn't prove anything real
anyway.

What IS tested here deterministically: the three-way response routing
(clarifying question vs. invalid PRD vs. constructed) that run_factory_agent
uses to decide what to do with prd_builder_agent's raw text output — this is
real branching logic with real failure modes (a malformed JSON response, or
one that fails the strict PRDInput schema), not just plumbing.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from factory_agent import run_factory_agent


@pytest.mark.asyncio
async def test_clarifying_question_short_circuits_before_construction():
    """A response not starting with '{' is prd_builder_agent's own
    documented convention for 'I need more info' — must never be parsed as
    JSON or fed into construction."""
    with patch("factory_agent._build_prd", new=AsyncMock(return_value="What module do you want to build?")):
        result = await run_factory_agent("something vague")
    assert result["status"] == "needs_clarification"
    assert result["question"] == "What module do you want to build?"


@pytest.mark.asyncio
async def test_malformed_json_reported_as_prd_invalid_not_raised():
    with patch("factory_agent._build_prd", new=AsyncMock(return_value="{not valid json")):
        result = await run_factory_agent("something")
    assert result["status"] == "prd_invalid"
    assert "not valid JSON" in result["errors"]


@pytest.mark.asyncio
async def test_schema_violation_reported_as_prd_invalid_not_raised():
    """The exact real failure mode Phase 4 found and closed: valid JSON
    that violates PRDInput's strict schema (e.g. an extra top-level key)
    must be caught here, not silently passed through to construction."""
    bad_prd = json.dumps({
        "module": "widget", "description": "x" * 20,
        "fields": [{"name": "a", "type": "string"}],
        "CONSTRAINTS": ["this key doesn't belong at the top level"],
    })
    with patch("factory_agent._build_prd", new=AsyncMock(return_value=bad_prd)):
        result = await run_factory_agent("something")
    assert result["status"] == "prd_invalid"
    assert "extra" in result["errors"].lower() or "CONSTRAINTS" in result["errors"]


@pytest.mark.asyncio
async def test_valid_prd_proceeds_to_construction_and_refreshes_memory():
    good_prd = {
        "module": "widget",
        "description": "A widget module description long enough to pass validation here.",
        "fields": [{"name": "widgetName", "type": "string", "required": True, "max_length": 100}],
    }
    fake_state = {"review_result": json.dumps({"scores": {"backend": 100}, "passed": False})}

    with patch("factory_agent._build_prd", new=AsyncMock(return_value=json.dumps(good_prd))), \
         patch("factory_agent.run_local", new=AsyncMock(return_value=fake_state)), \
         patch("factory_agent.factory_experience.build_index", return_value={"chunks": 10}), \
         patch("factory_agent.Path.exists", return_value=True):  # don't touch tests/prd_widget.json
        result = await run_factory_agent("build a widget module")

    assert result["status"] == "constructed"
    assert result["module"] == "widget"
    assert result["review_result"]["scores"]["backend"] == 100
    assert result["memory_refreshed"] is True


@pytest.mark.asyncio
async def test_memory_refresh_failure_does_not_mask_construction_result():
    """A best-effort step failing must never be reported as if construction
    itself failed — the construction result is already final by the time
    Factory Memory refresh runs."""
    good_prd = {
        "module": "widget",
        "description": "A widget module description long enough to pass validation here.",
        "fields": [{"name": "widgetName", "type": "string", "required": True, "max_length": 100}],
    }
    fake_state = {"review_result": json.dumps({"scores": {"backend": 100}, "passed": True})}

    with patch("factory_agent._build_prd", new=AsyncMock(return_value=json.dumps(good_prd))), \
         patch("factory_agent.run_local", new=AsyncMock(return_value=fake_state)), \
         patch("factory_agent.factory_experience.build_index", side_effect=RuntimeError("embedding API down")), \
         patch("factory_agent.Path.exists", return_value=True):
        result = await run_factory_agent("build a widget module")

    assert result["status"] == "constructed"
    assert result["review_result"]["passed"] is True
    assert result["memory_refreshed"] is False
    assert "embedding API down" in result["memory_error"]
