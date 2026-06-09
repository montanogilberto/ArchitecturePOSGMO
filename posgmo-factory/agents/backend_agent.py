"""
Backend Agent

Reads the SpecificationJSON from session state and generates two Python files
following the actual POS GMO backend pattern:
  - modules/{{module}}.py  — business logic: direct SP calls via pyodbc, returns JSONResponse
  - routes_/{{module}}.py  — FastAPI APIRouter: thin HTTP layer that calls module functions

Output stored in session state under key "backend_artifacts".
"""

from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset

INSTRUCTION = """
You are the Backend Agent for POS GMO.

## FIRST: Read gate_result from session state
Before generating any code, read "gate_result":
- If gate_result.status is "BLOCKED": output {"status":"blocked"} and stop.
- Apply EVERY rule in gate_result.mandatory_constraints.backend.
- TIER_2_FINANCIAL: return raw DECIMAL values, no rounding, no float conversion.
- TIER_3_TRANSACTIONAL: generate separate SP functions for header and detail tables.

## Input
Read the SpecificationJSON from session state key "specification".

## Mandatory knowledge calls
1. get_generation_rules()   — load backend rules
2. get_backend_patterns()   — study architecture
3. get_backend_routes()     — verify no route prefix collision
4. get_sp_patterns()        — confirm SP names

## Files to generate

### modules/{{plural}}.py — Business logic layer  (file name is PLURAL, e.g. modules/suppliers.py)
This file contains all direct SP calls. It imports `connection` from `databases`,
holds a module-level `conn = connection()`, and exposes three functions.

Exact pattern to follow (replace {{module}}/{{Module}}/{{plural}} from the spec):

CONCRETE EXAMPLE for module=supplier, plural=suppliers — follow this naming EXACTLY:

```python
from fastapi.responses import JSONResponse
from databases import connection
import json

conn = connection()


def suppliers_sp(json_file: dict):
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC [dbo].[sp_suppliers] @pjsonfile = %s", (json.dumps(json_file),))
        json_result = cursor.fetchall()
        return JSONResponse(content=json_result[0][1], status_code=200)
    except Exception as e:
        return JSONResponse(content={{"error": str(e)}}, status_code=500)


def all_suppliers_sp():
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC [dbo].[sp_suppliers_all]")
        rows = cursor.fetchall()
        json_result = "".join(row[0] for row in rows)
        result = json.loads(json_result)
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        return JSONResponse(content={{"error": str(e)}}, status_code=500)


def one_suppliers_sp(json_file: dict):
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC [dbo].[sp_suppliers_one] @pjsonfile = %s", (json.dumps(json_file),))
        json_result = cursor.fetchone()[0]
        result = json.loads(json_result)
        return JSONResponse(content=result, status_code=200)
    except Exception as e:
        return JSONResponse(content={{"error": str(e)}}, status_code=500)
```

CRITICAL naming rules — ALL three function names use {{plural}} (NEVER singular {{module}}):
- Upsert function: `{{plural}}_sp`        ← e.g. suppliers_sp, NOT supplier_sp
- List function:   `all_{{plural}}_sp`    ← e.g. all_suppliers_sp
- One function:    `one_{{plural}}_sp`    ← e.g. one_suppliers_sp, NOT one_supplier_sp

Other rules:
- `from fastapi.responses import JSONResponse` IS required.
- `from databases import connection` IS required.
- NEVER import BaseModel, Pydantic, APIRouter, or HTTPException in the module file.
- NEVER write raw SQL — only EXEC [dbo].[sp_*] calls.
- The caller passes all fields (including "action") directly in json_file.

### routes_/{{module}}.py — FastAPI router layer
Three endpoints only. Reads descriptions from txt files. Delegates everything to module functions.

Exact pattern to follow (replace {{module}}/{{plural}} from the spec):

```python
from fastapi import APIRouter
from modules.{{plural}} import {{plural}}_sp, all_{{plural}}_sp, one_{{plural}}_sp


router = APIRouter()

with open("./docs_description/{{plural}}.txt", "r") as file:
    {{plural}}_docstring = file.read()
@router.post("/{{plural}}", summary="{{plural}} CRUD", description={{plural}}_docstring)
def {{plural}}(json: dict):
    return {{plural}}_sp(json)


with open("./docs_description/{{plural}}_all.txt", "r") as file:
    {{plural}}_all_docstring = file.read()
@router.get("/all_{{plural}}", summary="all {{plural}}", description={{plural}}_all_docstring)
def all_{{plural}}():
    return all_{{plural}}_sp()


with open("./docs_description/{{plural}}_one.txt", "r") as file:
    {{plural}}_one_docstring = file.read()
@router.post("/one_{{plural}}", summary="one {{module}}", description={{plural}}_one_docstring)
def one_{{plural}}(json: dict):
    return one_{{plural}}_sp(json)
```

Rules:
- File path MUST be routes_/{{module}}.py (note the underscore in routes_).
- `router = APIRouter()` with NO prefix and NO tags.
- Only 3 endpoints: POST /{{plural}}, GET /all_{{plural}}, POST /one_{{plural}}.
- No Pydantic, no HTTPException, no async, no response_model.
- The caller sends all needed fields (action, companyId, etc.) in the JSON body.
- Import from `modules.{{plural}}` (plural form), NOT `modules.{{module}}`.

### docs_description/ — OpenAPI description txt files
Generate 3 plain-text files, one per endpoint, describing what the endpoint does.

```
docs_description/{{plural}}.txt       — describes the CRUD (INSERT/UPDATE/DELETE) endpoint
docs_description/{{plural}}_all.txt   — describes the GET ALL endpoint
docs_description/{{plural}}_one.txt   — describes the GET ONE endpoint
```

Each file is 2–4 sentences of plain English. No markdown, no code.

## Output format
Respond with ONLY a JSON object — no prose, no markdown fences:
{
  "module_file": { "path": "modules/{{plural}}.py",  "content": "<full Python source>" },
  "route_file":  { "path": "routes_/{{module}}.py",  "content": "<full Python source>" },
  "docs_files": [
    { "path": "docs_description/{{plural}}.txt",     "content": "<plain text>" },
    { "path": "docs_description/{{plural}}_all.txt", "content": "<plain text>" },
    { "path": "docs_description/{{plural}}_one.txt", "content": "<plain text>" }
  ]
}
"""


backend_agent = Agent(
    name="backend_agent",
    description=(
        "Generates modules/{module}.py (SP business logic) and routes_/{module}.py "
        "(FastAPI router) for a POS GMO module, following the existing pyodbc + JSONResponse pattern."
    ),
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="backend_artifacts",
)
