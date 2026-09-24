"""
Construction-layer fixes found while investigating factoryArtifact's real
run (database: 70, live SQL execution error 'CREATE/ALTER PROCEDURE must be
the first statement in a query batch'):

1. execute_sql_on_server (agents/database/rules.py) used to join create_table
   + sp_upsert + sp_all + sp_one into ONE string before splitting on GO —
   so whenever database_agent omitted a GO separator between the CREATE
   TABLE and the first CREATE PROC (every run observed so far), all of it
   landed in one batch and SQL Server rejected it. Each of the 4 params is
   already a separate structural block; the fix makes that boundary
   structural instead of dependent on the LLM remembering GO.

2. fix_database's _fix_sp_all_company_filter (agents/fixer/rules.py) was
   completely tenant_model-blind — it would unconditionally INJECT a
   companyId filter into sp_all whenever missing, with no exception for
   TENANT_INDEPENDENT modules. It never actually corrupted a real run only
   because every TENANT_INDEPENDENT sp_all observed so far already had the
   filter for an unrelated reason (database_agent's own generation bug), so
   the "already present, nothing to do" early-return masked the latent bug.
"""
from unittest.mock import MagicMock, patch

from agents.database.rules import execute_sql_on_server
from agents.fixer.rules import _fix_sp_all_company_filter, _fix_one_route_plural, fix_database


# ---------------------------------------------------------------------------
# Fix 1 — batching
# ---------------------------------------------------------------------------

def _mock_pyodbc_connect():
    """Returns (mock_connect, mock_cursor) so a test can inspect every
    cursor.execute() call without touching a real database."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False
    mock_connect = MagicMock(return_value=mock_conn)
    return mock_connect, mock_cursor


@patch.dict("os.environ", {
    "LOCAL_DB_SERVER": "x", "LOCAL_DB_NAME": "x",
    "LOCAL_DB_USER": "x", "LOCAL_DB_PASSWORD": "x",
})
def test_four_blocks_without_go_become_four_separate_batches():
    """The exact regression: no GO anywhere, but CREATE TABLE and 3 CREATE
    OR ALTER PROC blocks must still execute as 4 separate batches, not 1."""
    mock_connect, mock_cursor = _mock_pyodbc_connect()
    with patch("agents.database.rules.pyodbc.connect", mock_connect):
        execute_sql_on_server(
            create_table="CREATE TABLE dbo.Foo (fooId INT);",
            sp_upsert="CREATE OR ALTER PROC dbo.sp_foos AS BEGIN SELECT 1; END;",
            sp_all="CREATE OR ALTER PROC dbo.sp_foos_all AS BEGIN SELECT 1; END;",
            sp_one="CREATE OR ALTER PROC dbo.sp_foos_one AS BEGIN SELECT 1; END;",
        )
    assert mock_cursor.execute.call_count == 4
    executed = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert executed[0].startswith("CREATE TABLE")
    assert "sp_foos AS" in executed[1] or "sp_foos\n" in executed[1] or "sp_foos " in executed[1]
    assert "sp_foos_all" in executed[2]
    assert "sp_foos_one" in executed[3]


@patch.dict("os.environ", {
    "LOCAL_DB_SERVER": "x", "LOCAL_DB_NAME": "x",
    "LOCAL_DB_USER": "x", "LOCAL_DB_PASSWORD": "x",
})
def test_internal_go_within_a_block_still_splits():
    """A block that itself contains an internal GO must still be split —
    the fix narrows the scope of the join, it doesn't remove GO support."""
    mock_connect, mock_cursor = _mock_pyodbc_connect()
    with patch("agents.database.rules.pyodbc.connect", mock_connect):
        execute_sql_on_server(
            create_table="DROP TABLE IF EXISTS dbo.Foo;\nGO\nCREATE TABLE dbo.Foo (fooId INT);",
            sp_upsert="", sp_all="", sp_one="",
        )
    assert mock_cursor.execute.call_count == 2


# ---------------------------------------------------------------------------
# Fix 2 — fixer tenant_model awareness
# ---------------------------------------------------------------------------

_SP_ALL_WITH_COMPANY_ID = """CREATE OR ALTER PROC [dbo].[sp_foos_all] (@pjsonfile VARCHAR(MAX))
AS
SET NOCOUNT ON
BEGIN

    DECLARE @companyId INT;
    SET @companyId = TRY_CONVERT(INT,
        (SELECT TOP 1 JSON_VALUE(value, '$.companyId')
         FROM OPENJSON(@pjsonfile, '$.foos'))
    );
    SELECT [fooId]
    FROM dbo.Foos
    WHERE [companyId] = @companyId
    FOR JSON AUTO, ROOT('foos');
END;
"""


def test_tenant_independent_removes_existing_company_filter():
    fixed, fixes = _fix_sp_all_company_filter(_SP_ALL_WITH_COMPANY_ID, "foos", tenant_independent=True)
    assert "@companyId" not in fixed
    assert "WHERE" not in fixed.upper() or "companyId" not in fixed
    assert any("Removed" in f for f in fixes)


def test_tenant_scoped_still_ensures_company_filter_present_unchanged():
    """Regression: default (tenant_independent=False) behavior must be
    byte-for-byte the same as before this fix existed."""
    sp_all_missing = "CREATE OR ALTER PROC [dbo].[sp_foos_all] (@pjsonfile VARCHAR(MAX))\nAS\nBEGIN\n    SELECT 1 FOR JSON AUTO;\nEND;"
    fixed, fixes = _fix_sp_all_company_filter(sp_all_missing, "foos", tenant_independent=False)
    assert "@companyId" in fixed
    assert "WHERE [companyId] = @companyId" in fixed


def test_tenant_scoped_already_correct_is_a_noop():
    fixed, fixes = _fix_sp_all_company_filter(_SP_ALL_WITH_COMPANY_ID, "foos", tenant_independent=False)
    assert fixed == _SP_ALL_WITH_COMPANY_ID
    assert fixes == []


# ---------------------------------------------------------------------------
# Fix 3 — backend /one_{module} singular-route naturalization
# ---------------------------------------------------------------------------

_ROUTE_WITH_SINGULAR_ONE = '''from fastapi import APIRouter
from modules.factoryArtifacts import factoryArtifacts_sp, all_factoryArtifacts_sp, one_factoryArtifacts_sp

router = APIRouter()

@router.post("/factoryArtifacts", summary="FactoryArtifacts CRUD")
def factoryArtifacts(json: dict):
    return factoryArtifacts_sp(json)

@router.post("/all_factoryArtifacts", summary="all FactoryArtifacts")
def all_factoryArtifacts(json: dict):
    return all_factoryArtifacts_sp(json)

@router.post("/one_factoryArtifact", summary="one factoryArtifact")
def one_factoryArtifact(json: dict):
    return one_factoryArtifacts_sp(json)
'''


def test_fix_one_route_plural_corrects_real_observed_defect():
    fixed, fixes = _fix_one_route_plural(_ROUTE_WITH_SINGULAR_ONE, "factoryArtifact", "factoryArtifacts")
    assert '@router.post("/one_factoryArtifacts"' in fixed
    assert "def one_factoryArtifacts(" in fixed
    assert len(fixes) == 2
    # The already-correct plural SP call must be untouched, not doubled up.
    assert "one_factoryArtifacts_sp(json)" in fixed
    assert "one_factoryArtifacts_sp_sp" not in fixed


def test_fix_one_route_plural_noop_when_already_plural():
    already_correct = _ROUTE_WITH_SINGULAR_ONE.replace("one_factoryArtifact\"", "one_factoryArtifacts\"").replace(
        "def one_factoryArtifact(", "def one_factoryArtifacts("
    )
    fixed, fixes = _fix_one_route_plural(already_correct, "factoryArtifact", "factoryArtifacts")
    assert fixed == already_correct
    assert fixes == []


def test_fix_database_wires_tenant_model_from_gate_result():
    """End-to-end through fix_database, not just the inner helper — proves
    the gate_result.tenant_model key actually reaches the fixer."""
    db_artifacts = {
        "create_table": "CREATE TABLE dbo.Foos (fooId INT);",
        "sp_all": _SP_ALL_WITH_COMPANY_ID,
        "sp_one": "",
        "sp_upsert": "",
    }
    gate_result = {"tier": "TIER_1_CATALOG", "tenant_model": "TENANT_INDEPENDENT", "_module": "foo"}
    fixed_artifacts, fixes = fix_database(db_artifacts, gate_result)
    assert "@companyId" not in fixed_artifacts["sp_all"]
