"""
Client Acquisition, phase 1b: which ad set and campaign each ad belongs to.

Meta's Click-to-WhatsApp referral carries only the ad id. The webhook leaves a
'pending' row per ad (ensure_pending, in-process); smartloans_workers'
marketingAdsSyncWorker resolves it against the Meta Marketing API and writes
the result through POST /marketingAds. No personal data lives here.
"""

import json

from fastapi.responses import JSONResponse

from databases import connection
from observability.logger import workflow_step

SUPPORTED_ACTIONS = (1, 2)


def _exec(procedure: str, json_file: dict) -> dict:
    conn = None
    try:
        conn = connection()
        cursor = conn.cursor()
        cursor.execute(f"EXEC [dbo].[{procedure}] @pjsonfile = %s", (json.dumps(json_file),))
        rows = cursor.fetchall()
        # SQL Server may split long JSON across rows: always join.
        return json.loads("".join(r[0] for r in rows if r and r[0]))
    finally:
        if conn:
            conn.close()


def ensure_pending(json_file: dict) -> int:
    """Idempotent: the ad's row id, new ('pending') or existing. json_file is the
    SP's @pjsonfile shape with action 1. Raises on failure; workflow_step logs it.
    The webhook calls this inside its own try/except: a failure must never cost
    the customer a reply."""
    with workflow_step("ensure_ad_pending", workflow_name="marketing_attribution",
                       entity="marketingAd", action="create"):
        result = _exec("sp_marketingAds", json_file)
        if result.get("error"):
            raise RuntimeError(f"sp_marketingAds: {result['error']}")
        return result["result"][0]["marketingAds"][0]["marketingAdId"]


def upsert_marketingAds_sp(json_file: dict) -> JSONResponse:
    """POST /marketingAds (worker key). action 1 ensures a pending row, action 2
    writes a lookup result on an existing row. SP business errors are 400."""
    try:
        action = int(json_file["marketingAds"][0]["action"])
    except (KeyError, IndexError, TypeError, ValueError):
        return JSONResponse(content={"error": "marketingAds[0].action is required"}, status_code=400)
    if action not in SUPPORTED_ACTIONS:
        return JSONResponse(content={"error": "unsupported_action"}, status_code=400)
    try:
        with workflow_step("write_ad_lookup" if action == 2 else "ensure_ad_pending",
                           workflow_name="marketing_attribution", entity="marketingAd",
                           action="update" if action == 2 else "create"):
            result = _exec("sp_marketingAds", json_file)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    if result.get("error"):
        return JSONResponse(content=result, status_code=404 if result["error"] == "ad_not_found" else 400)
    return JSONResponse(content=result, status_code=200)


def all_marketingAds_sp(json_file: dict) -> JSONResponse:
    try:
        result = _exec("sp_marketingAds_all", json_file)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    return JSONResponse(content=result, status_code=400 if result.get("error") else 200)
