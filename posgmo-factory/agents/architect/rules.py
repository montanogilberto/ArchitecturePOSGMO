"""
Architect — naming rules constants.
These are the machine-readable conventions referenced in INSTRUCTION.
"""

# SQL type mapping from PRD field types
PRD_TYPE_TO_SQL: dict[str, str] = {
    "string":   "nvarchar(255)",
    "text":     "nvarchar(MAX)",
    "number":   "int",
    "integer":  "int",
    "decimal":  "decimal(10,2)",
    "float":    "decimal(5,4)",   # confidence scores / ratios
    "boolean":  "bit",
    "date":     "datetime",
    "datetime": "datetime",
}

# Mandatory audit columns for every POS domain table
AUDIT_COLUMNS: list[dict] = [
    {"name": "created_At", "sql_type": "datetime", "nullable": False},
    {"name": "updated_at", "sql_type": "datetime", "nullable": True},
]

# Forbidden audit field name variants (caught by reviewer)
FORBIDDEN_AUDIT_NAMES: set[str] = {
    "createdAt", "updatedAt", "created_at", "updated_At",
    "CreatedAt", "UpdatedAt", "CREATED_AT", "UPDATED_AT",
}

# SP naming rule: always plural
def sp_names(plural: str) -> dict[str, str]:
    """Return the three SP names for a given plural module name."""
    return {
        "prefix": f"sp_{plural}",
        "upsert": f"sp_{plural}",
        "all":    f"sp_{plural}_all",
        "one":    f"sp_{plural}_one",
    }

# File path rules
def file_paths(module: str, plural: str) -> dict[str, str]:
    """Return canonical file paths for a module."""
    Module = module[:1].upper() + module[1:]
    return {
        "module_file": f"modules/{plural}.py",
        "route_file":  f"routes_/{module}.py",
        "api_file":    f"src/api/{module}Api.ts",
        "page_file":   f"src/pages/{Module}Page.tsx",
        "css_file":    f"src/pages/{Module}Page.css",
    }