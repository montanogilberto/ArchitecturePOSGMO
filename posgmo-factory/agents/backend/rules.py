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

# All three endpoints are POST — never GET
ENDPOINT_METHODS = {
    "upsert": "POST",
    "all":    "POST",
    "one":    "POST",
}

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

# Per-request connection pattern (module-level conn is forbidden)
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