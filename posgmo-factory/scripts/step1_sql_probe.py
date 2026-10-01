"""
Step 1 evidence probe: render template SQL, execute it on the real SQL
Server, exercise every SP (insert -> all -> one -> update -> delete), then
ROLL BACK everything. Uses throwaway zz* table names so it can never touch a
live object. Prints a JSON report.

    python scripts/step1_sql_probe.py
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pyodbc  # noqa: E402

from agents.database.sql_templates import generate_crud_sql  # noqa: E402


def _cases() -> dict:
    fx = json.loads((ROOT / "tests/fixtures/factoryRun_spec_gate.json").read_text(encoding="utf-8"))
    ti = copy.deepcopy(fx["specification"])
    ti["module"], ti["db"]["table_name"], ti["db"]["sp_prefix"] = "zzStep1Probe", "ZzStep1Probes", "sp_zzStep1Probes"
    ti["db"]["columns"][0]["name"] = "zzStep1ProbeId"
    ti_row = {"title": "t", "projectSlug": "p", "organizationSlug": "o", "prdModuleName": "m",
              "prdSnapshot": "x" * 5000, "status": "queued", "triggeredByEmail": "a@b.c"}

    ts = copy.deepcopy(ti)
    ts["module"], ts["db"]["table_name"], ts["db"]["sp_prefix"] = "zzStep1Money", "ZzStep1Moneys", "sp_zzStep1Moneys"
    ts["db"]["columns"][0]["name"] = "zzStep1MoneyId"
    ts["db"]["columns"].insert(1, {"name": "companyId", "sql_type": "int", "nullable": False,
                                   "fk_table": "companies", "fk_column": "companyId"})
    ts["db"]["columns"].insert(2, {"name": "amountMXN", "sql_type": "decimal(12,4)", "nullable": False})
    ts_gate = {**fx["gate_result"], "tier": "TIER_2_FINANCIAL", "tenant_model": "TENANT_SCOPED",
               "mandatory_constraints": {"database": []}}
    return {
        "tenant_independent (factoryRun shape)": (ti, fx["gate_result"], ti_row, None),
        "tenant_scoped TIER_2 (companies FK)": (ts, ts_gate, {**ti_row, "amountMXN": 123.456}, "companyId"),
    }


def _batches(sql: str) -> list[str]:
    return [b.strip() for b in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE) if b.strip()]


def _exec(cur, sp: str, payload: dict):
    cur.execute(f"EXEC [dbo].[{sp}] @pjsonfile = ?", json.dumps(payload))
    rows = cur.fetchall()
    if not rows:
        return None
    return "".join(str(r[0]) for r in rows) if len(rows[0]) == 1 else [tuple(r) for r in rows]


def probe(name, spec, gate, row, company_col, cur) -> dict:
    out = generate_crud_sql(spec, gate)
    plural, sp = f"{spec['module']}s", spec["db"]["sp_prefix"]
    pk = f"{spec['module']}Id"
    report = {"case": name, "compile": [], "behavior": {}}
    for key in ("create_table", "sp_upsert", "sp_all", "sp_one"):
        for b in _batches(out[key]):
            cur.execute(b)
            report["compile"].append(b.split("\n", 1)[0][:70])

    company = {}
    if company_col:
        cur.execute("SELECT TOP 1 companyId FROM dbo.companies ORDER BY companyId")
        company = {"companyId": cur.fetchone()[0]}

    ins = _exec(cur, sp, {plural: [{"action": 1, **company, **row}]})
    new_id = int(ins[0][0])
    listed = json.loads(_exec(cur, f"{sp}_all", {plural: [company]}))[plural]
    one = json.loads(_exec(cur, f"{sp}_one", {plural: [{pk: new_id}]}))[plural][0]
    upd = _exec(cur, sp, {plural: [{"action": 2, pk: new_id, **company, **row, "status": "done"}]})
    after = json.loads(_exec(cur, f"{sp}_one", {plural: [{pk: new_id}]}))[plural][0]
    other_tenant = None
    if company_col:  # a different company must not be able to see or delete the row
        other = {"companyId": company["companyId"] + 987654}
        other_tenant = _exec(cur, f"{sp}_all", {plural: [other]})
    dele = _exec(cur, sp, {plural: [{"action": 3, pk: new_id, **company}]})
    cur.execute(f"SELECT COUNT(*) FROM dbo.[{spec['db']['table_name']}] WHERE [{pk}] = ?", new_id)
    remaining = cur.fetchone()[0]

    report["behavior"] = {
        "insert": ins[0], "all_count": len(listed), "one_updated_at_before": one.get("updated_at"),
        "prdSnapshot_len_roundtrip": len(one["prdSnapshot"]),
        "amountMXN": one.get("amountMXN"), "update": upd[0], "status_after_update": after["status"],
        "updated_at_after": after["updated_at"], "other_tenant_all": other_tenant,
        "delete": dele[0], "rows_remaining": remaining,
    }
    report["passed"] = (
        ins[0][2] == "" and len(listed) == 1 and len(one["prdSnapshot"]) == 5000
        and after["status"] == "done" and after["updated_at"] != "" and remaining == 0
        and (other_tenant in (None, "", "None"))
    )
    return report


def main():
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['LOCAL_DB_SERVER']};DATABASE={os.environ['LOCAL_DB_NAME']};"
        f"UID={os.environ['LOCAL_DB_USER']};PWD={os.environ['LOCAL_DB_PASSWORD']};TrustServerCertificate=yes;"
    )
    reports = []
    for name, (spec, gate, row, company_col) in _cases().items():
        conn = pyodbc.connect(conn_str, autocommit=False)
        try:
            reports.append(probe(name, spec, gate, row, company_col, conn.cursor()))
        except Exception as e:  # noqa: BLE001
            reports.append({"case": name, "passed": False, "error": str(e)[:400]})
        finally:
            conn.rollback()
            conn.close()
    print(json.dumps(reports, indent=2, default=str))


if __name__ == "__main__":
    main()
