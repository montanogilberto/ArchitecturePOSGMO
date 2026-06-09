"""
Database Agent

Reads the SpecificationJSON from session state and generates:
  1. CREATE TABLE statement
  2. sp_{plural}       — INSERT (1) / UPDATE (2) / DELETE (3) via integer action
  3. sp_{plural}_all   — SELECT all rows FOR JSON AUTO, ROOT('{plural}')
  4. sp_{plural}_one   — SELECT single row by PK FOR JSON AUTO, ROOT('{plural}')

Output stored in session state under key "database_artifacts".
"""

import os
import re

import pyodbc
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.mcp_tools import get_mcp_toolset

load_dotenv()


def execute_sql_on_server(
    create_table: str,
    sp_upsert: str,
    sp_all: str,
    sp_one: str,
) -> dict:
    """
    Executes the generated CREATE TABLE and three stored procedures directly
    against the POS GMO SQL Server using credentials from environment variables.

    Each statement is split on GO and executed individually, which is required
    by pyodbc (it does not support GO as a batch separator).

    Args:
        create_table: Full SQL for CREATE TABLE + indexes.
        sp_upsert:    Full SQL for sp_{plural} (INSERT/UPDATE/DELETE).
        sp_all:       Full SQL for sp_{plural}_all.
        sp_one:       Full SQL for sp_{plural}_one.

    Returns:
        dict with "success" bool and "details" list of per-statement results.
    """
    server   = os.environ["LOCAL_DB_SERVER"]
    database = os.environ["LOCAL_DB_NAME"]
    user     = os.environ["LOCAL_DB_USER"]
    password = os.environ["LOCAL_DB_PASSWORD"]

    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};DATABASE={database};"
        f"UID={user};PWD={password};"
        "TrustServerCertificate=yes;"
    )

    combined = "\n".join([create_table, sp_upsert, sp_all, sp_one])
    # Split on GO (case-insensitive, on its own line) — pyodbc cannot handle GO
    batches = [b.strip() for b in re.split(r"^\s*GO\s*$", combined, flags=re.MULTILINE) if b.strip()]

    # SQL Server error numbers that mean "already exists" — safe to skip on re-runs
    _ALREADY_EXISTS_CODES = {
        2714,   # object with that name already exists
        1913,   # index with that name already exists
        2705,   # column name already exists
    }

    details = []
    try:
        with pyodbc.connect(conn_str, autocommit=True) as conn:
            cursor = conn.cursor()
            for batch in batches:
                try:
                    cursor.execute(batch)
                    details.append({"status": "ok", "batch_preview": batch[:80]})
                except pyodbc.Error as e:
                    err_str = str(e)
                    # Extract SQL Server native error number (last number in the tuple repr)
                    native = None
                    try:
                        native = int(re.search(r"\((\d+)\) \(SQL", err_str).group(1))
                    except Exception:
                        pass
                    if native in _ALREADY_EXISTS_CODES:
                        details.append({"status": "skipped (already exists)", "batch_preview": batch[:80]})
                    else:
                        details.append({"status": "error", "message": err_str, "batch_preview": batch[:80]})
        success = all(d["status"] in ("ok", "skipped (already exists)") for d in details)
        return {"success": success, "details": details}
    except pyodbc.Error as e:
        return {"success": False, "details": [{"status": "connection_error", "message": str(e)}]}

INSTRUCTION = """
You are the Database Agent for POS GMO.

## Input
Read the SpecificationJSON from session state key "specification".

## Mandatory knowledge calls
1. get_generation_rules()                        — load database rules
2. get_sp_patterns()                             — use existing SPs as templates
3. get_table_columns("cashRegisterSessions")     — study a reference POS table
4. get_relationships_for_table(spec.db.table_name) — check existing FKs if any

## Rules

### CREATE TABLE
- Schema: always dbo.
- Primary key: {module}Id INT IDENTITY(1,1) NOT NULL, CONSTRAINT PK_{Table} PRIMARY KEY CLUSTERED.
- companyId INT NOT NULL — always present after PK.
- Column names: snake_case (e.g. first_name, last_name, created_At, updated_at).
- created_At DATETIME NOT NULL DEFAULT GETDATE()
- updated_at DATETIME NULL
- Use DATETIME (not DATETIME2) for POS domain tables.
- FK constraints: CONSTRAINT FK_{Table}_{Parent} FOREIGN KEY (col) REFERENCES dbo.{parent}(col).
- NONCLUSTERED INDEX for every column listed in spec.db.indexes.

### sp_{plural} — CRUD stored procedure
Parameter: @pjsonfile VARCHAR(MAX)  (VARCHAR not NVARCHAR)

Output template variable declared at top:
```sql
DECLARE @Outputmessage NVARCHAR(MAX) = '{
  "result": [
    { "value": "", "msg": "", "error": "" }
  ]
}'
```

Action is an integer read from the JSON:
```sql
SET @action = (
    SELECT TOP 1 TRY_CONVERT(INT, JSON_VALUE(value, '$.action'))
    FROM OPENJSON(@pjsonfile, '$.{plural}')
);
```

Declare a @payload table variable with all module columns (nullable):
```sql
DECLARE @payload TABLE (
    {module}Id  INT NULL,
    companyId   INT NULL,
    first_name  NVARCHAR(100) NULL,
    ...
);

INSERT INTO @payload (...)
SELECT
    TRY_CONVERT(INT, JSON_VALUE(value, '$.{module}Id')),
    TRY_CONVERT(INT, JSON_VALUE(value, '$.companyId')),
    JSON_VALUE(value, '$.first_name'),
    ...
FROM OPENJSON(@pjsonfile, '$.{plural}');
```

Actions:
- 1 = INSERT: run duplicate validations, then INSERT INTO dbo.{plural} SELECT ... FROM @payload
- 2 = UPDATE: run duplicate validations (exclude self), then UPDATE dbo.{plural} INNER JOIN @payload
- 3 = DELETE: DELETE dbo.{plural} INNER JOIN @payload ON {module}Id

Duplicate validations (for fields that must be unique within a company):
- Check for duplicates within the payload itself first (GROUP BY companyId, field HAVING COUNT(*) > 1)
- Check for conflicts against the existing table (INNER JOIN dbo.{plural} on companyId + field)
- On conflict: SET @Outputmessage error='1' and msg=<reason>, COMMIT, GOTO Finish

Set success message: SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Inserted/Updated/Deleted Successfully')

Wrap everything in BEGIN TRY / BEGIN TRANSACTION ... COMMIT / END TRY BEGIN CATCH ROLLBACK SET error END CATCH

End with GOTO label:
```sql
Finish:
    SELECT
        JSON_VALUE(value,'$.value') AS value,
        JSON_VALUE(value,'$.msg')   AS msg,
        JSON_VALUE(value,'$.error') AS error
    FROM OPENJSON(@Outputmessage,'$.result');
```

### sp_{plural}_all — SELECT all
No parameter. Pattern:
```sql
CREATE PROC [dbo].[sp_{plural}_all]
AS
SET NOCOUNT ON
BEGIN
    SELECT
        [{module}Id],
        ISNULL([companyId], 0)   AS companyId,
        ISNULL([first_name], '') AS first_name,
        ...
        [created_At],
        [updated_at]
    FROM dbo.{plural}
    FOR JSON AUTO, ROOT('{plural}');
END
```
- Wrap every nullable column with ISNULL(col, default) — use 0 for ints, '' for strings.
- Use FOR JSON AUTO, ROOT('{plural}') — NOT FOR JSON PATH.

### sp_{plural}_one — SELECT by PK
Parameter: @pjsonfile VARCHAR(MAX)

Pattern:
```sql
ALTER PROC [dbo].[sp_{plural}_one] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @{module}Id INT;
    SET @{module}Id = CAST(
        (SELECT TOP 1 JSON_VALUE(value, '$.{module}Id')
         FROM OPENJSON(@pjsonfile, '$.{plural}')) AS INT
    );
    SELECT
        {module}Id,
        ISNULL(companyId, 0)   AS companyId,
        ISNULL(first_name, '') AS first_name,
        ...
        created_At,
        ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') AS updated_at
    FROM dbo.{plural}
    WHERE {module}Id = @{module}Id
    FOR JSON AUTO, ROOT('{plural}');
END
```
- updated_at uses ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '') to handle NULLs.
- Use FOR JSON AUTO, ROOT('{plural}').

## JSON input contract (caller must send):
```json
{
  "{plural}": [
    { "action": 1, "companyId": 5, "first_name": "...", ... }
  ]
}
```
Action values: 1=INSERT, 2=UPDATE, 3=DELETE.

## Execution step (MANDATORY — do this after generating SQL)
After generating all four SQL blocks, call execute_sql_on_server with:
- create_table = the CREATE TABLE + index SQL
- sp_upsert    = the sp_{plural} SQL
- sp_all       = the sp_{plural}_all SQL
- sp_one       = the sp_{plural}_one SQL

The tool connects to the SQL Server and executes each statement.
If any statement returns an error, include it in the output's "execution" field.

## Output format
Respond with ONLY a JSON object — no prose, no markdown fences:
{
  "create_table": "<full CREATE TABLE SQL>",
  "sp_upsert":    "<full CREATE OR ALTER PROCEDURE sp_{plural} SQL>",
  "sp_all":       "<full CREATE PROC sp_{plural}_all SQL>",
  "sp_one":       "<full ALTER PROC sp_{plural}_one SQL>",
  "execution":    <result dict from execute_sql_on_server>
}
"""


database_agent = Agent(
    name="database_agent",
    description=(
        "Generates CREATE TABLE and all stored procedures for a POS GMO module, "
        "then executes them directly against SQL Server."
    ),
    model="gemini-2.0-flash",
    instruction=INSTRUCTION,
    tools=[get_mcp_toolset(), FunctionTool(func=execute_sql_on_server)],
    output_key="database_artifacts",
)
