# Database Agent — tool functions.
# execute_sql_on_server runs generated DDL/SPs against live SQL Server.

import os
import re

import pyodbc



def execute_sql_on_server(
    create_table: str,
    sp_upsert: str,
    sp_all: str,
    sp_one: str,
) -> dict:
    """
    Executes the generated CREATE TABLE and three stored procedures directly
    against the POS GMO SQL Server using credentials from environment variables.

    Each statement is split on GO and executed individually, which is required
    by pyodbc (it does not support GO as a batch separator).

    Args:
        create_table: Full SQL for CREATE TABLE + indexes.
        sp_upsert:    Full SQL for sp_{plural} (INSERT/UPDATE/DELETE).
        sp_all:       Full SQL for sp_{plural}_all.
        sp_one:       Full SQL for sp_{plural}_one.

    Returns:
        dict with "success" bool and "details" list of per-statement results.
    """
    server   = os.environ["LOCAL_DB_SERVER"]
    database = os.environ["LOCAL_DB_NAME"]
    user     = os.environ["LOCAL_DB_USER"]
    password = os.environ["LOCAL_DB_PASSWORD"]

    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};DATABASE={database};"
        f"UID={user};PWD={password};"
        "TrustServerCertificate=yes;"
    )

    # Each of the 4 params is ALREADY a separate structural block (CREATE
    # TABLE vs. 3 independent CREATE OR ALTER PROC statements) — they must
    # never be joined into one string before batching. CREATE/ALTER
    # PROCEDURE (and VIEW/FUNCTION/TRIGGER) must be the first statement in
    # its own batch; joining all 4 blocks together and relying on
    # database_agent to have remembered a GO separator between CREATE TABLE
    # and the first CREATE PROC produced exactly that error live (factoryRun,
    # factoryArtifact) whenever the LLM omitted GO, which was every run
    # observed so far. Splitting per-block first, THEN on internal GO within
    # each block, makes each block's own batch boundary structural instead
    # of dependent on LLM compliance — still honors extra GO markers a block
    # might contain internally.
    def _split_on_go(sql: str) -> list[str]:
        return [b.strip() for b in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE) if b.strip()]

    batches: list[str] = []
    for block in (create_table, sp_upsert, sp_all, sp_one):
        batches.extend(_split_on_go(block))

    # SQL Server error numbers that mean "already exists" — safe to skip on re-runs
    _ALREADY_EXISTS_CODES = {
        2714,   # object with that name already exists
        1913,   # index with that name already exists
        2705,   # column name already exists
    }

    details = []
    try:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            cursor = conn.cursor()
            for batch in batches:
                try:
                    cursor.execute(batch)
                    details.append({"status": "ok", "batch_preview": batch[:80]})
                except pyodbc.Error as e:
                    err_str = str(e)
                    # Extract SQL Server native error number (last number in the tuple repr)
                    native = None
                    try:
                        native = int(re.search(r"\((\d+)\) \(SQL", err_str).group(1))
                    except Exception:
                        pass
                    if native in _ALREADY_EXISTS_CODES:
                        details.append({"status": "skipped (already exists)", "batch_preview": batch[:80]})
                    else:
                        details.append({"status": "error", "message": err_str, "batch_preview": batch[:80]})
        success = all(d["status"] in ("ok", "skipped (already exists)") for d in details)
        return {"success": success, "details": details}
    except pyodbc.Error as e:
        return {"success": False, "details": [{"status": "connection_error", "message": str(e)}]}
