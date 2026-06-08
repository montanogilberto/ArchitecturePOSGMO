"""
Backend Agent

Reads the SpecificationJSON from session state and generates three Python files:
  - models/{{module}}.py    — Pydantic request/response models
  - schemas/{{module}}.py   — thin Pydantic schema aliases (used for OpenAPI docs)
  - routes/{{module}}.py    — FastAPI APIRouter with all CRUD endpoints

Output stored in session state under key "backend_artifacts".
"""

from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset

INSTRUCTION = """
You are the Backend Agent for POS GMO.

## Input
Read the SpecificationJSON from session state key "specification".

## Mandatory knowledge calls
1. get_generation_rules()     — load backend rules
2. get_backend_patterns()     — study existing models and auth patterns
3. get_backend_routes()       — verify no route prefix collision
4. get_sp_patterns()          — confirm SP names to call

## Python / FastAPI rules
- models/{{module}}.py:
    * Class {{Module}}Base(BaseModel):  all fields, Optional for nullable
    * Class {{Module}}Create({{Module}}Base):  used for POST body
    * Class {{Module}}Response({{Module}}Base):  adds {{module}}Id, companyId, createdAt, updatedAt
    * Use Optional[X] = None for nullable columns.
    * datetime fields typed as Optional[datetime] = None.
    * Google-style docstring on every class and function.

- schemas/{{module}}.py:
    * from models.{{module}} import {{Module}}Create, {{Module}}Response
    * Re-export with __all__ = ["{{Module}}Create", "{{Module}}Response"]
    * Add any response envelope schemas needed (e.g. {{Module}}ListResponse).

- routes/{{module}}.py:
    * router = APIRouter(prefix="/{{plural}}", tags=["{{Module}}"])
    * Imports: from fastapi import APIRouter, HTTPException
    * DB connection helper: from database import get_connection   (existing pattern)
    * ALL DB calls: cursor.execute("EXEC sp_{{module}} @pjsonfile=?", json.dumps(payload))
    * NEVER write raw SQL in Python.
    * POST   /{{plural}}/             → calls sp_{{module}} with action="INSERT"
    * PUT    /{{plural}}/{{id}}         → calls sp_{{module}} with action="UPDATE"
    * DELETE /{{plural}}/{{id}}         → calls sp_{{module}} with action="DELETE"
    * GET    /{{plural}}/             → calls sp_{{module}}_all
    * GET    /{{plural}}/{{id}}         → calls sp_{{module}}_one
    * Parse SP response: rows = cursor.fetchone()[0]; return json.loads(rows)
    * On empty result raise HTTPException(status_code=404)
    * Full Google-style docstring on every endpoint.

## Output format
Respond with ONLY a JSON object — no prose, no markdown fences:
{
  "model_file":  { "path": "models/{{module}}.py",  "content": "<full Python source>" },
  "schema_file": { "path": "schemas/{{module}}.py", "content": "<full Python source>" },
  "route_file":  { "path": "routes/{{module}}.py",  "content": "<full Python source>" }
}
"""


backend_agent = Agent(
    name="backend_agent",
    description=(
        "Generates FastAPI models, schemas, and routes for a POS GMO module, "
        "following existing Pydantic and pyodbc patterns exactly."
    ),
    model="gemini-2.0-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="backend_artifacts",
)
