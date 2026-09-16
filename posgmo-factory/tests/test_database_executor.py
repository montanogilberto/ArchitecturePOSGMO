"""
database_executor_agent's deterministic merge logic — no LLM, no live DB
(execute_sql_on_server is mocked). See agents/database_executor/rules.py for
why this step exists: database_agent used to call execute_sql_on_server
itself as a tool taking four large SQL strings as arguments, which was
traced to its chronic MALFORMED_FUNCTION_CALL failures
(docs/experiment1-leadCapture-evaluation.md). Now database_agent only writes
SQL as text; this module executes it separately, as plain Python.
"""
import json
from unittest.mock import patch

from agents.database_executor.rules import merge_execution_result


def test_empty_database_artifacts_returns_empty():
    assert merge_execution_result({"database_artifacts": ""}) == {}
    assert merge_execution_result({"database_artifacts": "{}"}) == {}
    assert merge_execution_result({}) == {}


def test_non_crud_shape_is_left_untouched_no_execution_attempted():
    """ACTION_ROUTER/BUSINESS_LOGIC/BLOB_UPLOAD artifacts don't have all four
    required keys -- execute_sql_on_server only knows the CRUD shape, so
    these must pass through unexecuted rather than crash or guess."""
    action_router_artifact = {
        "create_table": "CREATE TABLE ...",
        "sp_action_router": "CREATE PROCEDURE sp_module ...",
    }
    with patch("agents.database_executor.rules.execute_sql_on_server") as mock_exec:
        result = merge_execution_result({"database_artifacts": json.dumps(action_router_artifact)})
        mock_exec.assert_not_called()
    assert result == action_router_artifact
    assert "execution" not in result


def test_crud_shape_executes_and_merges_result():
    artifact = {
        "create_table": "CREATE TABLE dbo.Foo (id INT);",
        "sp_upsert": "CREATE PROCEDURE sp_foos ...",
        "sp_all": "CREATE PROCEDURE sp_foos_all ...",
        "sp_one": "CREATE PROCEDURE sp_foos_one ...",
    }
    fake_result = {"success": True, "details": [{"status": "ok", "batch_preview": "CREATE TABLE..."}]}
    with patch("agents.database_executor.rules.execute_sql_on_server", return_value=fake_result) as mock_exec:
        result = merge_execution_result({"database_artifacts": json.dumps(artifact)})
        mock_exec.assert_called_once_with(
            artifact["create_table"], artifact["sp_upsert"], artifact["sp_all"], artifact["sp_one"],
        )
    assert result["execution"] == fake_result
    # Original SQL fields must survive untouched.
    for key in ("create_table", "sp_upsert", "sp_all", "sp_one"):
        assert result[key] == artifact[key]


def test_handles_markdown_fenced_json():
    artifact = {
        "create_table": "CREATE TABLE dbo.Foo (id INT);",
        "sp_upsert": "x", "sp_all": "y", "sp_one": "z",
    }
    fenced = "```json\n" + json.dumps(artifact) + "\n```"
    fake_result = {"success": True, "details": []}
    with patch("agents.database_executor.rules.execute_sql_on_server", return_value=fake_result):
        result = merge_execution_result({"database_artifacts": fenced})
    assert result["execution"] == fake_result
