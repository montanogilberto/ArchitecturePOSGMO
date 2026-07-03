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
    "CRUD_ONLY":          "3 sync endpoints, integer actions 1/2/3",
    "CRUD_AND_CONNECTOR": "same as CRUD_ONLY + async connector endpoints",
    "ACTION_ROUTER":      "single async endpoint, string action routing (4+ named ops)",
}