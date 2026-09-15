"""Tests for ecosystem_graph.sql_dependencies against the live SQL Server.

Covers step 16F's "backend route -> stored procedure -> database table"
final hop. This is the one ecosystem_graph layer with no offline mode by
design (see its module docstring: querying sys.sql_expression_dependencies
is the whole point, precisely because .sql files can drift from what's
deployed) — so unlike the other extractor tests, this cannot fall back to
a static fixture without defeating its own purpose.

Skips cleanly (rather than failing) when LOCAL_DB_* credentials aren't
available in this environment, e.g. in CI that doesn't have network access
to the production DB.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from ecosystem_graph.sql_dependencies import get_sp_table_dependencies


def _live_db_available() -> bool:
    try:
        from agents.schema_analyst.rules import _connect
        conn = _connect()
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _live_db_available(),
    reason="no live SQL Server connection available in this environment",
)


def test_sp_clients_reads_the_clients_table():
    """sp_clients is a simple read/write against dbo.clients — the DMV
    query should surface at least that dependency (it may also surface
    others sp_clients happens to reference; this only asserts the one
    dependency this task has independently verified elsewhere in this
    session, not an exhaustive list)."""
    deps = get_sp_table_dependencies(["sp_clients"])
    tables = {d["table"] for d in deps if d["procedure"] == "sp_clients"}
    assert "clients" in tables
    # Every row from this live query is VERIFIED by construction -- there
    # is no "unresolved" case for a DMV-sourced edge.
    assert all(d["confidence"] == "VERIFIED" for d in deps)


def test_unknown_procedure_returns_empty_not_an_error():
    deps = get_sp_table_dependencies(["sp_this_procedure_does_not_exist_xyz"])
    assert deps == []


def test_scoping_by_name_returns_only_requested_procedures():
    deps = get_sp_table_dependencies(["sp_clients", "sp_clients_all"])
    procs = {d["procedure"] for d in deps}
    assert procs <= {"sp_clients", "sp_clients_all"}
