"""
PRD Schema — gate that validates every feature request before it enters the pipeline.

Usage:
    from prd_schema import PRDInput, SpecificationJSON
    prd = PRDInput.model_validate(raw_dict)       # raises ValidationError on bad input
    spec = SpecificationJSON.model_validate(raw)  # Architect Agent output validator
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# PRD enums
# ---------------------------------------------------------------------------

class FieldType(str, Enum):
    string   = "string"
    number   = "number"
    integer  = "integer"
    boolean  = "boolean"
    date     = "date"
    datetime = "datetime"   # DATETIME column (maps to nvarchar for display, datetime for storage)
    text     = "text"       # long-form nvarchar(MAX)
    decimal  = "decimal"
    float_   = "float"      # alias → treated as decimal(5,4) by Architect


class PaymentMethod(str, Enum):
    cash         = "cash"
    card         = "card"
    transfer     = "transfer"
    mixed        = "mixed"


class AllowedRole(str, Enum):
    admin    = "Admin"
    manager  = "Manager"
    cashier  = "Cashier"


# ---------------------------------------------------------------------------
# PRD input — what a human (or orchestrating agent) submits
# ---------------------------------------------------------------------------

class FieldDef(BaseModel):
    name: str = Field(
        description="camelCase column name, e.g. 'supplierName'",
        pattern=r"^[a-z][a-zA-Z0-9]*$",
    )
    type: FieldType
    required: bool = True
    max_length: Optional[int] = None
    fk_table: Optional[str] = Field(
        default=None,
        description="Exact POS GMO table name this field references, e.g. 'companies'",
    )
    fk_column: Optional[str] = Field(
        default=None,
        description="FK column on the parent table, e.g. 'companyId'",
    )
    description: Optional[str] = None

    @model_validator(mode="after")
    def fk_columns_paired(self) -> "FieldDef":
        if (self.fk_table is None) != (self.fk_column is None):
            raise ValueError("fk_table and fk_column must both be set or both omitted.")
        return self


from pydantic import field_validator
from typing import Union

class RelationshipDef(BaseModel):
    """Rich relationship object — parentModule, cardinality, notes."""
    parentModule: Optional[str] = None
    cardinality: Optional[str] = None
    notes: Optional[str] = None


class PRDEndpoint(BaseModel):
    """Custom backend endpoint declared in PRD backend.endpoints[]."""
    path: str
    method: str = "POST"
    description: Optional[str] = None
    requestSchema: Optional[str] = None
    responseSchema: Optional[str] = None


class PRDFrontendComponent(BaseModel):
    step: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None


class PRDFrontendHints(BaseModel):
    pageRoute: Optional[str] = None
    allowedRoles: List[str] = Field(default_factory=list)
    uiPattern: Optional[str] = None
    components: List[PRDFrontendComponent] = Field(default_factory=list)


class PRDDatabaseHints(BaseModel):
    """Author hints forwarded to downstream agents as context (not enforced)."""
    tables: List[str] = Field(default_factory=list)
    storedProcedures: List[str] = Field(default_factory=list)


class PRDBackendHints(BaseModel):
    endpoints: List[PRDEndpoint] = Field(default_factory=list)


class PRDInput(BaseModel):
    module: str = Field(
        description="Singular camelCase module name, e.g. 'supplier'",
        pattern=r"^[a-z][a-zA-Z0-9]*$",
    )
    description: str = Field(
        description="One-sentence business description of the module.",
        min_length=10,
    )
    fields: List[FieldDef] = Field(
        description="List of data fields for this module.",
        min_length=1,
    )
    relationships: List[RelationshipDef] = Field(
        default_factory=list,
        description="Parent modules this module depends on (rich object or plain string).",
    )

    @field_validator("relationships", mode="before")
    @classmethod
    def _coerce_relationships(cls, v):
        """Allow plain strings: "companies" → RelationshipDef(parentModule="companies")"""
        if not isinstance(v, list):
            return v
        return [{"parentModule": item} if isinstance(item, str) else item for item in v]
    roles_allowed: List[AllowedRole] = Field(
        default_factory=lambda: [AllowedRole.admin, AllowedRole.manager],
        description="Frontend roles that may access this module's page.",
    )
    payment_methods: List[PaymentMethod] = Field(
        default_factory=list,
        description="Required only if the module handles financial transactions.",
    )
    has_list_view: bool = Field(
        default=True,
        description="Whether to generate an IonList page with search + infinite scroll.",
    )
    has_detail_view: bool = Field(
        default=False,
        description="Whether to generate a detail/edit page at /{module}/:id.",
    )
    # Rich optional sections — passed through to SpecificationJSON unchanged
    frontend: Optional[PRDFrontendHints] = Field(
        default=None,
        description="Frontend hints: pageRoute, uiPattern, wizard components.",
    )
    backend: Optional[PRDBackendHints] = Field(
        default=None,
        description="Custom backend endpoints beyond standard CRUD.",
    )
    database: Optional[PRDDatabaseHints] = Field(
        default=None,
        description="Author database hints: custom table/SP names.",
    )

    @model_validator(mode="after")
    def company_id_not_in_fields(self) -> "PRDInput":
        names = {f.name for f in self.fields}
        if "companyId" in names:
            raise ValueError(
                "Do not declare companyId in fields — it is injected automatically "
                "by all POS GMO stored procedures."
            )
        return self


# ---------------------------------------------------------------------------
# Specification JSON — Architect Agent output, consumed by downstream agents
# ---------------------------------------------------------------------------

class DBColumnSpec(BaseModel):
    name: str
    sql_type: str                   # e.g. "nvarchar(200)", "int", "decimal(10,2)"
    nullable: bool = True
    fk_table: Optional[str] = None
    fk_column: Optional[str] = None


class DBSpec(BaseModel):
    table_name: str                 # e.g. "suppliers"
    sp_prefix: str                  # e.g. "sp_suppliers"
    columns: List[DBColumnSpec]
    indexes: List[str] = Field(
        default_factory=list,
        description="Column names that need a non-clustered index.",
    )


class BackendSpec(BaseModel):
    module_file: str                # e.g. "modules/suppliers.py"  — PLURAL, business logic / SP calls
    route_file: str                 # e.g. "routes_/supplier.py"   — singular, FastAPI router
    router_prefix: str              # e.g. "/suppliers"
    sp_calls: List[str]             # e.g. ["sp_suppliers", "sp_suppliers_all", "sp_suppliers_one"]


class FrontendSpec(BaseModel):
    api_file: str                   # e.g. "src/api/supplierApi.ts"
    page_file: str                  # e.g. "src/pages/SupplierPage.tsx"
    css_file: str                   # e.g. "src/pages/SupplierPage.css"
    route_path: str                 # e.g. "/suppliers"
    roles: List[str]
    has_list_view: bool
    has_detail_view: bool
    typescript_interfaces: List[str] = Field(
        description="Names of the TS interfaces to generate, e.g. ['Supplier', 'SupplierApiResponse']",
    )


class PRDHints(BaseModel):
    """Raw PRD sections forwarded unchanged — used by Decision Gate and Backend Agent."""
    backend_endpoints: List[PRDEndpoint] = Field(default_factory=list)
    frontend_ui_pattern: Optional[str] = None
    frontend_components: List[PRDFrontendComponent] = Field(default_factory=list)
    database_tables: List[str] = Field(default_factory=list)
    database_sps: List[str] = Field(default_factory=list)


class SpecificationJSON(BaseModel):
    module: str
    description: str
    db: DBSpec
    backend: BackendSpec
    frontend: FrontendSpec
    prd_hints: PRDHints = Field(
        default_factory=PRDHints,
        description="Raw PRD hints forwarded to Decision Gate and Backend Agent.",
    )

    @model_validator(mode="after")
    def enforce_naming_standards(self) -> "SpecificationJSON":
        m = self.module       # singular e.g. "supplier"
        plural = f"{m}s"      # simple plural e.g. "suppliers"

        # ── SP naming: always plural ────────────────────────────────────────
        self.db.sp_prefix = f"sp_{plural}"
        self.backend.sp_calls = [
            f"sp_{plural}",
            f"sp_{plural}_all",
            f"sp_{plural}_one",
        ]

        # ── Audit fields: enforce exact casing ──────────────────────────────
        # Map every forbidden variant → canonical name
        _AUDIT_CORRECTIONS = {
            "createdAt":  "created_At",
            "created_at": "created_At",
            "updated_At": "updated_at",
            "updatedAt":  "updated_at",
        }
        for col in self.db.columns:
            if col.name in _AUDIT_CORRECTIONS:
                col.name = _AUDIT_CORRECTIONS[col.name]

        # Ensure both audit columns are present with correct types
        existing_names = {c.name for c in self.db.columns}
        if "created_At" not in existing_names:
            self.db.columns.append(
                DBColumnSpec(name="created_At", sql_type="datetime", nullable=False)
            )
        if "updated_at" not in existing_names:
            self.db.columns.append(
                DBColumnSpec(name="updated_at", sql_type="datetime", nullable=True)
            )

        # ── File paths ───────────────────────────────────────────────────────
        self.backend.module_file = self.backend.module_file.replace("models/", "modules/")
        if self.backend.route_file.startswith("routes/"):
            self.backend.route_file = "routes_/" + self.backend.route_file[len("routes/"):]

        self.backend.module_file = f"modules/{plural}.py"
        self.backend.route_file  = f"routes_/{m}.py"
        self.frontend.api_file   = f"src/api/{m}Api.ts"

        return self
