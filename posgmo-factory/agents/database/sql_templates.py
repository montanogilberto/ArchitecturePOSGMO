"""
Deterministic CRUD SQL generation — zero LLM calls.

database_agent was the least reliable construction layer in every milestone
(Milestone 7: 32 attempts to land all three layers in one run, database
always the laggard). Moving execution out of the tool call (see
agents/database_executor/) removed one failure mode, but the SQL itself was
still generated stochastically: MALFORMED_FUNCTION_CALL on the MCP knowledge
calls, snake_case vs camelCase column drift (factoryRun: `factory_run_id`
failed the `{module}Id` PK check), companyId filters on TENANT_INDEPENDENT
modules, missing GO separators.

But the CRUD_ONLY / CRUD_AND_CONNECTOR SQL shape is fully determined by
inputs that are already structured by the time database_agent runs:
specification.db (columns, types, FKs, indexes) + gate_result (tier,
tenant_model, soft_delete_parents, index_recommendations). So for that
shape, this module renders the four artifacts directly. The LLM stays in the
loop only for shapes a template can't honestly produce (ACTION_ROUTER,
BUSINESS_LOGIC, TIER_3 header/detail, or a gate constraint this module
doesn't recognize) — see generate_crud_sql()'s None return.
"""
from __future__ import annotations

import json
import re
from typing import Optional

TEMPLATE_PATTERNS = {"CRUD_ONLY", "CRUD_AND_CONNECTOR"}

_AUDIT_CREATED = "created_At"
_AUDIT_UPDATED = "updated_at"

_STRING_TYPES = {"NVARCHAR", "VARCHAR", "NCHAR", "CHAR", "TEXT", "NTEXT"}
_NUMERIC_TYPES = {"INT", "BIGINT", "SMALLINT", "TINYINT", "BIT", "DECIMAL", "NUMERIC", "FLOAT", "REAL", "MONEY"}
_DATE_TYPES = {"DATETIME", "DATETIME2", "DATE", "SMALLDATETIME", "DATETIMEOFFSET"}

# Logical types an architect sometimes emits instead of a SQL type.
_LOGICAL_TYPES = {
    "STRING": "NVARCHAR(255)",
    "INTEGER": "INT",
    "NUMBER": "DECIMAL(10,2)",
    "BOOLEAN": "BIT",
    "BOOL": "BIT",
    "UUID": "UNIQUEIDENTIFIER",
}

# Same monetary-name heuristic as agents/reviewer/rules.py's TIER_2 check,
# so generator and reviewer can never disagree about which columns it covers.
_MONETARY_NAME = re.compile(
    r"^(?:amount|total|price|cost|expense|income|payment|fee|balance|subtotal|discount)",
    re.IGNORECASE,
)

# gate_result.mandatory_constraints.database entries this template satisfies
# by construction. Anything NOT matched here means the gate is asking for
# something the template doesn't know how to render (a UNIQUE constraint from
# an ADR, a header/detail split, ...) -> fall back to the LLM rather than
# silently dropping a mandatory rule.
_SATISFIED_CONSTRAINTS = [
    r"companyId INT NOT NULL must be present",
    r"sp_all MUST accept @pjsonfile and filter WHERE companyId",
    r"companyId is NOT applicable to this module",
    r"Every nullable column in SELECT must be wrapped with ISNULL",
    r"SP mutations must be wrapped in BEGIN TRY",
    r"All monetary DECIMAL columns .* must be DECIMAL\(10,2\)",
    r"Non-monetary decimal columns .* keep their original precision",
    r"Use DATETIME2\(3\) instead of DATETIME",
    # TENANT_INDEPENDENT ADR boilerplate — satisfied by omitting companyId entirely.
    r"companyId must not be a NOT NULL column",
    r"must not read, accept, default, or validate against a client-supplied companyId",
]


def _safe_load(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    body = raw.strip()
    if body.startswith("```"):
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("```")).strip()
    try:
        loaded = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def unsupported_reason(spec: dict, gate: dict) -> Optional[str]:
    """None if the template can render this module faithfully, else a short
    reason it can't (recorded on the artifact so fallbacks are visible)."""
    if not spec.get("module") or not spec.get("db", {}).get("columns"):
        return "specification has no module/db.columns"
    pattern = gate.get("backend_pattern", "CRUD_ONLY")
    if pattern not in TEMPLATE_PATTERNS:
        return f"backend_pattern {pattern} is not a CRUD template shape"
    if gate.get("tier") == "TIER_3_TRANSACTIONAL":
        return "TIER_3_TRANSACTIONAL requires a header/detail table pair"
    for rule in (gate.get("mandatory_constraints") or {}).get("database", []):
        if not any(re.search(p, rule, re.IGNORECASE) for p in _SATISFIED_CONSTRAINTS):
            return f"unrecognized database constraint: {rule[:120]}"
    if gate.get("tier") == "TIER_4_IOT" and any(
        c.get("name", "").lower() == "active" for c in spec["db"]["columns"]
    ):
        return "TIER_4_IOT forbids an active flag but the spec declares one"
    return None


# ---------------------------------------------------------------------------
# Column model
# ---------------------------------------------------------------------------

def _normalize_type(sql_type: str) -> str:
    """'int IDENTITY(1,1) NOT NULL' -> 'INT', 'nvarchar(MAX)' -> 'NVARCHAR(MAX)'."""
    m = re.match(r"\s*(\w+)\s*(\([^)]*\))?", sql_type or "")
    if not m:
        return "NVARCHAR(255)"
    base = m.group(1).upper()
    if base in _LOGICAL_TYPES:
        return _LOGICAL_TYPES[base]
    size = (m.group(2) or "").replace(" ", "").upper()
    if base in {"NVARCHAR", "VARCHAR", "NCHAR", "CHAR"} and not size:
        size = "(255)"
    if base in {"DECIMAL", "NUMERIC"} and not size:
        size = "(10,2)"
    return base + size


def _base(sql_type: str) -> str:
    return sql_type.split("(", 1)[0]


def primary_key(spec: dict) -> str:
    """The spec's IDENTITY column when the architect declared one (it mirrors
    the live table when that table already exists -- live schema outranks the
    `{module}Id` naming default; found live: posRewardCatalogItems' PK is
    catalogItemId), else the `{module}Id` convention."""
    for col in spec.get("db", {}).get("columns", []):
        if "IDENTITY" in str(col.get("sql_type", "")).upper() and col.get("name"):
            return col["name"].strip()
    return f"{spec['module']}Id"


def _build_columns(spec: dict, gate: dict) -> list[dict]:
    """Returns the ordered column list the table actually gets: PK first,
    companyId next (tenant-scoped only), domain columns, audit columns last."""
    pk = primary_key(spec)
    tier = gate.get("tier", "TIER_1_CATALOG")
    tenant_scoped = gate.get("tenant_model", "TENANT_SCOPED") != "TENANT_INDEPENDENT"
    ts_type = "DATETIME2(3)" if tier == "TIER_4_IOT" else "DATETIME"

    domain: list[dict] = []
    seen = {pk.lower(), "companyid", _AUDIT_CREATED.lower(), _AUDIT_UPDATED.lower(),
            "createdat", "updatedat"}
    company_fk = None
    for col in spec["db"]["columns"]:
        name = (col.get("name") or "").strip()
        if not name:
            continue
        if name.lower() == "companyid":
            company_fk = col
            continue
        if name.lower() in seen:
            continue  # PK / audit columns are emitted canonically below
        seen.add(name.lower())
        sql_type = _normalize_type(col.get("sql_type", ""))
        if _base(sql_type) == "DATETIME2" and tier != "TIER_4_IOT":
            sql_type = "DATETIME"
        elif _base(sql_type) == "DATETIME" and tier == "TIER_4_IOT":
            sql_type = "DATETIME2(3)"
        if (tier == "TIER_2_FINANCIAL" and _base(sql_type) in {"DECIMAL", "NUMERIC"}
                and _MONETARY_NAME.match(name)):
            sql_type = "DECIMAL(10,2)"
        domain.append({
            "name": name,
            "type": sql_type,
            "nullable": bool(col.get("nullable", True)),
            "fk_table": col.get("fk_table"),
            "fk_column": col.get("fk_column"),
        })

    cols = [{"name": pk, "type": "INT", "nullable": False, "identity": True}]
    if tenant_scoped:
        cols.append({
            "name": "companyId", "type": "INT", "nullable": False,
            "fk_table": (company_fk or {}).get("fk_table"),
            "fk_column": (company_fk or {}).get("fk_column"),
        })
    cols += domain
    cols.append({"name": _AUDIT_CREATED, "type": ts_type, "nullable": False, "audit": True})
    cols.append({"name": _AUDIT_UPDATED, "type": ts_type, "nullable": True, "audit": True})
    return cols


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _select_expr(col: dict, pk: str) -> str:
    name = col["name"]
    if name == _AUDIT_UPDATED:
        return f"ISNULL(CONVERT(VARCHAR(30), {name}, 126), '') AS {name}"
    if name == pk or not col["nullable"]:
        return f"[{name}]"
    base = _base(col["type"])
    if base in _STRING_TYPES:
        return f"ISNULL([{name}], '') AS [{name}]"
    if base in _NUMERIC_TYPES:
        return f"ISNULL([{name}], 0) AS [{name}]"
    if base in _DATE_TYPES:
        return f"ISNULL(CONVERT(VARCHAR(30), [{name}], 126), '') AS [{name}]"
    return f"ISNULL(CONVERT(NVARCHAR(MAX), [{name}]), '') AS [{name}]"


def _active_literal(col: dict) -> str:
    """The platform's soft-delete convention: `active` '1' = live, whether the
    spec models it as BIT or as the string flag (NVARCHAR(1)/CHAR(1)) the
    reviewer's soft-delete check (active = '1') is written against."""
    if col["name"].lower() != "active":
        return ""
    base = _base(col["type"])
    if base == "BIT":
        return "1"
    if base in _STRING_TYPES:
        return "'1'"
    return ""


def _default_for(col: dict) -> str:
    lit = _active_literal(col)
    return f" DEFAULT {lit}" if lit else ""


def _render_create_table(table: str, cols: list[dict], pk: str, indexes: list[tuple[str, ...]]) -> str:
    lines = []
    for c in cols:
        if c.get("identity"):
            lines.append(f"    [{c['name']}] INT IDENTITY(1,1) NOT NULL")
        elif c["name"] == _AUDIT_CREATED:
            lines.append(f"    [{c['name']}] {c['type']} NOT NULL DEFAULT GETDATE()")
        else:
            null = "NULL" if c["nullable"] else "NOT NULL"
            lines.append(f"    [{c['name']}] {c['type']} {null}{_default_for(c)}")
    lines.append(f"    CONSTRAINT [PK_{table}] PRIMARY KEY CLUSTERED ([{pk}] ASC)")
    for c in cols:
        if c.get("fk_table") and c.get("fk_column"):
            lines.append(
                f"    CONSTRAINT [FK_{table}_{c['fk_table']}_{c['name']}] FOREIGN KEY ([{c['name']}]) "
                f"REFERENCES [dbo].[{c['fk_table']}]([{c['fk_column']}])"
            )
    parts = [f"CREATE TABLE [dbo].[{table}] (\n" + ",\n".join(lines) + "\n);"]
    for idx in indexes:
        ix_name = f"IX_{table}_" + "_".join(idx)
        cols_sql = ", ".join(f"[{c}]" for c in idx)
        parts.append(f"CREATE NONCLUSTERED INDEX [{ix_name}] ON [dbo].[{table}] ({cols_sql});")
    return "\nGO\n\n".join(parts) + "\nGO\n"


def _render_sp_upsert(sp: str, table: str, plural: str, cols: list[dict], pk: str,
                      tenant_scoped: bool) -> str:
    payload_cols = [c for c in cols if not c.get("audit")]
    writable = [c for c in payload_cols if not c.get("identity")]

    decl = ",\n".join(f"        [{c['name']}] {c['type']} NULL" for c in payload_cols)
    with_cols = ",\n".join(f"        [{c['name']}] {c['type']} '$.{c['name']}'" for c in payload_cols)
    names = ", ".join(f"[{c['name']}]" for c in payload_cols)

    ins_cols = ", ".join(f"[{c['name']}]" for c in writable) + f", [{_AUDIT_CREATED}]"
    ins_vals = ", ".join(
        f"ISNULL(p.[{c['name']}], {_active_literal(c)})" if _active_literal(c) else f"p.[{c['name']}]"
        for c in writable
    ) + ", GETDATE()"
    upd_cols = [c for c in writable if c["name"] != "companyId"]
    # Full-replace UPDATE (the platform convention: callers send the whole
    # record), except a NOT NULL column omitted from the payload keeps its
    # current value -- writing NULL there can only fail (found by
    # scripts/step1_sql_probe.py: UPDATE without `active` -> "Cannot insert
    # the value NULL into column 'active'").
    upd_set = ",\n".join(
        f"                t.[{c['name']}] = "
        + (f"p.[{c['name']}]" if c["nullable"] else f"ISNULL(p.[{c['name']}], t.[{c['name']}])")
        for c in upd_cols
    )
    if upd_set:
        upd_set += ",\n"
    upd_set += f"                t.[{_AUDIT_UPDATED}] = GETDATE()"
    join = f"t.[{pk}] = p.[{pk}]"
    if tenant_scoped:
        join += " AND t.[companyId] = p.[companyId]"

    return f"""CREATE OR ALTER PROCEDURE [dbo].[{sp}] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @Outputmessage NVARCHAR(MAX) = '{{
  "result": [
    {{ "value": "", "msg": "", "error": "" }}
  ]
}}';

    DECLARE @action INT;
    SET @action = (
        SELECT TOP 1 TRY_CONVERT(INT, JSON_VALUE(value, '$.action'))
        FROM OPENJSON(@pjsonfile, '$.{plural}')
    );

    DECLARE @payload TABLE (
{decl}
    );

    BEGIN TRY
        INSERT INTO @payload ({names})
        SELECT {names}
        FROM OPENJSON(@pjsonfile, '$.{plural}')
        WITH (
{with_cols}
        );

        BEGIN TRANSACTION;

        IF @action = 1
        BEGIN
            INSERT INTO [dbo].[{table}] ({ins_cols})
            SELECT {ins_vals}
            FROM @payload AS p;

            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].value', CAST(SCOPE_IDENTITY() AS VARCHAR(20)));
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Inserted Successfully');
        END
        ELSE IF @action = 2
        BEGIN
            UPDATE t
            SET
{upd_set}
            FROM [dbo].[{table}] AS t
            INNER JOIN @payload AS p ON {join};

            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Updated Successfully');
        END
        ELSE IF @action = 3
        BEGIN
            DELETE t
            FROM [dbo].[{table}] AS t
            INNER JOIN @payload AS p ON {join};

            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Deleted Successfully');
        END
        ELSE
        BEGIN
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
            SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', 'Invalid action');
            ROLLBACK TRANSACTION;
            GOTO Finish;
        END

        COMMIT TRANSACTION;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
            ROLLBACK TRANSACTION;
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].error', '1');
        SET @Outputmessage = JSON_MODIFY(@Outputmessage, '$.result[0].msg', ERROR_MESSAGE());
    END CATCH

Finish:
    SELECT
        JSON_VALUE(value, '$.value') AS value,
        JSON_VALUE(value, '$.msg')   AS msg,
        JSON_VALUE(value, '$.error') AS error
    FROM OPENJSON(@Outputmessage, '$.result');
END
GO
"""


def _render_sp_all(sp: str, table: str, plural: str, cols: list[dict], pk: str,
                   tenant_scoped: bool, soft_delete_parents: list[dict]) -> str:
    select = ",\n        ".join(_select_expr(c, pk) for c in cols)
    filters = []
    if tenant_scoped:
        filters.append("[companyId] = @companyId")
    col_names = {c["name"].lower(): c for c in cols}
    for sdp in soft_delete_parents:
        fk_col = col_names.get((sdp.get("fk_column") or "").lower())
        parent = sdp.get("fk_table")
        if not fk_col or not parent:
            continue
        parent_pk = fk_col.get("fk_column") or fk_col["name"]
        cond = f"[{fk_col['name']}] IN (SELECT [{parent_pk}] FROM [dbo].[{parent}] WHERE [active] = '1')"
        if fk_col["nullable"]:
            cond = f"([{fk_col['name']}] IS NULL OR {cond})"
        filters.append(cond)
    where = ("\n    WHERE " + "\n      AND ".join(filters)) if filters else ""

    company = ""
    if tenant_scoped:
        company = f"""
    DECLARE @companyId INT;
    SET @companyId = TRY_CONVERT(INT,
        (SELECT TOP 1 JSON_VALUE(value, '$.companyId')
         FROM OPENJSON(@pjsonfile, '$.{plural}'))
    );
"""
    return f"""CREATE OR ALTER PROCEDURE [dbo].[{sp}_all] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
{company}
    SELECT
        {select}
    FROM [dbo].[{table}]{where}
    FOR JSON AUTO, ROOT('{plural}');
END
GO
"""


def _render_sp_one(sp: str, table: str, plural: str, cols: list[dict], pk: str) -> str:
    select = ",\n        ".join(_select_expr(c, pk) for c in cols)
    return f"""CREATE OR ALTER PROCEDURE [dbo].[{sp}_one] (@pjsonfile VARCHAR(MAX))
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @{pk} INT;
    SET @{pk} = TRY_CONVERT(INT,
        (SELECT TOP 1 JSON_VALUE(value, '$.{pk}')
         FROM OPENJSON(@pjsonfile, '$.{plural}'))
    );

    SELECT
        {select}
    FROM [dbo].[{table}]
    WHERE [{pk}] = @{pk}
    FOR JSON AUTO, ROOT('{plural}');
END
GO
"""


def _resolve_indexes(spec: dict, gate: dict, cols: list[dict], pk: str) -> list[tuple[str, ...]]:
    by_lower = {c["name"].lower(): c["name"] for c in cols}
    requested: list[str] = list(spec["db"].get("indexes") or [])
    requested += [r.get("column", "") for r in gate.get("index_recommendations") or []]
    requested += [c["name"] for c in cols if c.get("fk_table") and c.get("fk_column")]
    out: list[tuple[str, ...]] = []
    for entry in requested:
        parts = [p.strip().strip("[]") for p in str(entry).split(",") if p.strip()]
        resolved = tuple(by_lower.get(p.lower()) for p in parts)
        if not resolved or None in resolved or resolved == (pk,):
            continue  # column not in this table (e.g. companyId on a TENANT_INDEPENDENT module)
        if resolved not in out:
            out.append(resolved)
    return out


def _names(spec: dict) -> tuple[str, str, str, str]:
    """(module, plural, table, sp) — plural is always module + 's', the same
    definition agents/reviewer/rules.py uses, so OPENJSON keys and ROOT names
    can't drift from what the reviewer checks."""
    module = spec["module"]
    plural = f"{module}s"
    db = spec.get("db", {})
    table = (db.get("table_name") or "").strip() or plural[0].upper() + plural[1:]
    sp = (db.get("sp_prefix") or "").strip()
    if sp.lower() != f"sp_{plural}".lower():
        sp = f"sp_{plural}"
    return module, plural, table, sp


def _live_sql_type(col: dict) -> str:
    base = str(col.get("type", "")).upper()
    length = col.get("max_length")
    if base in {"NVARCHAR", "VARCHAR", "NCHAR", "CHAR", "VARBINARY", "BINARY"}:
        return f"{base}(MAX)" if length in (-1, None) else f"{base}({length})"
    if base in {"DECIMAL", "NUMERIC"}:
        return f"{base}({col.get('precision') or 10},{col.get('scale') or 0})"
    return base


def reconcile_with_live(spec: dict, gate: dict, live_columns: list[dict]) -> tuple[dict, list[str], Optional[str]]:
    """When the target table already exists, the live table outranks the
    specification (authority order: MCP / live schema first). Returns
    (reconciled spec, spec columns missing from the live table, blocking
    reason or None).

    Found live: across two real runs the architect declared the same
    existing table's PK as catalogItemId (matches live) and then as
    posRewardCatalogItemId (invented) -- every SP of the second run failed
    with "Invalid column name". The PK and column set now come from the live
    table; spec types are kept where the column matches.
    """
    live = {c["name"].lower(): c for c in live_columns}
    for audit in (_AUDIT_CREATED, _AUDIT_UPDATED):
        if audit.lower() not in live:
            return spec, [], f"live table has no {audit} column (existing table predates audit conventions)"
    tenant_scoped = gate.get("tenant_model", "TENANT_SCOPED") != "TENANT_INDEPENDENT"
    if tenant_scoped != ("companyid" in live):
        return spec, [], (
            f"tenant_model {gate.get('tenant_model')} disagrees with live table "
            f"({'has' if 'companyid' in live else 'lacks'} companyId)"
        )
    live_pk = next((c for c in live_columns if c.get("is_identity")), None) or \
        next((c for c in live_columns if c.get("is_pk")), None)
    if not live_pk:
        return spec, [], "live table has no identity/primary key column"

    by_name = {c.get("name", "").lower(): c for c in spec["db"]["columns"]}
    reconciled = []
    for lc in live_columns:
        sc = dict(by_name.get(lc["name"].lower()) or {})
        sql_type = sc.get("sql_type") or _live_sql_type(lc)
        sql_type = re.sub(r"\s*IDENTITY\s*\([^)]*\)", "", sql_type, flags=re.IGNORECASE)
        if lc is live_pk:
            sql_type = "int IDENTITY(1,1) NOT NULL"
        reconciled.append({**sc, "name": lc["name"], "sql_type": sql_type,
                           "nullable": bool(lc.get("nullable", True)) and lc is not live_pk})
    drift = [c.get("name") for c in spec["db"]["columns"]
             if c.get("name") and c["name"].lower() not in live
             and "IDENTITY" not in str(c.get("sql_type", "")).upper()]
    new_spec = {**spec, "db": {**spec["db"], "columns": reconciled}}
    return new_spec, drift, None


def generate_crud_sql(spec_raw, gate_raw, live_columns: Optional[list[dict]] = None) -> Optional[dict]:
    """Renders database_artifacts for a CRUD-shaped module, or returns None
    when the template can't faithfully cover it (caller falls back to the
    LLM). A BLOCKED gate returns the same blocked marker the prompt asks the
    LLM for. `live_columns` (the target table's live columns, when it already
    exists) makes the live table authoritative -- see reconcile_with_live."""
    spec, gate = _safe_load(spec_raw), _safe_load(gate_raw)
    if gate.get("status") == "BLOCKED":
        return {"status": "blocked", "reason": gate.get("reason", ""), "generator": "template"}
    if unsupported_reason(spec, gate):
        return None
    drift: list[str] = list(spec.get("db", {}).get("schema_drift") or [])  # from spec_reconciler
    if live_columns:
        spec, live_drift, blocking = reconcile_with_live(spec, gate, live_columns)
        if blocking:
            return None
        drift += [d for d in live_drift if d not in drift]

    module, plural, table, sp = _names(spec)
    pk = primary_key(spec)
    tenant_scoped = gate.get("tenant_model", "TENANT_SCOPED") != "TENANT_INDEPENDENT"
    cols = _build_columns(spec, gate)
    indexes = _resolve_indexes(spec, gate, cols, pk)

    return {
        "create_table": _render_create_table(table, cols, pk, indexes),
        "sp_upsert": _render_sp_upsert(sp, table, plural, cols, pk, tenant_scoped),
        "sp_all": _render_sp_all(sp, table, plural, cols, pk, tenant_scoped,
                                 gate.get("soft_delete_parents") or []),
        "sp_one": _render_sp_one(sp, table, plural, cols, pk),
        "generator": "template",
        **({"existing_table": True} if live_columns else {}),
        **({"schema_drift": drift} if drift else {}),
    }


def fallback_reason(spec_raw, gate_raw, live_columns: Optional[list[dict]] = None) -> Optional[str]:
    """Why generate_crud_sql returned None (for the stage's metadata)."""
    spec, gate = _safe_load(spec_raw), _safe_load(gate_raw)
    reason = unsupported_reason(spec, gate)
    if reason or not live_columns:
        return reason
    return reconcile_with_live(spec, gate, live_columns)[2]
