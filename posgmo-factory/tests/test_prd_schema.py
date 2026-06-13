"""Tests for PRD input validation and SpecificationJSON shape."""

import pytest
from pydantic import ValidationError

from prd_schema import (
    AllowedRole,
    DBColumnSpec,
    DBSpec,
    BackendSpec,
    FieldDef,
    FieldType,
    FrontendSpec,
    PRDInput,
    SpecificationJSON,
)


# ---------------------------------------------------------------------------
# PRDInput
# ---------------------------------------------------------------------------

def test_prd_rejects_company_id_in_fields():
    with pytest.raises(ValidationError, match="companyId"):
        PRDInput.model_validate({
            "module": "supplier",
            "description": "Manages product suppliers for POS GMO companies.",
            "fields": [{"name": "companyId", "type": "number"}],
        })


def test_prd_valid_without_company_id():
    prd = PRDInput.model_validate({
        "module": "supplier",
        "description": "Manages product suppliers for POS GMO companies.",
        "fields": [
            {"name": "supplierName", "type": "string"},
            {"name": "phone", "type": "string", "required": False},
        ],
    })
    assert prd.module == "supplier"
    assert len(prd.fields) == 2


def test_prd_rejects_pascal_case_module():
    with pytest.raises(ValidationError):
        PRDInput.model_validate({
            "module": "Supplier",
            "description": "Test module for validation.",
            "fields": [{"name": "name", "type": "string"}],
        })


def test_prd_rejects_empty_fields():
    with pytest.raises(ValidationError):
        PRDInput.model_validate({
            "module": "supplier",
            "description": "Some description here.",
            "fields": [],
        })


def test_prd_fk_must_be_paired():
    with pytest.raises(ValidationError, match="fk_table and fk_column"):
        PRDInput.model_validate({
            "module": "supplier",
            "description": "Manages product suppliers for POS GMO companies.",
            "fields": [{"name": "categoryId", "type": "number", "fk_table": "categories"}],
        })


def test_prd_valid_fk():
    prd = PRDInput.model_validate({
        "module": "supplier",
        "description": "Manages product suppliers for POS GMO companies.",
        "fields": [{"name": "categoryId", "type": "number",
                    "fk_table": "categories", "fk_column": "categoryid"}],
    })
    assert prd.fields[0].fk_table == "categories"


def test_prd_default_roles():
    prd = PRDInput.model_validate({
        "module": "supplier",
        "description": "Manages product suppliers for POS GMO companies.",
        "fields": [{"name": "name", "type": "string"}],
    })
    assert AllowedRole.admin in prd.roles_allowed
    assert AllowedRole.manager in prd.roles_allowed


# ---------------------------------------------------------------------------
# SpecificationJSON
# ---------------------------------------------------------------------------

def _valid_spec() -> dict:
    return {
        "module": "supplier",
        "description": "Manages product suppliers.",
        "db": {
            "table_name": "suppliers",
            "sp_prefix": "sp_suppliers",
            "columns": [
                {"name": "supplierId", "sql_type": "int", "nullable": False},
                {"name": "supplierName", "sql_type": "nvarchar(200)", "nullable": False},
                {"name": "companyId", "sql_type": "int", "nullable": False},
            ],
        },
        "backend": {
            "module_file":   "modules/suppliers.py",
            "route_file":    "routes_/supplier.py",
            "router_prefix": "/suppliers",
            "sp_calls":      ["sp_suppliers", "sp_suppliers_all", "sp_suppliers_one"],
        },
        "frontend": {
            "api_file":              "src/api/supplierApi.ts",
            "page_file":             "src/pages/SupplierPage.tsx",
            "css_file":              "src/pages/SupplierPage.css",
            "route_path":            "/suppliers",
            "roles":                 ["Admin", "Manager"],
            "has_list_view":         True,
            "has_detail_view":       False,
            "typescript_interfaces": ["Supplier", "SupplierApiResponse"],
        },
    }


def test_spec_valid():
    spec = SpecificationJSON.model_validate(_valid_spec())
    assert spec.module == "supplier"
    assert spec.db.sp_prefix == "sp_suppliers"
    assert spec.backend.module_file == "modules/suppliers.py"
    assert spec.backend.route_file == "routes_/supplier.py"


def test_spec_auto_corrects_module_file():
    # SpecificationJSON auto-corrects models/ -> modules/ prefix
    data = _valid_spec()
    data["backend"]["module_file"] = "models/suppliers.py"
    spec = SpecificationJSON.model_validate(data)
    assert spec.backend.module_file == "modules/suppliers.py"


def test_spec_auto_corrects_route_file():
    # SpecificationJSON auto-corrects routes/ -> routes_/ prefix
    data = _valid_spec()
    data["backend"]["route_file"] = "routes/supplier.py"
    spec = SpecificationJSON.model_validate(data)
    assert spec.backend.route_file == "routes_/supplier.py"


def test_spec_enforces_plural_module_file():
    # module_file must be modules/{plural}.py (plural form)
    data = _valid_spec()
    data["backend"]["module_file"] = "modules/supplier.py"   # singular -- should be corrected to plural
    spec = SpecificationJSON.model_validate(data)
    assert spec.backend.module_file == "modules/suppliers.py"


def test_spec_enforces_api_file_naming():
    # api_file is always enforced to src/api/{module}Api.ts
    data = _valid_spec()
    data["frontend"]["api_file"] = "src/api/supplierapi.ts"  # wrong suffix
    spec = SpecificationJSON.model_validate(data)
    assert spec.frontend.api_file == "src/api/supplierApi.ts"