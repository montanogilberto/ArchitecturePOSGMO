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

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# PRD enums
# ---------------------------------------------------------------------------

class FieldType(str, Enum):
    string   = "string"
    number   = "number"
    boolean  = "boolean"
    date     = "date"
    text     = "text"       # long-form nvarchar(MAX)
    decimal  = "decimal"


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
    relationships: List[str] = Field(
        default_factory=list,
        description="Existing POS GMO table names this module depends on.",
    )
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
    module_file: str                # e.g. "modules/supplier.py"  — business logic / SP calls
    route_file: str                 # e.g. "routes_/supplier.py"  — FastAPI router
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


class SpecificationJSON(BaseModel):
    module: str
    description: str
    db: DBSpec
    backend: BackendSpec
    frontend: FrontendSpec

    @model_validator(mode="after")
    def files_follow_naming(self) -> "SpecificationJSON":
        m = self.module

        # Coerce common LLM mistakes so the pipeline never crashes on minor path deviations.
        # "models/" is a frequent mistake — silently correct it to "modules/".
        self.backend.module_file = self.backend.module_file.replace("models/", "modules/")
        # "routes/" without underscore — correct to "routes_/"
        if self.backend.route_file.startswith("routes/"):
            self.backend.route_file = "routes_/" + self.backend.route_file[len("routes/"):]

        # Enforce canonical paths after coercion.
        if self.backend.module_file != f"modules/{m}.py":
            self.backend.module_file = f"modules/{m}.py"
        if self.backend.route_file != f"routes_/{m}.py":
            self.backend.route_file = f"routes_/{m}.py"
        if self.frontend.api_file != f"src/api/{m}Api.ts":
            self.frontend.api_file = f"src/api/{m}Api.ts"

        return self
