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
            "Every domain table must include companyId INT NOT NULL for multi-tenant isolation.",
            "SP parameter: @pjsonfile VARCHAR(MAX) — VARCHAR not NVARCHAR.",
            "SP naming: sp_{plural}, sp_{plural}_all, sp_{plural}_one.",
            "JSON input wraps rows in an array under the plural key: { \"{plural}\": [ {...} ] }.",
            "Parse action as integer: TRY_CONVERT(INT, JSON_VALUE(value, '$.action')) FROM OPENJSON(@pjsonfile, '$.{plural}').",
            "Actions: 1=INSERT, 2=UPDATE, 3=DELETE — never string 'INSERT'/'UPDATE'.",
            "Always declare a @payload TABLE variable and INSERT from OPENJSON before using data.",
            "Standard output: @Outputmessage with result[0].value/msg/error JSON, finalized via GOTO Finish.",
            "Run duplicate validations (payload-internal + table join) before INSERT/UPDATE.",
            "sp_{plural}_all: no parameter, FOR JSON AUTO, ROOT('{plural}') — NOT FOR JSON PATH.",
            "sp_{plural}_one: reads {module}Id via OPENJSON, FOR JSON AUTO, ROOT('{plural}').",
            "Wrap nullable columns with ISNULL(col, 0/''). updated_at uses ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '').",
            "Audit columns EXACT casing: created_At (capital A) and updated_at (all lowercase). No other form is accepted.",
            "Column names: snake_case (first_name, last_name). Audit fields: created_At, updated_at.",
            "POS tables use DATETIME not DATETIME2.",
            "Primary keys: {module}Id INT IDENTITY(1,1) NOT NULL.",
            "Never issue raw SQL from Python — always EXEC via pyodbc.",
        ],
        "backend": [
            "Two files per module: modules/{plural}.py (PLURAL, SP logic) and routes_/{module}.py (singular, HTTP router).",
            "modules/{plural}.py: imports `from fastapi.responses import JSONResponse` AND `from databases import connection`.",
            "modules/{plural}.py: conn = connection() at module level.",
            "modules/{plural}.py: three functions — {plural}_sp(json_file), all_{plural}_sp(), one_{plural}_sp(json_file).",
            "DB calls: cursor.execute('EXEC [dbo].[sp_{plural}] @pjsonfile = %s', (json.dumps(json_file),)).",
            "all_{plural}_sp: cursor.fetchall(), join row[0] strings, json.loads the result.",
            "{module}_sp: cursor.fetchall(), return json_result[0][1].",
            "one_{module}_sp: cursor.fetchone()[0], json.loads the result.",
            "All functions return JSONResponse directly — no Pydantic, no raise HTTPException.",
            "routes_/{module}.py: `from modules.{plural} import {plural}_sp, all_{plural}_sp, one_{plural}_sp`.",
            "routes_/{module}.py: router = APIRouter() with NO prefix and NO tags.",
            "routes_/{module}.py: exactly 3 endpoints — POST /{plural}, GET /all_{plural}, POST /one_{plural}.",
            "Each route endpoint reads its OpenAPI description from ./docs_description/{plural}*.txt before the decorator.",
            "Route functions are plain `def`, not async. Body is `json: dict`. Just delegate: `return {plural}_sp(json)`.",
            "No Pydantic, no HTTPException, no response_model, no status codes in route file.",
            "Generate 3 docs_description txt files: {plural}.txt, {plural}_all.txt, {plural}_one.txt.",
            "NEVER import FastAPI or Pydantic in the module file (modules/).",
            "NEVER write raw SQL — only EXEC [dbo].[sp_*] calls.",
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
# Domain knowledge tool
# ---------------------------------------------------------------------------

# Canonical domain catalog keyed by module name (and common aliases).
# The PRD Enricher Agent calls this to inject context before the Architect runs.
_DOMAIN_CATALOG: dict[str, dict] = {
    # ── FINANCIAL ─────────────────────────────────────────────────────────
    "loan": {
        "tier": "TIER_2_FINANCIAL",
        "suggested_fields": [
            {"name": "principal",       "type": "decimal", "required": True,  "description": "Loan principal amount"},
            {"name": "interest_rate",   "type": "decimal", "required": True,  "description": "Annual interest rate (e.g. 0.12 = 12%)"},
            {"name": "term_months",     "type": "integer", "required": True,  "description": "Loan duration in months"},
            {"name": "disbursement_date","type": "datetime","required": False, "description": "Date the loan was disbursed to the client"},
            {"name": "due_date",        "type": "datetime","required": False,  "description": "Final payment due date"},
            {"name": "status",          "type": "string",  "required": True,  "description": "Workflow state: pending/approved/active/paid/defaulted/rejected/cancelled"},
            {"name": "clientId",        "type": "integer", "required": True,  "description": "FK → clients table for multi-tenant isolation"},
            {"name": "notes",           "type": "text",    "required": False, "description": "Free-text remarks for the loan officer"},
        ],
        "relationships": ["clients", "companies"],
        "workflow": {
            "field": "status",
            "states": ["pending", "approved", "active", "paid", "defaulted", "rejected", "cancelled"],
            "transitions": {
                "pending":  ["approved", "rejected"],
                "approved": ["active", "cancelled"],
                "active":   ["paid", "defaulted"],
            },
            "initial_state": "pending",
            "terminal_states": ["paid", "defaulted", "rejected", "cancelled"],
        },
        "business_rules": [
            "principal must be > 0",
            "interest_rate must be between 0 and 1 (store as decimal, display as %)",
            "term_months must be between 1 and 360",
            "clientId must reference an existing client in the same company",
            "Only admin/manager can approve or disburse — employee cannot change status",
            "Once status=active, principal and interest_rate are immutable",
        ],
        "validation_rules": [
            {"field": "principal",     "rule": "> 0",       "error_msg": "El monto debe ser mayor a cero"},
            {"field": "interest_rate", "rule": "0 < x < 1", "error_msg": "La tasa debe estar entre 0 y 1"},
            {"field": "term_months",   "rule": "1-360",     "error_msg": "El plazo debe ser entre 1 y 360 meses"},
        ],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": True,
            "amount_format": "currency",
            "primary_display_field": "clientId",
            "secondary_display_field": "principal",
            "action_buttons": ["Approve", "Disburse", "Mark Paid"],
            "status_colors": {
                "pending": "warning", "approved": "primary", "active": "success",
                "paid": "medium", "defaulted": "danger", "rejected": "dark", "cancelled": "light",
            },
        },
    },
    "income": {
        "tier": "TIER_2_FINANCIAL",
        "suggested_fields": [
            {"name": "amount",       "type": "decimal",  "required": True,  "description": "Income amount"},
            {"name": "concept",      "type": "string",   "required": True,  "description": "Income description/concept"},
            {"name": "income_date",  "type": "datetime", "required": True,  "description": "Date of the income entry"},
            {"name": "reference",    "type": "string",   "required": False, "description": "External reference or receipt number"},
            {"name": "categoryId",   "type": "integer",  "required": False, "description": "FK → categories for reporting"},
        ],
        "relationships": ["companies", "categories"],
        "workflow": None,
        "business_rules": [
            "amount must be > 0",
            "income_date cannot be in the future",
            "amounts are display-only on frontend — never recompute totals client-side",
        ],
        "validation_rules": [
            {"field": "amount", "rule": "> 0", "error_msg": "El monto debe ser mayor a cero"},
        ],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "currency",
            "primary_display_field": "concept",
            "secondary_display_field": "amount",
            "action_buttons": [],
        },
    },
    "expense": {
        "tier": "TIER_2_FINANCIAL",
        "suggested_fields": [
            {"name": "amount",       "type": "decimal",  "required": True,  "description": "Expense amount"},
            {"name": "concept",      "type": "string",   "required": True,  "description": "Expense description"},
            {"name": "expense_date", "type": "datetime", "required": True,  "description": "Date of the expense"},
            {"name": "reference",    "type": "string",   "required": False, "description": "Receipt or invoice reference"},
            {"name": "categoryId",   "type": "integer",  "required": False, "description": "FK → categories"},
        ],
        "relationships": ["companies", "categories"],
        "workflow": None,
        "business_rules": [
            "amount must be > 0",
            "IVA is always 0 — never compute tax",
            "amounts are display-only on frontend",
        ],
        "validation_rules": [
            {"field": "amount", "rule": "> 0", "error_msg": "El monto debe ser mayor a cero"},
        ],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "currency",
            "primary_display_field": "concept",
            "secondary_display_field": "amount",
            "action_buttons": [],
        },
    },
    # ── TRANSACTIONAL ─────────────────────────────────────────────────────
    "sale": {
        "tier": "TIER_3_TRANSACTIONAL",
        "suggested_fields": [
            {"name": "clientId",    "type": "integer",  "required": False, "description": "FK → clients (optional for anonymous sales)"},
            {"name": "total",       "type": "decimal",  "required": True,  "description": "Total sale amount — computed server-side only"},
            {"name": "status",      "type": "string",   "required": True,  "description": "draft/confirmed/paid/cancelled"},
            {"name": "sale_date",   "type": "datetime", "required": True,  "description": "Date and time of the sale"},
            {"name": "payment_method", "type": "string","required": False, "description": "cash/card/transfer"},
        ],
        "relationships": ["clients", "products", "companies"],
        "workflow": {
            "field": "status",
            "states": ["draft", "confirmed", "paid", "cancelled"],
            "transitions": {
                "draft":     ["confirmed", "cancelled"],
                "confirmed": ["paid", "cancelled"],
            },
            "initial_state": "draft",
            "terminal_states": ["paid", "cancelled"],
        },
        "business_rules": [
            "total is ALWAYS computed by the stored procedure — never by the frontend",
            "Stock must be decremented when status transitions to paid",
            "A cancelled sale must restore stock",
            "IVA is always 0",
        ],
        "validation_rules": [
            {"field": "total", "rule": ">= 0", "error_msg": "El total no puede ser negativo"},
        ],
        "ui_hints": {
            "layout": "master-detail",
            "status_badge": True,
            "amount_format": "currency",
            "primary_display_field": "sale_date",
            "secondary_display_field": "total",
            "action_buttons": ["Confirm", "Pay", "Cancel"],
        },
    },
    "order": {
        "tier": "TIER_3_TRANSACTIONAL",
        "suggested_fields": [
            {"name": "clientId",    "type": "integer",  "required": True,  "description": "FK → clients"},
            {"name": "total",       "type": "decimal",  "required": True,  "description": "Order total — server-side only"},
            {"name": "status",      "type": "string",   "required": True,  "description": "pending/processing/shipped/delivered/cancelled"},
            {"name": "order_date",  "type": "datetime", "required": True,  "description": "Date the order was placed"},
            {"name": "delivery_date","type": "datetime","required": False, "description": "Expected or actual delivery date"},
        ],
        "relationships": ["clients", "products", "companies"],
        "workflow": {
            "field": "status",
            "states": ["pending", "processing", "shipped", "delivered", "cancelled"],
            "transitions": {
                "pending":    ["processing", "cancelled"],
                "processing": ["shipped", "cancelled"],
                "shipped":    ["delivered"],
            },
            "initial_state": "pending",
            "terminal_states": ["delivered", "cancelled"],
        },
        "business_rules": [
            "total computed server-side only",
            "Stock reserved on creation, decremented on delivered",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "master-detail",
            "status_badge": True,
            "amount_format": "currency",
            "primary_display_field": "clientId",
            "secondary_display_field": "total",
            "action_buttons": ["Process", "Ship", "Mark Delivered"],
        },
    },
    # ── CATALOG ───────────────────────────────────────────────────────────
    "supplier": {
        "tier": "TIER_1_CATALOG",
        "suggested_fields": [
            {"name": "active", "type": "string", "required": True, "description": "1=active 0=inactive — matches POS GMO convention"},
        ],
        "relationships": ["companies"],
        "workflow": None,
        "business_rules": [
            "active field uses '1'/'0' strings — NOT boolean bit — matches existing POS GMO convention",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "plain",
            "primary_display_field": "supplierName",
            "secondary_display_field": "contactName",
            "action_buttons": [],
        },
    },
    "product": {
        "tier": "TIER_1_CATALOG",
        "suggested_fields": [
            {"name": "price",       "type": "decimal",  "required": True,  "description": "Sale price"},
            {"name": "cost",        "type": "decimal",  "required": False, "description": "Purchase cost for margin tracking"},
            {"name": "stock",       "type": "integer",  "required": False, "description": "Current stock quantity"},
            {"name": "barcode",     "type": "string",   "required": False, "description": "EAN/UPC barcode for QR scanner"},
            {"name": "categoryId",  "type": "integer",  "required": False, "description": "FK → categories"},
            {"name": "active",      "type": "string",   "required": True,  "description": "1=active 0=inactive"},
        ],
        "relationships": ["categories", "companies"],
        "workflow": None,
        "business_rules": [
            "price must be >= 0",
            "IVA is always 0",
            "stock is managed by sale/purchase SPs — not directly editable in this module",
        ],
        "validation_rules": [
            {"field": "price", "rule": ">= 0", "error_msg": "El precio no puede ser negativo"},
        ],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "currency",
            "primary_display_field": "productName",
            "secondary_display_field": "price",
            "action_buttons": [],
        },
    },
    "client": {
        "tier": "TIER_1_CATALOG",
        "suggested_fields": [
            {"name": "first_name",  "type": "string",  "required": True,  "description": "Client first name"},
            {"name": "last_name",   "type": "string",  "required": True,  "description": "Client last name"},
            {"name": "cellphone",   "type": "string",  "required": False, "description": "Primary contact phone"},
            {"name": "email",       "type": "string",  "required": False, "description": "Email address"},
            {"name": "address",     "type": "text",    "required": False, "description": "Full address"},
            {"name": "active",      "type": "string",  "required": True,  "description": "1=active 0=inactive"},
        ],
        "relationships": ["companies"],
        "workflow": None,
        "business_rules": [
            "Client is referenced by loans, sales, and orders — do not delete, only deactivate",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "plain",
            "primary_display_field": "first_name",
            "secondary_display_field": "cellphone",
            "action_buttons": [],
        },
    },
    "category": {
        "tier": "TIER_1_CATALOG",
        "suggested_fields": [
            {"name": "categoryName", "type": "string", "required": True,  "description": "Category display name"},
            {"name": "description",  "type": "text",   "required": False, "description": "Optional description"},
            {"name": "active",       "type": "string", "required": True,  "description": "1=active 0=inactive"},
        ],
        "relationships": ["companies"],
        "workflow": None,
        "business_rules": [],
        "validation_rules": [],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "plain",
            "primary_display_field": "categoryName",
            "secondary_display_field": "description",
            "action_buttons": [],
        },
    },
    "user": {
        "tier": "TIER_1_CATALOG",
        "suggested_fields": [
            {"name": "first_name",  "type": "string", "required": True,  "description": "First name"},
            {"name": "last_name",   "type": "string", "required": True,  "description": "Last name"},
            {"name": "email",       "type": "string", "required": True,  "description": "Login email"},
            {"name": "roleId",      "type": "integer","required": True,  "description": "FK → roles table"},
            {"name": "active",      "type": "string", "required": True,  "description": "1=active 0=inactive"},
        ],
        "relationships": ["companies", "roles"],
        "workflow": None,
        "business_rules": [
            "Passwords are NEVER stored in the module file — handled by auth service",
            "Only admin can create/modify users",
        ],
        "validation_rules": [
            {"field": "email", "rule": "valid email format", "error_msg": "Correo inválido"},
        ],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": False,
            "amount_format": "plain",
            "primary_display_field": "first_name",
            "secondary_display_field": "email",
            "action_buttons": [],
        },
    },
    # ── IOT ───────────────────────────────────────────────────────────────
    "sensor": {
        "tier": "TIER_4_IOT",
        "suggested_fields": [
            {"name": "sensor_name",  "type": "string",  "required": True,  "description": "Human-readable sensor identifier"},
            {"name": "value",        "type": "decimal", "required": True,  "description": "Sensor reading value"},
            {"name": "unit",         "type": "string",  "required": False, "description": "Unit of measurement (°C, %, psi)"},
            {"name": "read_at",      "type": "datetime","required": True,  "description": "Timestamp of the reading — use DATETIME2(3)"},
            {"name": "deviceId",     "type": "integer", "required": False, "description": "FK → devices table"},
            {"name": "alert_flag",   "type": "string",  "required": False, "description": "0=normal 1=threshold exceeded"},
        ],
        "relationships": ["companies", "devices"],
        "workflow": None,
        "business_rules": [
            "Use DATETIME2(3) for read_at — millisecond precision required for IoT",
            "No IonInfiniteScroll — use IonCard chart view instead",
            "Readings are INSERT-only — no UPDATE or DELETE actions",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "chart-view",
            "status_badge": False,
            "amount_format": "plain",
            "primary_display_field": "sensor_name",
            "secondary_display_field": "value",
            "action_buttons": [],
        },
    },
    "device": {
        "tier": "TIER_4_IOT",
        "suggested_fields": [
            {"name": "device_name",  "type": "string", "required": True,  "description": "Device display name"},
            {"name": "mac_address",  "type": "string", "required": False, "description": "Hardware MAC address"},
            {"name": "location",     "type": "string", "required": False, "description": "Physical location description"},
            {"name": "active",       "type": "string", "required": True,  "description": "1=active 0=inactive"},
            {"name": "last_seen",    "type": "datetime","required": False, "description": "Last heartbeat timestamp"},
        ],
        "relationships": ["companies"],
        "workflow": None,
        "business_rules": [
            "Use DATETIME2(3) for last_seen",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": True,
            "amount_format": "plain",
            "primary_display_field": "device_name",
            "secondary_display_field": "location",
            "action_buttons": [],
        },
    },
    # ── LAUNDRY / VENDING ─────────────────────────────────────────────────
    "laundry": {
        "tier": "TIER_3_TRANSACTIONAL",
        "suggested_fields": [
            {"name": "clientId",     "type": "integer",  "required": False, "description": "FK → clients (optional)"},
            {"name": "weight_kg",    "type": "decimal",  "required": False, "description": "Load weight in kilograms"},
            {"name": "total",        "type": "decimal",  "required": True,  "description": "Total charge — server-side"},
            {"name": "status",       "type": "string",   "required": True,  "description": "received/washing/drying/ready/delivered/cancelled"},
            {"name": "received_at",  "type": "datetime", "required": True,  "description": "Drop-off timestamp"},
            {"name": "delivery_at",  "type": "datetime", "required": False, "description": "Pickup timestamp"},
        ],
        "relationships": ["clients", "companies"],
        "workflow": {
            "field": "status",
            "states": ["received", "washing", "drying", "ready", "delivered", "cancelled"],
            "transitions": {
                "received": ["washing", "cancelled"],
                "washing":  ["drying"],
                "drying":   ["ready"],
                "ready":    ["delivered"],
            },
            "initial_state": "received",
            "terminal_states": ["delivered", "cancelled"],
        },
        "business_rules": [
            "total computed server-side only",
            "IVA is always 0",
        ],
        "validation_rules": [],
        "ui_hints": {
            "layout": "list-with-modal",
            "status_badge": True,
            "amount_format": "currency",
            "primary_display_field": "received_at",
            "secondary_display_field": "status",
            "action_buttons": ["Mark Washing", "Mark Drying", "Mark Ready", "Mark Delivered"],
            "status_colors": {
                "received": "warning", "washing": "primary", "drying": "tertiary",
                "ready": "success", "delivered": "medium", "cancelled": "danger",
            },
        },
    },
}

# Common aliases → canonical module name
_ALIASES = {
    "loans":    "loan",
    "incomes":  "income",
    "expenses": "expense",
    "sales":    "sale",
    "orders":   "order",
    "suppliers":"supplier",
    "products": "product",
    "clients":  "client",
    "categories":"category",
    "users":    "user",
    "sensors":  "sensor",
    "devices":  "device",
    "laundries":"laundry",
    "egreso":   "expense",
    "egresos":  "expense",
    "ingreso":  "income",
    "ingresos": "income",
    "prestamo": "loan",
    "prestamos":"loan",
    "venta":    "sale",
    "ventas":   "sale",
    "proveedor":"supplier",
    "proveedores":"supplier",
    "producto": "product",
    "productos":"product",
    "cliente":  "client",
    "clientes": "client",
    "categoria":"category",
    "categorias":"category",
    "usuario":  "user",
    "usuarios": "user",
}

# Default for unknown modules
_CATALOG_DEFAULT = {
    "tier": "TIER_1_CATALOG",
    "suggested_fields": [],
    "relationships": ["companies"],
    "workflow": None,
    "business_rules": [
        "companyId is required for multi-tenant isolation",
        "Use active field ('1'/'0') for soft-delete pattern",
    ],
    "validation_rules": [],
    "ui_hints": {
        "layout": "list-with-modal",
        "status_badge": False,
        "amount_format": "plain",
        "primary_display_field": "",
        "secondary_display_field": "",
        "action_buttons": [],
    },
}


@mcp.tool()
def get_domain_rules(module_name: str) -> dict:
    """
    Returns domain-specific context for a given module name:
    tier classification, suggested fields, workflow states and transitions,
    business rules, validation rules, and UI layout hints.

    Called by the PRD Enricher Agent to inject context into thin PRDs
    before the Architect generates the SpecificationJSON.

    Args:
        module_name: Singular or plural module name in any language
                     (e.g. "loan", "loans", "prestamo", "supplier", "sale").

    Returns:
        dict with keys: tier, suggested_fields, workflow, business_rules,
        validation_rules, ui_hints. Falls back to TIER_1_CATALOG defaults
        if the module is not in the catalog.
    """
    key = module_name.lower().strip()
    canonical = _ALIASES.get(key, key)
    result = _DOMAIN_CATALOG.get(canonical, _CATALOG_DEFAULT).copy()
    result["matched_module"] = canonical
    result["input_module"]   = module_name
    return result


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
