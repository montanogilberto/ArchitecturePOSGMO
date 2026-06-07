"""
POS GMO Knowledge MCP Server

Exposes all architecture knowledge files as MCP tools so ADK agents
can retrieve patterns before generating any code.

Run:
    python -m mcp_server.server            # stdio transport (default)
    MCP_TRANSPORT=http python -m mcp_server.server  # HTTP transport
"""

import csv
import json
import os
from pathlib import Path

from fastmcp import FastMCP

# Root of the ArquitecturePOS repository (one level up from posgmo-factory/)
KNOWLEDGE_ROOT = Path(__file__).parent.parent.parent

mcp = FastMCP("posgmo-knowledge")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _json(relative: str) -> any:
    path = KNOWLEDGE_ROOT / relative
    if not path.exists():
        return {"error": f"Knowledge file not found: {relative}"}
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(relative: str, fieldnames: list[str]) -> list[dict]:
    path = KNOWLEDGE_ROOT / relative
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, fieldnames=fieldnames))


# ---------------------------------------------------------------------------
# Frontend tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_frontend_patterns() -> dict:
    """
    Returns the complete frontend knowledge base:
    architecture overview, modules, routes, UI patterns, and component catalog.

    Agents MUST call this before generating any frontend file.
    """
    return {
        "architecture":  _json("Frontend/frontend_knowledge.json"),
        "modules":       _json("Frontend/frontend_modules.json.json"),
        "routes":        _json("Frontend/frontend_routes.json.json"),
        "ui_patterns":   _json("Frontend/frontend_ui_patterns.json.json"),
        "components":    _json("Frontend/frontend_components.json.json"),
    }


@mcp.tool()
def get_api_contracts() -> list:
    """
    Returns all documented frontend → backend API contracts (request + response shapes).

    Use this to derive TypeScript interfaces and ensure the generated API
    client matches what the backend stored procedures return.
    """
    return _json("Frontend/frontend_api_contracts.json.json")


@mcp.tool()
def get_ui_patterns() -> list:
    """
    Returns POS GMO UI implementation patterns:
    UTC-7 conversion, infinite scroll, inactivity watchdog, IVA=0 override, API fallback.

    Every frontend agent must apply these patterns where relevant.
    """
    return _json("Frontend/frontend_ui_patterns.json.json")


@mcp.tool()
def get_component_catalog() -> list:
    """
    Returns the catalog of reusable Ionic React components with props signatures.

    Agents must reuse these components rather than inventing new ones.
    """
    return _json("Frontend/frontend_components.json.json")


# ---------------------------------------------------------------------------
# Backend tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_backend_patterns() -> dict:
    """
    Returns the complete backend knowledge base:
    architecture pipeline, models, schemas, authentication flows, and business domains.

    Agents MUST call this before generating any backend file.
    """
    return {
        "architecture": _json("Backend/backend_architecture.json.json"),
        "models":       _json("Backend/backend_models.json.json"),
        "schemas":      _json("Backend/backend_schemas.json.json"),
        "auth":         _json("Backend/backend_authentication.json.json"),
        "domains":      _json("Backend/backend_business_domains.json.json"),
        "ai_features":  _json("Backend/backend_ai_features.json.json"),
        "prompts":      _json("Backend/backend_prompts.json.json"),
    }


@mcp.tool()
def get_backend_routes() -> list:
    """
    Returns all registered FastAPI routes with their file paths and tags.

    Use this to check for naming conflicts before registering a new route
    and to understand the existing route structure.
    """
    return _json("Backend/backend_routes.json.json").get("routes", [])


@mcp.tool()
def get_sp_patterns() -> list:
    """
    Returns the stored procedure catalog: names, module bindings, and parameter signatures.

    All DB mutations in POS GMO go through stored procedures.
    The universal parameter pattern is: @pjsonfile nvarchar(MAX).
    Naming convention: sp_{module}, sp_{module}_all, sp_{module}_one.
    """
    data = _json("Backend/backend_stored_procedures.json.json")
    return data.get("stored_procedures", data)


# ---------------------------------------------------------------------------
# Database tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_db_schema() -> dict:
    """
    Returns the full SQL Server column-level schema and foreign key relationships.

    Use this to:
    - Verify FK targets exist before declaring a foreign key.
    - Follow existing column naming (camelCase), types (datetime not datetime2 for POS),
      and nullability conventions.
    - Confirm companyId is present for multi-tenant isolation.
    """
    columns = _csv_rows(
        "Database/structure_database.csv",
        fieldnames=["schema", "table", "column", "type", "length",
                    "nullable", "pk", "fk", "extra"],
    )
    return {
        "columns":       columns,
        "relationships": _json("Database/sql_relationships.json"),
    }


@mcp.tool()
def get_table_list() -> list[str]:
    """
    Returns a deduplicated list of all table names in the POS GMO database.

    Use this for quick existence checks before referencing a table.
    """
    rows = _csv_rows(
        "Database/structure_database.csv",
        fieldnames=["schema", "table", "column", "type", "length",
                    "nullable", "pk", "fk", "extra"],
    )
    seen: set[str] = set()
    tables: list[str] = []
    for row in rows:
        t = row["table"]
        if t not in seen:
            seen.add(t)
            tables.append(t)
    return tables


@mcp.tool()
def get_table_columns(table_name: str) -> list[dict]:
    """
    Returns all columns for a specific table.

    Args:
        table_name: Exact table name (case-sensitive, e.g. "cashRegisterSessions").

    Use this before adding a column to confirm it doesn't already exist.
    """
    rows = _csv_rows(
        "Database/structure_database.csv",
        fieldnames=["schema", "table", "column", "type", "length",
                    "nullable", "pk", "fk", "extra"],
    )
    return [r for r in rows if r["table"] == table_name]


@mcp.tool()
def get_relationships_for_table(table_name: str) -> dict:
    """
    Returns foreign key relationships where the given table is the parent or child.

    Args:
        table_name: Exact table name (e.g. "income").
    """
    all_rels = _json("Database/sql_relationships.json")
    return {
        "as_parent": [r for r in all_rels if r["parent_table"] == table_name],
        "as_child":  [r for r in all_rels if r["child_table"]  == table_name],
    }


# ---------------------------------------------------------------------------
# Cross-cutting tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_generation_rules() -> dict:
    """
    Returns the generation rules every agent must follow:
    naming conventions, forbidden patterns, required fields, and quality gates.
    """
    return {
        "global": [
            "Never invent architecture. Always reuse POS GMO patterns.",
            "Always call the relevant MCP knowledge tool before generating.",
            "Prefer consistency over creativity.",
            "Generate production-ready code only.",
            "Follow SOLID and Clean Architecture.",
        ],
        "database": [
            "All tables live in the dbo schema.",
            "Every domain table must include companyId (int, NOT NULL) for multi-tenant isolation.",
            "SP parameter signature: @pjsonfile nvarchar(MAX).",
            "SP naming: sp_{module}, sp_{module}_all, sp_{module}_one.",
            "Parse JSON inside SPs with OPENJSON.",
            "Return resultsets with FOR JSON PATH.",
            "POS tables use datetime. Marketplace/analytics tables use datetime2.",
            "Primary keys: {entity}Id int IDENTITY(1,1) NOT NULL.",
            "Never issue raw SQL from Python — always EXEC via pyodbc.",
        ],
        "backend": [
            "Routers: APIRouter(prefix='/{module}', tags=['{Module}']).",
            "DB calls: cursor.execute('EXEC sp_{module} @pjsonfile=?', json.dumps(payload)).",
            "Pydantic models: Optional[T] for nullable columns.",
            "Docstrings: Google style with Args and Returns sections.",
            "All mutations use POST. GET for reads.",
        ],
        "frontend": [
            "Page shell: IonPage > IonHeader > IonToolbar > IonContent.",
            "API client: plain fetch(), TypeScript interfaces required.",
            "UTC to Hermosillo (UTC-7): subtract 7*60*60*1000 ms from UTC date.",
            "IVA is always 0. Never compute tax from server response.",
            "Loading state: IonLoading. Errors: IonToast.",
            "Lists > 20 items must use IonInfiniteScroll pattern.",
            "CSS: scoped file per page, no global style mutations.",
        ],
        "reviewer_thresholds": {
            "min_score_to_pass": 90,
            "regenerate_on_fail": True,
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "http":
        port = int(os.getenv("MCP_HTTP_PORT", "8100"))
        mcp.run(transport="http", port=port)
    else:
        mcp.run(transport="stdio")
