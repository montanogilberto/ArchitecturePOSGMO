"""Replay a saved run's spec+gate through the database stage logic (live
lookup + template) and execute on the real server in validate (rollback)
mode. Evidence for the existing-table fix.

    python scripts/step1_replay_existing_table.py docs/evidence/step1/artifacts/<run>.json
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["FACTORY_SQL_MODE"] = "validate"
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agents.database.live_schema import live_table_columns  # noqa: E402
from agents.database.rules import execute_sql_on_server  # noqa: E402
from agents.database.sql_templates import generate_crud_sql, _safe_load  # noqa: E402
from agents.reviewer.rules import _check_database  # noqa: E402

a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
spec, gate = _safe_load(a["specification"]), _safe_load(a["gate_result"])
live = live_table_columns(spec["db"]["table_name"])
out = generate_crud_sql(spec, gate, live)
res = execute_sql_on_server(out["create_table"], out["sp_upsert"], out["sp_all"], out["sp_one"])
print(json.dumps({
    "table": spec["db"]["table_name"],
    "spec_pk": next(c["name"] for c in spec["db"]["columns"] if "IDENTITY" in c["sql_type"].upper()),
    "live_pk": next((c["name"] for c in live or [] if c["is_identity"]), None),
    "existing_table": out.get("existing_table"), "schema_drift": out.get("schema_drift"),
    "execution": {"success": res["success"], "mode": res.get("mode"),
                  "statuses": [d["status"] for d in res["details"]],
                  "errors": [d.get("message", "")[:160] for d in res["details"] if d["status"] == "error"]},
    "review_issues": [i.message for i in _check_database({**out, "execution": res}, spec, gate)],
}, indent=2))
