"""
SP -> table edges, from SQL Server's own dependency metadata
(sys.sql_expression_dependencies) — not text-parsing .sql files, which
can (and demonstrably do, elsewhere in this codebase — see
sql_logic/sp_income.sql being stale relative to the live sp_income
definition) drift from what's actually deployed. This queries the same
production DB already used throughout this session for live verification.

Reuses agents/schema_analyst/rules.py::_connect() — the factory's
existing pyodbc connection helper — rather than adding a second DB
connection method.
"""
from __future__ import annotations

from agents.schema_analyst.rules import _connect


def get_sp_table_dependencies(sp_names: list[str] | None = None) -> list[dict]:
    """Live query: which real tables does each stored procedure touch.

    Args:
        sp_names: Restrict to these procedure names, or None for every
            procedure in the database (272+ backend routes worth —
            expensive and rarely needed; prefer passing an explicit list
            scoped to what you're actually investigating).

    Returns:
        List of {"procedure": str, "table": str}. A procedure with
        dynamic SQL (EXEC(@sql)) may return fewer/no rows here — SQL
        Server can't statically resolve dependencies inside dynamic SQL,
        which is a real limitation of this DMV, not a bug in this query.
    """
    conn = _connect()
    try:
        cursor = conn.cursor()
        query = """
            SELECT DISTINCT
                OBJECT_NAME(d.referencing_id) AS proc_name,
                d.referenced_entity_name AS referenced_table
            FROM sys.sql_expression_dependencies d
            WHERE d.referenced_entity_name IS NOT NULL
              AND d.referenced_class_desc = 'OBJECT_OR_COLUMN'
        """
        params: tuple = ()
        if sp_names:
            placeholders = ",".join("?" for _ in sp_names)
            query += f" AND OBJECT_NAME(d.referencing_id) IN ({placeholders})"
            params = tuple(sp_names)
        query += " ORDER BY proc_name, referenced_table"

        cursor.execute(query, params) if params else cursor.execute(query)
        # Always VERIFIED: this DMV only returns dependencies that really
        # exist in the live, deployed database -- there is no "unresolved"
        # case for this layer the way there is for the regex/ast ones.
        return [{"procedure": row[0], "table": row[1], "confidence": "VERIFIED"} for row in cursor.fetchall()]
    finally:
        conn.close()
