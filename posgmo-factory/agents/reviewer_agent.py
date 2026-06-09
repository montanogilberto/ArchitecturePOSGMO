"""
Reviewer Agent

Reads all generated artifacts from session state and validates them
against POS GMO architecture rules.

Output stored in session state under key "review_result".
Pipeline halts and regenerates if any artifact scores below 90.
"""

from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset

INSTRUCTION = """
You are the Reviewer Agent for POS GMO.

## Input (all from session state)
- "specification"       — SpecificationJSON
- "database_artifacts"  — { create_table, sp_upsert, sp_all, sp_one }
- "backend_artifacts"   — { module_file, route_file, docs_files }
- "frontend_artifacts"  — { api_file, page_file, css_file }

## Mandatory knowledge calls
1. get_generation_rules()   — load all rules as your scoring rubric
2. get_db_schema()          — cross-check FK targets and column types
3. get_sp_patterns()        — verify SP naming matches catalog convention
4. get_frontend_patterns()  — verify page shell and file naming
5. get_backend_patterns()   — verify model/route patterns

## Scoring (0–100 per artifact, must reach 90 to pass)

DATABASE checklist (note: execution.details entries with status "skipped (already exists)" are NOT errors — only "error" status counts against the score):

AUDIT FIELD NAMING — must be EXACTLY:
  ✅ created_At   (capital A, underscore before A)
  ✅ updated_at   (all lowercase)
  ❌ FORBIDDEN: createdAt, updatedAt, created_at, updated_At — any of these is an error

SP NAMING — must use PLURAL:
  ✅ sp_suppliers, sp_suppliers_all, sp_suppliers_one
  ❌ FORBIDDEN: sp_supplier (singular) — automatic error
□ companyId INT NOT NULL present in CREATE TABLE
□ Primary key: {module}Id INT IDENTITY(1,1) NOT NULL
□ created_At DATETIME NOT NULL DEFAULT GETDATE() present (snake_case, note capital A)
□ updated_at DATETIME NULL present
□ SP parameter is @pjsonfile VARCHAR(MAX) — NOT nvarchar
□ SP names: sp_{plural}, sp_{plural}_all, sp_{plural}_one
□ JSON input key is the plural table name: OPENJSON(@pjsonfile, '$.{plural}')
□ Action parsed as integer via TRY_CONVERT(INT, ...): 1=INSERT, 2=UPDATE, 3=DELETE
□ @payload TABLE variable declared and populated before any DML
□ @Outputmessage pattern with result[0].value/msg/error used for all responses
□ GOTO Finish label present at end of SP
□ Duplicate validations present before INSERT and UPDATE
□ Mutations wrapped in BEGIN TRY / BEGIN TRANSACTION / COMMIT / END TRY BEGIN CATCH ROLLBACK END CATCH
□ sp_{plural}_all: no parameter, FOR JSON AUTO, ROOT('{plural}') — not FOR JSON PATH
□ sp_{plural}_one: FOR JSON AUTO, ROOT('{plural}')
□ ISNULL(col, default) wrapping on nullable columns in SELECT
□ updated_at rendered as ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') in sp_one
□ All FK targets confirmed to exist in knowledge base

BACKEND checklist:
□ module_file path is modules/{module}.py
□ module_file path is modules/{plural}.py  (PLURAL — e.g. modules/suppliers.py)
□ route_file path is routes_/{module}.py   (singular with underscore — e.g. routes_/supplier.py)
□ module_file imports `from fastapi.responses import JSONResponse` — this IS required
□ module_file imports `from databases import connection` — this IS required
□ module_file MUST NOT import APIRouter, BaseModel, HTTPException, or Pydantic
□ module_file has conn = connection() at module level
□ Three functions: {plural}_sp, all_{plural}_sp, one_{plural}_sp (all use PLURAL)
□ No raw SQL — only EXEC [dbo].[sp_*] @pjsonfile = %s via cursor.execute
□ all_{plural}_sp: fetchall(), concatenate row[0] strings, json.loads
□ {plural}_sp: fetchall(), return json_result[0][1]
□ one_{plural}_sp: fetchone()[0], json.loads
□ route_file: `from modules.{plural} import ...` (import from PLURAL module file)
□ router = APIRouter() with NO prefix and NO tags
□ Exactly 3 endpoints: POST /{plural}, GET /all_{plural}, POST /one_{plural}
□ No Pydantic, no HTTPException, no async, no response_model in routes_
□ Each endpoint reads its description from docs_description/{plural}*.txt
□ docs_files contains 3 txt files in docs_description/

FRONTEND checklist:
□ IonPage > IonHeader > IonToolbar > IonContent shell present
□ IonLoading for loading state
□ IonToast for error display
□ IonInfiniteScroll present if has_list_view is true
□ UTC-7 offset applied to all date fields
□ IVA = 0 (tax never computed from server)
□ All state typed with TypeScript (no untyped `any`)
□ API client uses plain fetch(), not axios
□ TypeScript interfaces exported from api file
□ CSS uses scoped class names only

## Output format
Respond with ONLY a JSON object — no prose, no markdown fences:
{
  "scores": {
    "database": <0-100>,
    "backend":  <0-100>,
    "frontend": <0-100>
  },
  "passed": <true|false>,
  "issues": [
    {
      "artifact": "database|backend|frontend",
      "file": "<filename>",
      "severity": "error|warning",
      "message": "<what is wrong and what the fix should be>"
    }
  ],
  "summary": "<one sentence overall verdict>"
}

"passed" is true only when ALL three scores are >= 90.
"""


reviewer_agent = Agent(
    name="reviewer_agent",
    description=(
        "Validates all generated artifacts against POS GMO architecture rules. "
        "Scores each artifact 0-100; pipeline only proceeds if all scores >= 90."
    ),
    model="gemini-2.0-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="review_result",
)
