# Schema Analyst — tool functions.
# Extracted for package structure.

from __future__ import annotations

import json
import os
from typing import Any

import pyodbc
from google.adk.tools.tool_context import ToolContext


# ---------------------------------------------------------------------------
# DB connection helper (same pattern as database_agent)
# ---------------------------------------------------------------------------

def _connect() -> pyodbc.Connection:
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
    return pyodbc.connect(conn_str, timeout=15)


# ---------------------------------------------------------------------------
# Analysis tool
# ---------------------------------------------------------------------------

def analyze_database_schema(module: str, plural: str, tool_context: ToolContext) -> dict:
    """
    Queries the live SQL Server and returns a full schema analysis for the
    incoming module. Stores results in session state under 'db_context'.

    Args:
        module: Singular camelCase module name, e.g. "supplier".
        plural: Plural table name, e.g. "suppliers".

    Returns:
        dict with keys: tables, foreign_keys, indexes, conflicts, suggestions
    """
    try:
        conn   = _connect()
        cursor = conn.cursor()

        # ── 1. All tables ────────────────────────────────────────────────
        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        all_tables = [row[0] for row in cursor.fetchall()]

        # ── 2. All columns (grouped by table) ───────────────────────────
        cursor.execute("""
            SELECT
                c.TABLE_NAME,
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT,
                CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END AS IS_PK
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.TABLE_NAME, ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
            ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
        """)
        columns_by_table: dict[str, list[dict]] = {}
        for row in cursor.fetchall():
            tbl = row[0]
            if tbl not in columns_by_table:
                columns_by_table[tbl] = []
            columns_by_table[tbl].append({
                "name":       row[1],
                "type":       row[2],
                "max_length": row[3],
                "nullable":   row[4] == "YES",
                "default":    row[5],
                "is_pk":      row[6] == "YES",
            })

        # ── 3. All FK relationships ──────────────────────────────────────
        cursor.execute("""
            SELECT
                fk.name                          AS fk_name,
                tp.name                          AS parent_table,
                cp.name                          AS parent_column,
                tr.name                          AS referenced_table,
                cr.name                          AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            JOIN sys.tables tp  ON fkc.parent_object_id      = tp.object_id
            JOIN sys.columns cp ON fkc.parent_object_id      = cp.object_id
                                AND fkc.parent_column_id     = cp.column_id
            JOIN sys.tables tr  ON fkc.referenced_object_id  = tr.object_id
            JOIN sys.columns cr ON fkc.referenced_object_id  = cr.object_id
                                AND fkc.referenced_column_id = cr.column_id
            ORDER BY tp.name, fk.name
        """)
        foreign_keys: list[dict] = []
        for row in cursor.fetchall():
            foreign_keys.append({
                "fk_name":          row[0],
                "parent_table":     row[1],
                "parent_column":    row[2],
                "referenced_table": row[3],
                "referenced_col":   row[4],
            })

        # ── 4. Indexes ───────────────────────────────────────────────────
        cursor.execute("""
            SELECT
                t.name  AS table_name,
                i.name  AS index_name,
                i.is_unique,
                STRING_AGG(c.name, ', ') WITHIN GROUP (ORDER BY ic.key_ordinal) AS columns
            FROM sys.indexes i
            JOIN sys.tables t       ON i.object_id    = t.object_id
            JOIN sys.index_columns ic ON i.object_id  = ic.object_id
                                     AND i.index_id   = ic.index_id
            JOIN sys.columns c      ON ic.object_id   = c.object_id
                                     AND ic.column_id = c.column_id
            WHERE i.is_primary_key = 0
              AND i.type > 0
            GROUP BY t.name, i.name, i.is_unique
            ORDER BY t.name, i.name
        """)
        indexes: list[dict] = []
        for row in cursor.fetchall():
            indexes.append({
                "table":     row[0],
                "index":     row[1],
                "is_unique": bool(row[2]),
                "columns":   row[3],
            })

        cursor.close()
        conn.close()

    except Exception as e:
        return {"error": str(e), "tables": [], "foreign_keys": [], "indexes": []}

    # ── 5. Table existence check (informational only — not a block) ────────
    target_table = plural[0].upper() + plural[1:]   # e.g. "Suppliers"
    table_already_exists = target_table in all_tables or plural in all_tables

    # ── 6. Smart FK suggestions ──────────────────────────────────────────
    # Tables that likely make sense as parents for ANY new module
    always_relevant = {"Companies", "Users", "Roles"}
    # Tables whose name overlaps with the module's description
    suggestions: list[dict] = []
    for tbl in all_tables:
        if tbl in always_relevant or tbl.lower() in plural.lower() or plural.lower() in tbl.lower():
            pk_cols = [c["name"] for c in columns_by_table.get(tbl, []) if c["is_pk"]]
            suggestions.append({
                "table":  tbl,
                "pk":     pk_cols[0] if pk_cols else None,
                "reason": "always required" if tbl in always_relevant else "name similarity",
            })

    # ── 7. Build compact table summary (for Architect context) ──────────
    table_summary: list[dict] = []
    for tbl in all_tables:
        cols = columns_by_table.get(tbl, [])
        table_summary.append({
            "table":   tbl,
            "columns": [f"{c['name']} ({c['type']}{'  PK' if c['is_pk'] else ''})" for c in cols],
        })

    result: dict[str, Any] = {
        "module":          module,
        "plural":          plural,
        "target_table":    target_table,
        "table_already_exists": table_already_exists,
        "all_tables":           all_tables,
        "table_details":        table_summary,
        "foreign_keys":         foreign_keys,
        "indexes":              indexes,
        "fk_suggestions":       suggestions,
        "analysis_notes":       (
            f"Table '{target_table}' already exists — database agent will use CREATE OR ALTER."
            if table_already_exists else
            f"Table '{target_table}' is available for creation."
        ),
    }

    # Store in session state for Architect to read
    tool_context.state["db_context"] = json.dumps(result, default=str)
    return result


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------
