"""
Backend Agent — generation rules summary.
These constants document the invariants the LLM must follow.
The full rules are embedded in prompt.py; this file provides
machine-readable versions for tests and documentation.
"""

# Route file prefix — ALWAYS routes_/ (note the underscore)
ROUTE_FILE_PREFIX = "routes_/"

# Module file prefix — ALWAYS modules/ with PLURAL name
MODULE_FILE_PREFIX = "modules/"

# All three CRUD endpoints are POST — never GET
ENDPOINT_METHODS = {
    "upsert": "POST",
    "all":    "POST",
    "one":    "POST",
}

# ACTION_ROUTER has a single POST endpoint
ACTION_ROUTER_ENDPOINT_METHOD = "POST"

# Forbidden imports in module files
FORBIDDEN_MODULE_IMPORTS = {
    "BaseModel", "APIRouter", "HTTPException", "Pydantic",
}

# Required imports in module files
REQUIRED_MODULE_IMPORTS = {
    "JSONResponse": "from fastapi.responses import JSONResponse",
    "connection":   "from databases import connection",
    "json":         "import json",
}

# Per-request connection pattern — CRUD style (conn only, no cursor at module level)
CONNECTION_PATTERN = """
def {plural}_sp(json_file: dict):
    conn = None
    try:
        conn = connection()
        cursor = conn.cursor()
        cursor.execute("EXEC [dbo].[sp_{plural}] @pjsonfile = %s", (json.dumps(json_file),))
        row = cursor.fetchone()
        json_result = row[0] if row else '{{"message": "ok"}}'
        return JSONResponse(content=json.loads(json_result), status_code=200)
    except Exception as e:
        return JSONResponse(content={{"error": str(e)}}, status_code=500)
    finally:
        if conn:
            conn.close()
"""

# Per-request connection pattern — ACTION_ROUTER style
# conn AND cursor start as None; closed in separate sub-finally blocks
ACTION_ROUTER_CONNECTION_PATTERN = """
def _sp(payload: dict):
    conn = cursor = None
    try:
        conn = connection()
        cursor = conn.cursor()
        cursor.execute(
            "EXEC [dbo].[sp_{module}] @pjsonfile = %s",
            (json.dumps({{"{{domainKey}}": [payload]}}),)
        )
        row = cursor.fetchone()
        raw = row[0] if row and row[0] else "null"
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        return {{"error": str(e)}}
    finally:
        try:
            if cursor: cursor.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass
"""

# Backend pattern types
BACKEND_PATTERNS = {
    "CRUD_ONLY":          "3 sync endpoints (/plural, /all_plural, /one_plural), integer actions 1/2/3",
    "CRUD_AND_CONNECTOR": "same as CRUD_ONLY + async connector endpoints (Azure Face, blob upload)",
    "ACTION_ROUTER":      "single async POST endpoint, string action routing, 4+ named ops (loanChat, disbursement, legalCases)",
    "BUSINESS_LOGIC":     "multiple named async endpoints, private _sp_X() helpers returning dicts, may call Stripe/httpx (creditScore, walletBalance, automatedPayments)",
    "WEBHOOK_HANDLER":    "external webhook endpoint (Twilio, Stripe), always returns HTTP 200, handles form-encoded + JSON (whatsapp)",
    "BLOB_UPLOAD":        "file upload only, base64 → Azure Blob Storage → returns blobUrl, no SP call (signatureUpload)",
}

# SmartLoans modules and their patterns (reference)
SMARTLOANS_MODULE_PATTERNS = {
    "clientFaceRecognitions": "CRUD_AND_CONNECTOR",  # CRUD + Azure Liveness + blob upload
    "creditScore":            "BUSINESS_LOGIC",       # in-memory scoring algo + 2 SPs
    "loans":                  "CRUD_ONLY",            # NOTE: current code has module-level conn bug
    "pushNotifications":      "CRUD_ONLY",            # CRUD + register_device (async, Azure NH)
    "loanOffers":             "CRUD_ONLY",
    "loanProposals":          "CRUD_ONLY",
    "loanChat":               "ACTION_ROUTER",        # string actions + push notifications
    "signatureUpload":        "BLOB_UPLOAD",          # routes_ only, no module file
    "automatedPayments":      "BUSINESS_LOGIC",       # Stripe SetupIntent + amortization + cron
    "whatsapp":               "WEBHOOK_HANDLER",      # Twilio TwiML, always 200
    "walletBalance":          "BUSINESS_LOGIC",       # _sp_wallet() helper + named async funcs
    "rewards":                "ACTION_ROUTER",        # _sp() + sync rewards_sp, no push
    "clientDashboards":       "CRUD_ONLY",            # NOTE: current code has module-level conn bug
    "digitalContracts":       "ACTION_ROUTER",        # _sp() + async + push
    "legalCases":             "ACTION_ROUTER",        # _sp() + async + push
    "disbursement":           "ACTION_ROUTER",        # _sp() + async + push
}