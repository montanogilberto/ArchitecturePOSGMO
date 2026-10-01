"""Read-only lookup of the target table in the live SQL Server.

Used by database_agent before rendering SQL: when the table already exists,
its live columns/PK are authoritative over the architect's specification.
Best-effort -- returns None when the table doesn't exist OR the lookup
fails (the stage then renders from the spec, as before).
"""
from __future__ import annotations

from typing import Optional

_COLUMNS_SQL = """
SELECT c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION,
       c.NUMERIC_SCALE, c.IS_NULLABLE,
       COLUMNPROPERTY(OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)),
                      c.COLUMN_NAME, 'IsIdentity') AS is_identity,
       CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_pk
FROM INFORMATION_SCHEMA.COLUMNS c
LEFT JOIN (
    SELECT ku.TABLE_NAME, ku.COLUMN_NAME
    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
WHERE c.TABLE_SCHEMA = 'dbo' AND c.TABLE_NAME = ?
ORDER BY c.ORDINAL_POSITION
"""


def live_table_columns(table: str) -> Optional[list[dict]]:
    if not table:
        return None
    try:
        from agents.schema_analyst.rules import _connect

        with _connect() as conn:
            rows = conn.cursor().execute(_COLUMNS_SQL, table).fetchall()
    except Exception as e:  # noqa: BLE001 -- best-effort by design
        print(f"[database_agent] live schema lookup unavailable: {str(e)[:120]}", flush=True)
        return None
    if not rows:
        return None
    return [
        {"name": r[0], "type": r[1], "max_length": r[2], "precision": r[3], "scale": r[4],
         "nullable": r[5] == "YES", "is_identity": bool(r[6]), "is_pk": bool(r[7])}
        for r in rows
    ]
