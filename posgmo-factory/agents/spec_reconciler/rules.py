"""
Spec reconciliation — deterministic, zero LLM.

When the module's table already exists in the live database, the live
table outranks the architect's specification (authority order: MCP / live
schema first). Found live (Step 1 evidence, posRewardCatalogItem): across
two real runs the architect declared the same existing table's PK first as
catalogItemId (matches live), then as posRewardCatalogItemId (invented).
Every SP of the second run failed with "Invalid column name", and backend /
frontend would have sent the invented key too -- so the correction has to
happen on `specification` itself, before any construction agent reads it,
not inside one layer.

Spec columns the live table lacks are dropped from db.columns (no layer can
store them without a migration) and listed under db.schema_drift, which the
reviewer turns into an explicit "needs a migration decision" error.
"""
from __future__ import annotations

import json

from agents.database.live_schema import live_table_columns
from agents.database.sql_templates import _safe_load, reconcile_with_live


def reconcile_specification(state: dict, lookup=live_table_columns) -> tuple[dict | None, dict]:
    """Returns (reconciled spec or None when unchanged, record for state)."""
    spec, gate = _safe_load(state.get("specification")), _safe_load(state.get("gate_result"))
    table = spec.get("db", {}).get("table_name", "")
    if gate.get("status") == "BLOCKED" or not table:
        return None, {"status": "skipped", "reason": "gate blocked or no table_name"}
    live = lookup(table)
    if not live:
        return None, {"status": "new_table", "table": table}
    new_spec, drift, blocking = reconcile_with_live(spec, gate, live)
    if blocking:
        return None, {"status": "not_reconciled", "table": table, "reason": blocking}

    old_pk = next((c["name"] for c in spec["db"]["columns"]
                   if "IDENTITY" in str(c.get("sql_type", "")).upper()), None)
    new_pk = next(c["name"] for c in new_spec["db"]["columns"]
                  if "IDENTITY" in str(c.get("sql_type", "")).upper())
    if drift:
        new_spec["db"]["schema_drift"] = drift
    new_spec["db"]["indexes"] = [
        i for i in spec["db"].get("indexes") or []
        if all(p.strip().lower() in {c["name"].lower() for c in live} for p in str(i).split(","))
    ]
    record = {"status": "reconciled", "table": table, "spec_pk": old_pk, "live_pk": new_pk,
              "pk_corrected": old_pk != new_pk, "schema_drift": drift}
    return new_spec, record


def to_state_json(spec: dict) -> str:
    return json.dumps(spec)
