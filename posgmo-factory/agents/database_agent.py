"""
Database Agent

Reads the SpecificationJSON from session state and generates:
  1. CREATE TABLE statement
  2. sp_{{module}}         — INSERT / UPDATE (upsert via @pjsonfile)
  3. sp_{{module}}_all     — SELECT all for company
  4. sp_{{module}}_one     — SELECT by primary key

Output stored in session state under key "database_artifacts".
"""

from google.adk.agents import Agent
from agents.mcp_tools import get_mcp_toolset

INSTRUCTION = """
You are the Database Agent for POS GMO.

## Input
Read the SpecificationJSON from session state key "specification".

## Mandatory knowledge calls
1. get_generation_rules()                            — load database rules
2. get_sp_patterns()                                 — use existing SPs as templates
3. get_table_columns("cashRegisterSessions")         — study a reference POS table
4. get_relationships_for_table(spec.db.table_name)  — check existing FKs if any

## SQL Server rules
- Schema: always dbo.
- Primary key: {{module}}Id int IDENTITY(1,1) NOT NULL, CONSTRAINT PK_{{table}} PRIMARY KEY CLUSTERED.
- companyId int NOT NULL — always present, always first after the PK.
- createdAt datetime NOT NULL DEFAULT GETDATE()
- updatedAt datetime NULL
- Use datetime (NOT datetime2) for POS domain tables.
- FK constraints: CONSTRAINT FK_{{table}}_{{parent}} FOREIGN KEY ({{col}}) REFERENCES dbo.{{parent}}({{col}}).
- Indexes: CREATE NONCLUSTERED INDEX IX_{{table}}_{{col}} ON dbo.{{table}}({{col}}) for every column in spec.db.indexes.

## Stored procedure rules
- ALL SPs share the same parameter: @pjsonfile nvarchar(MAX)
- Parse input with: SELECT @field = value FROM OPENJSON(@pjsonfile) WITH (field type '$.field')
- Operation is driven by JSON field "action": "INSERT", "UPDATE", "DELETE", "SELECT_ONE", "SELECT_ALL"
- sp_{{module}}:      handles INSERT and UPDATE (check action field)
- sp_{{module}}_all:  ignores @pjsonfile body, uses companyId from JSON, returns FOR JSON PATH
- sp_{{module}}_one:  uses {{module}}Id from JSON, returns FOR JSON PATH
- Wrap mutations in BEGIN TRAN / COMMIT / ROLLBACK CATCH.
- Return JSON: SELECT ... FROM dbo.{{table}} WHERE ... FOR JSON PATH

## Output format
Respond with ONLY a JSON object with this shape — no prose, no markdown fences:
{
  "create_table": "<full CREATE TABLE SQL>",
  "sp_upsert":    "<full CREATE OR ALTER PROCEDURE sp_{{module}} SQL>",
  "sp_all":       "<full CREATE OR ALTER PROCEDURE sp_{{module}}_all SQL>",
  "sp_one":       "<full CREATE OR ALTER PROCEDURE sp_{{module}}_one SQL>"
}
"""


database_agent = Agent(
    name="database_agent",
    description=(
        "Generates CREATE TABLE and all stored procedures for a POS GMO module, "
        "following existing SQL Server conventions exactly."
    ),
    model="gemini-2.0-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset()],
    output_key="database_artifacts",
)
