"""
Client Acquisition, phase 1: which ad brought each lead. Rows are written only
from the WhatsApp webhook (modules/whatsappCloud), never from a public route.
"""

import json

from fastapi.responses import JSONResponse

from databases import connection
from observability.logger import workflow_step


def record_referral(json_file: dict) -> int:
    """Idempotent insert. json_file is the SP's @pjsonfile shape. Returns the
    row's id, new or existing. Raises on failure; workflow_step logs it."""
    with workflow_step("record_referral", workflow_name="marketing_attribution",
                       entity="marketingLeadAttribution", action="create"):
        conn = None
        try:
            conn = connection()
            cursor = conn.cursor()
            cursor.execute("EXEC [dbo].[sp_marketingLeadAttributions] @pjsonfile = %s", (json.dumps(json_file),))
            value, msg, error = cursor.fetchone()
            if error:
                raise RuntimeError(f"sp_marketingLeadAttributions: {msg}")
            return int(value)
        finally:
            if conn:
                conn.close()


def _read_sp(procedure: str, json_file: dict) -> JSONResponse:
    conn = None
    try:
        conn = connection()
        cursor = conn.cursor()
        cursor.execute(f"EXEC [dbo].[{procedure}] @pjsonfile = %s", (json.dumps(json_file),))
        rows = cursor.fetchall()
        # SQL Server may split long JSON across rows: always join.
        raw = "".join(r[0] for r in rows if r and r[0])
        return JSONResponse(content=json.loads(raw), status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        if conn:
            conn.close()


def all_marketingLeadAttributions_sp(json_file: dict) -> JSONResponse:
    return _read_sp("sp_marketingLeadAttributions_all", json_file)


def one_marketingLeadAttributions_sp(json_file: dict) -> JSONResponse:
    return _read_sp("sp_marketingLeadAttributions_one", json_file)
