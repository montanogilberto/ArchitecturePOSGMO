# Reviewer Agent — deterministic checklist scoring logic.
# No LLM involved. All checks are regex/string operations.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from google.adk.tools.tool_context import ToolContext

from agents.reviewer.raw_sql import find_raw_sql


# ============================================================================
# Data structures
# ============================================================================

@dataclass
class Issue:
    artifact: Literal["database", "backend", "frontend"]
    file: str
    severity: Literal["error", "warning", "auto_error"]
    message: str

    def deduction(self) -> int:
        return 20 if self.severity == "auto_error" else (10 if self.severity == "error" else 0)


def _score(issues: list[Issue], artifact: str) -> int:
    deductions = sum(i.deduction() for i in issues if i.artifact == artifact)
    return max(0, 100 - deductions)


# ============================================================================
# DATABASE checks
# ============================================================================

def _check_database(db: dict, spec: dict, gate: dict) -> list[Issue]:
    issues: list[Issue] = []
    tier   = gate.get("tier", "TIER_1_CATALOG")
    module = spec.get("module", "")
    plural = f"{module}s"

    create = db.get("create_table", "")
    sp_ups = db.get("sp_upsert", "")
    sp_all = db.get("sp_all", "")
    sp_one = db.get("sp_one", "")
    # `.get(key, {})`'s default only fires when the key is ABSENT — an LLM
    # emitting JSON `null` for a key that IS present crashes the chained
    # .get() below with AttributeError (found live: factoryArtifact's
    # setting_patch came back null, not {}, and took down the whole run).
    # `or {}` catches both "missing" and "present but falsy/None".
    execution = db.get("execution") or {}

    def E(msg: str, auto=False):
        issues.append(Issue("database", "create_table/SPs", "auto_error" if auto else "error", msg))

    def W(msg: str):
        issues.append(Issue("database", "create_table/SPs", "warning", msg))

    tenant_independent = gate.get("tenant_model") == "TENANT_INDEPENDENT"

    # ── Existing-table drift ──────────────────────────────────────────────
    # The target table already exists and lacks columns the PRD/spec asked for
    # (agents/database/sql_templates.reconcile_with_live). The SPs are valid
    # against the live table, but those fields can't be stored without a
    # migration -- a human decision, surfaced here rather than hidden.
    drift = db.get("schema_drift") or []
    if drift:
        E(f"Existing live table lacks spec columns {drift} -- needs a migration decision")
    if db.get("live_conflict"):
        E(f"Existing live table conflicts with the gate decision ({db['live_conflict']}) -- needs a human decision")
    if db.get("migration_required"):
        E(f"Existing live table needs a migration: {str(db['migration_required'])[:160]}")

    # ── Execution errors ──────────────────────────────────────────────────
    # Blocking: SQL that doesn't execute on the server can't ship. As a plain
    # error (-10) a single failed batch scored exactly 90 and PASSED review
    # (Step 1 evidence: leadCapture's LLM-written expression index,
    # "Incorrect syntax near '('", database: 90).
    for detail in execution.get("details", []):
        if detail.get("status") in ("error", "connection_error"):
            E(f"SQL execution error: {detail.get('message','')[:120]}", auto=True)

    # ── CREATE TABLE checks ───────────────────────────────────────────────
    if tenant_independent:
        if re.search(r'\bcompanyId\b', create, re.IGNORECASE):
            E(
                "companyId must not appear in CREATE TABLE for TENANT_INDEPENDENT modules",
                auto=True,
            )
    elif not re.search(r'\bcompanyId\b', create, re.IGNORECASE):
        E("companyId column missing from CREATE TABLE", auto=True)

    # The spec's IDENTITY column is the PK when declared (it mirrors a live
    # table that already exists, e.g. posRewardCatalogItems.catalogItemId);
    # {module}Id is the default for new tables. Same rule as
    # agents/database/sql_templates.primary_key.
    pk_name = next(
        (c.get("name") for c in spec.get("db", {}).get("columns", [])
         if "IDENTITY" in str(c.get("sql_type", "")).upper() and c.get("name")),
        f"{module}Id",
    )
    pk_pattern = rf'\b{re.escape(pk_name)}\b.*\bIDENTITY\(1,1\)'
    if not re.search(pk_pattern, create, re.IGNORECASE):
        E(f"Primary key '{pk_name} INT IDENTITY(1,1)' missing or malformed")

    if not re.search(r'\bcreated_At\b', create):
        E("created_At column missing (must be exactly 'created_At' — capital A)")
    elif re.search(r'\bcreated_at\b', create):
        E("Audit field casing error: found 'created_at' — must be 'created_At' (capital A)", auto=True)

    if not re.search(r'\bupdated_at\b', create, re.IGNORECASE):
        E("updated_at column missing from CREATE TABLE")

    # Forbidden audit name variants
    for bad in ("createdAt", "updatedAt", "updated_At"):
        if re.search(rf'\b{bad}\b', create):
            E(f"Forbidden audit field name '{bad}' — use created_At / updated_at", auto=True)

    # DATETIME2 rule
    if tier == "TIER_4_IOT":
        if not re.search(r'\bDATETIME2\b', create, re.IGNORECASE):
            E("TIER_4_IOT requires DATETIME2(3) for timestamp columns")
    else:
        if re.search(r'\bDATETIME2\b', create, re.IGNORECASE):
            E(f"DATETIME2 found in {tier} module — only TIER_4_IOT uses DATETIME2", auto=True)

    # TIER_2 monetary DECIMAL columns must be DECIMAL(10,2)
    if tier == "TIER_2_FINANCIAL":
        monetary_cols = re.findall(
            r'(\b(?:amount|total|price|cost|expense|income|payment|fee|balance|subtotal|discount)\w*)\b'
            r'[^,\n]*?DECIMAL\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)',
            create, re.IGNORECASE
        )
        for col_name, prec, scale in monetary_cols:
            if int(scale) != 2:
                E(f"Monetary column '{col_name}' is DECIMAL({prec},{scale}) — must be DECIMAL(10,2)", auto=True)

    # ── SP naming ─────────────────────────────────────────────────────────
    for sp_body, sp_label in [(sp_ups, "sp_upsert"), (sp_all, "sp_all"), (sp_one, "sp_one")]:
        if re.search(rf'\bsp_{re.escape(module)}\b(?!s)', sp_body, re.IGNORECASE):
            E(f"SP uses singular name 'sp_{module}' — must be plural 'sp_{plural}'", auto=True)

    # ── SP parameter type ─────────────────────────────────────────────────
    for sp_body, label in [(sp_ups, "sp_upsert"), (sp_all, "sp_all"), (sp_one, "sp_one")]:
        if re.search(r'@pjsonfile\s+NVARCHAR', sp_body, re.IGNORECASE):
            E(f"{label}: @pjsonfile must be VARCHAR(MAX), not NVARCHAR")

    # ── sp_all: companyId filter ──────────────────────────────────────────
    if not re.search(r'@pjsonfile', sp_all, re.IGNORECASE):
        E("sp_all missing @pjsonfile parameter (multi-tenancy broken)", auto=True)
    if tenant_independent:
        if re.search(r'WHERE\s+\[?companyId\]?\s*=\s*@companyId', sp_all, re.IGNORECASE):
            E(
                "sp_all must not filter by companyId for TENANT_INDEPENDENT modules",
                auto=True,
            )
    elif not re.search(r'WHERE\s+\[?companyId\]?\s*=\s*@companyId', sp_all, re.IGNORECASE):
        E("sp_all missing WHERE companyId = @companyId filter (cross-company data leak)", auto=True)

    # ── OPENJSON key must be plural ───────────────────────────────────────
    # A TENANT_INDEPENDENT sp_all legitimately reads nothing from @pjsonfile
    # (no companyId to extract), so it has no OPENJSON at all -- checking it
    # anyway produced Milestone 7's "sp_all: OPENJSON key must be plural"
    # finding on a correct sp_all. sp_all is only checked when it does parse.
    for sp_body, label in [(sp_ups, "sp_upsert"), (sp_all, "sp_all"), (sp_one, "sp_one")]:
        if label == "sp_all" and not re.search(r'\bOPENJSON\b', sp_body, re.IGNORECASE):
            continue
        if sp_body and not re.search(rf"OPENJSON.*'\$\.{re.escape(plural)}'", sp_body, re.IGNORECASE):
            E(f"{label}: OPENJSON key must be '$.{plural}' (plural), not singular")

    # ── @payload TABLE variable ───────────────────────────────────────────
    if not re.search(r'DECLARE\s+@payload\s+TABLE', sp_ups, re.IGNORECASE):
        E("sp_upsert: @payload TABLE variable missing")

    # ── TRY_CONVERT for action ────────────────────────────────────────────
    if not re.search(r'TRY_CONVERT\s*\(\s*INT', sp_ups, re.IGNORECASE):
        E("sp_upsert: action must be parsed with TRY_CONVERT(INT, ...)")

    # ── BEGIN TRY / TRANSACTION / COMMIT / ROLLBACK ───────────────────────
    for kw in ("BEGIN TRY", "BEGIN TRANSACTION", "COMMIT", "ROLLBACK"):
        if not re.search(rf'\b{kw}\b', sp_ups, re.IGNORECASE):
            E(f"sp_upsert: '{kw}' missing — mutations must be transactional")

    # ── GOTO Finish ───────────────────────────────────────────────────────
    if not re.search(r'\bFinish\s*:', sp_ups, re.IGNORECASE):
        E("sp_upsert: GOTO Finish label missing")

    # ── @Outputmessage pattern ────────────────────────────────────────────
    if not re.search(r'@Outputmessage', sp_ups, re.IGNORECASE):
        E("sp_upsert: @Outputmessage response pattern missing")

    # ── FOR JSON AUTO (not PATH) ──────────────────────────────────────────
    for sp_body, label in [(sp_all, "sp_all"), (sp_one, "sp_one")]:
        if re.search(r'FOR\s+JSON\s+PATH', sp_body, re.IGNORECASE):
            E(f"{label}: must use FOR JSON AUTO, not FOR JSON PATH")
        if not re.search(rf"ROOT\s*\(\s*['\"]?{re.escape(plural)}['\"]?\s*\)", sp_body, re.IGNORECASE):
            E(f"{label}: ROOT('{plural}') missing or uses wrong name")

    # ── ISNULL on updated_at in sp_one ────────────────────────────────────
    if not re.search(r"ISNULL\s*\(\s*CONVERT\s*\(\s*VARCHAR", sp_one, re.IGNORECASE):
        E("sp_one: updated_at must use ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '')")

    # ── soft_delete_parents ───────────────────────────────────────────────
    for sdp in gate.get("soft_delete_parents") or []:
        fk_table = sdp.get("fk_table", "")
        if fk_table and not re.search(rf"{re.escape(fk_table)}.*active.*=.*'1'", sp_all, re.IGNORECASE):
            E(f"sp_all: missing active='1' filter for soft-delete parent '{fk_table}'")

    return issues


# ============================================================================
# BACKEND checks
# ============================================================================

def _check_backend(be: dict, spec: dict, gate: dict) -> list[Issue]:
    issues: list[Issue] = []
    module  = spec.get("module", "")
    plural  = f"{module}s"
    pattern = gate.get("backend_pattern", "CRUD_ONLY")
    connectors = gate.get("connector_endpoints") or []

    module_file = be.get("module_file") or {}
    route_file  = be.get("route_file") or {}
    mod_path    = module_file.get("path", "")
    mod_content = module_file.get("content", "")
    rt_path     = route_file.get("path", "")
    rt_content  = route_file.get("content", "")
    docs        = be.get("docs_files") or []

    def E(file: str, msg: str, auto=False):
        issues.append(Issue("backend", file, "auto_error" if auto else "error", msg))

    def W(file: str, msg: str):
        issues.append(Issue("backend", file, "warning", msg))

    # ── File paths ────────────────────────────────────────────────────────
    expected_mod = f"modules/{plural}.py"
    if mod_path != expected_mod:
        E("module_file", f"module_file path must be '{expected_mod}', got '{mod_path}'", auto=True)

    expected_rt = f"routes_/{module}.py"
    if rt_path != expected_rt:
        E("route_file", f"route_file path must be '{expected_rt}', got '{rt_path}'", auto=True)

    # ── Required imports ──────────────────────────────────────────────────
    if "from fastapi.responses import JSONResponse" not in mod_content:
        E(mod_path, "Missing: from fastapi.responses import JSONResponse", auto=True)
    if "from databases import connection" not in mod_content:
        E(mod_path, "Missing: from databases import connection", auto=True)

    # ── Forbidden imports ─────────────────────────────────────────────────
    for forbidden in ("APIRouter", "BaseModel", "HTTPException", "from pydantic"):
        if forbidden in mod_content:
            E(mod_path, f"Forbidden import '{forbidden}' in module_file", auto=True)

    # -- Connection pattern: per-request (module-level conn is FORBIDDEN) ----------
    # Module-level conn = connection() causes 500 after DB idle timeout.
    if re.search(r"^conn\s*=\s*connection\(\)", mod_content, re.MULTILINE):
        E(mod_path, "Module-level conn = connection() is forbidden -- must be inside each function", auto=True)
    if not re.search(r"conn\s*=\s*connection\(\)", mod_content):
        E(mod_path, "Missing per-request conn = connection() inside CRUD functions")
    if not re.search(r"finally", mod_content):
        E(mod_path, "DB connection must be closed in finally block: if conn: conn.close()")

    # ── Three CRUD functions ──────────────────────────────────────────────
    for fn in (f"{plural}_sp", f"all_{plural}_sp", f"one_{plural}_sp"):
        if not re.search(rf'\bdef {re.escape(fn)}\b', mod_content):
            E(mod_path, f"Missing function: {fn}()", auto=True)

    # ── all_sp must accept json_file: dict ───────────────────────────────────
    if re.search(rf'\bdef all_{re.escape(plural)}_sp\s*\(\s*\)', mod_content):
        E(mod_path, f"all_{plural}_sp() must accept json_file: dict (zero-arg is forbidden)", auto=True)

    # ── No raw SQL ────────────────────────────────────────────────────────
    # AST-based (agents/reviewer/raw_sql.py): any cursor name, SQL held in a
    # variable, f-strings. The old `cursor\.execute\(["'](?!EXEC)` regex
    # missed `cur.execute(...)` -- 16 of 23 real backend violations.
    for hit in find_raw_sql(mod_content):
        E(mod_path, f"Raw SQL detected ({hit}) — only EXEC [dbo].[sp_*] calls allowed")

    # -- SP return pattern: fetchone for upsert, fetchall+join for all/one --------
    if re.search(r"json_result\[0\]\[0\]", mod_content):
        E(mod_path, "json_result[0][0] is the old broken pattern -- use fetchone()+row[0] for upsert", auto=True)
    if not re.search(r"cursor\.fetchone\(\)", mod_content):
        E(mod_path, f"{plural}_sp (upsert) must use cursor.fetchone() for the single SP result row")
    if not re.search(r"cursor\.fetchall\(\)", mod_content):
        E(mod_path, f"all_{plural}_sp / one_{plural}_sp must use cursor.fetchall() for multi-row JSON")
    if not re.search(r"if not json_result", mod_content):
        E(mod_path, "Missing empty resultset guard (if not json_result) -- prevents json.loads crash")
    # ── No round() ────────────────────────────────────────────────────────
    if re.search(r'\bround\s*\(', mod_content):
        E(mod_path, "round() call found — return raw values, no rounding", auto=True)

    # ── Route file: import from plural module ─────────────────────────────
    if not re.search(rf'from modules\.{re.escape(plural)}\s+import', rt_content):
        E(rt_path, f"route_file must import from 'modules.{plural}' (plural)", auto=True)

    # ── APIRouter with no prefix/tags ─────────────────────────────────────
    if not re.search(r'router\s*=\s*APIRouter\s*\(\s*\)', rt_content):
        E(rt_path, "router = APIRouter() must have NO prefix and NO tags")

    # ── 3 CRUD endpoints — all POST ───────────────────────────────────────
    for path, method in [
        (f"/{plural}", "post"),
        (f"/all_{plural}", "post"),
        (f"/one_{plural}", "post"),
    ]:
        pat = rf'@router\.{method}\s*\(\s*["\']/?{re.escape(path.lstrip("/"))}'
        if not re.search(pat, rt_content, re.IGNORECASE):
            E(rt_path, f"Missing endpoint: {method.upper()} {path}", auto=True)

    # ── No Pydantic/HTTPException/async in routes_ ────────────────────────
    for forbidden in ("HTTPException", "BaseModel", "response_model"):
        if forbidden in rt_content:
            E(rt_path, f"Forbidden in route_file: '{forbidden}'")

    # ── docs_files ────────────────────────────────────────────────────────
    if len(docs) < 3:
        E("docs_description/", f"Expected 3 docs txt files, found {len(docs)}")

    # ── CRUD_AND_CONNECTOR: verify connector functions + routes ───────────
    if pattern == "CRUD_AND_CONNECTOR":
        # A connector that delegates its external call to an already-instrumented
        # modules/*.py helper (send_azure_push, Twilio senders, etc. -- the
        # established pattern, e.g. notificationDispatch.py) has no reason to
        # import httpx/os.getenv itself; those concerns live in the helper it
        # calls. Only a connector making its own raw outbound call (biometric
        # verify, MercadoLibre/eBay OAuth, ...) needs httpx.AsyncClient +
        # os.getenv directly. Checked once per module, not once per endpoint --
        # looping this inside `for ep in connectors` duplicated the same
        # module-wide finding once per connector (confirmed live: transactionNotification's
        # two endpoints produced the same two "must use..." errors twice each).
        delegates_to_internal_module = bool(re.search(r'^from modules\.\w+ import', mod_content, re.MULTILINE))
        if not delegates_to_internal_module:
            if "os.getenv" not in mod_content:
                E(mod_path, "Connector must use os.getenv() for secrets — hardcoded credentials forbidden")
            if "httpx.AsyncClient" not in mod_content:
                E(mod_path, "Connector must use httpx.AsyncClient for HTTP calls")

        for ep in connectors:
            path = ep.get("path", "")
            # Check async function exists in module_file
            fn_hint = path.strip("/").replace("/", "_").replace("-", "_")
            if not re.search(r'\basync\s+def\s+\w+_connector\b', mod_content):
                E(mod_path, f"Missing async connector function for '{path}'", auto=True)
            # Check route exists
            # Check route exists -- PRD uses hyphens, generated code uses camelCase.
            # Normalize both by removing all separators before comparing.
            norm_prd = path.lstrip('/').lower().replace('-', '').replace('_', '')
            route_defs = re.findall(r"@router\.(post|get)\s*\(\s*['\"]([^'\"]+)", rt_content, re.IGNORECASE)
            found_route = any(
                h[1].lstrip('/').lower().replace('-', '').replace('_', '') == norm_prd
                for h in route_defs
            )
            if not found_route:
                E(rt_path, f"Missing connector route for {path!r} (or camelCase equivalent)", auto=True)
    return issues


# ============================================================================
# FRONTEND checks
# ============================================================================

def _check_frontend(fe: dict, spec: dict, gate: dict) -> list[Issue]:
    """Frontend checks. With an MVVM spec (specification.frontend.view_file set —
    always true in the pipeline, the spec reconciler enforces it) each check runs
    on the file that should hold the code: JSX checks on the View, state/auth
    checks on the Logic hook, plus structural checks on shell/View/Logic and
    their paths (frontend_layout.py). A spec without view_file (older runs)
    keeps the original single-page behaviour."""
    from frontend_layout import FEATURE_TO_SRC, layout, resolve_area

    issues: list[Issue] = []
    module    = spec.get("module", "")
    Module    = module[0].upper() + module[1:] if module else ""
    fspec     = spec.get("frontend") or {}
    ui_pattern = (spec.get("prd_hints") or {}).get("frontend_ui_pattern", "")
    mvvm      = bool(fspec.get("view_file"))

    def content(key: str) -> str:
        return (fe.get(key) or {}).get("content", "") or ""

    page_content = content("page_file")
    api_content  = content("api_file")
    css_content  = content("css_file")
    view_content = content("view_file")
    logic_content = content("logic_file")

    if mvvm:
        paths = layout(module, resolve_area(module, fspec.get("area")))
        page_file, api_file = paths["page_file"], paths["api_file"]
        view_file, logic_file, css_file = paths["view_file"], paths["logic_file"], paths["css_file"]
        jsx, jsx_file = view_content, view_file          # where JSX must live
        state, state_file = logic_content, logic_file    # where state/effects must live
        ui = view_content + "\n" + logic_content
    else:
        page_file, api_file = f"src/pages/{Module}Page.tsx", f"src/api/{module}Api.ts"
        css_file = f"src/pages/{Module}Page.css"
        jsx = state = ui = page_content
        jsx_file = state_file = page_file

    def E(file: str, msg: str, auto=False):
        issues.append(Issue("frontend", file, "auto_error" if auto else "error", msg))
    def W(file: str, msg: str):
        issues.append(Issue("frontend", file, "warning", msg))

    # ── MVVM structure + paths ────────────────────────────────────────────
    if mvvm:
        for key in ("api_file", "page_file", "view_file", "logic_file", "css_file"):
            got = (fe.get(key) or {}).get("path")
            if got and got != paths[key]:
                E(paths[key], f"{key} path must be {paths[key]} (got {got})", auto=True)
        for key, fname in (("view_file", view_file), ("logic_file", logic_file)):
            if not content(key).strip():
                E(fname, f"{key} missing — MVVM requires {fname}", auto=True)
        if not re.search(rf"import\s+{Module}View\s+from\s+'\./{Module}/{Module}View'", page_content):
            E(page_file, f"Router shell must import {Module}View from './{Module}/{Module}View'", auto=True)
        if f"import './{Module}/{Module}.css'" not in page_content:
            E(page_file, f"Router shell must import './{Module}/{Module}.css'", auto=True)
        if re.search(r"\buse(State|Effect)\s*\(|\bfetch\s*\(", page_content):
            E(page_file, "Router shell must only render the View — move state/effects/fetch to the Logic hook", auto=True)
        if view_content and not re.search(rf"\buse{Module}\s*\(\s*\)", view_content):
            E(view_file, f"View must get its data from `const vm = use{Module}()`", auto=True)
        if re.search(r"\buse(State|Effect)\s*\(", view_content):
            E(view_file, "View is presentation only — move useState/useEffect into the Logic hook")
        if logic_content and not re.search(rf"export\s+(const|function)\s+use{Module}\b", logic_content):
            E(logic_file, f"Logic must export the hook use{Module}", auto=True)
        if logic_content and not re.search(
                rf"export\s+type\s+{Module}VM\s*=\s*ReturnType<\s*typeof\s+use{Module}\s*>", logic_content):
            E(logic_file, f"Logic must export `type {Module}VM = ReturnType<typeof use{Module}>`")
        if logic_content and fspec.get("has_list_view", True) and "useIonViewWillEnter" not in logic_content:
            E(logic_file, "Data freshness: reload in useIonViewWillEnter (Ionic keeps pages mounted)")
        for c, fname in ((view_content, view_file), (logic_content, logic_file)):
            if re.search(r"\bfetch\s*\(", c):
                E(fname, f"fetch() outside the api file — all HTTP goes through {api_file}", auto=True)

    # ── Auth hook — MUST use useUser, never AuthContext ──────────────────
    if "AuthContext" in ui:
        E(state_file,
          f"AuthContext import found — FORBIDDEN. Use `import {{ useUser }} from '{FEATURE_TO_SRC if mvvm else '../'}contexts/UserContext'` instead",
          auto=True)
    if re.search(r"useContext\s*\(\s*AuthContext\s*\)", ui):
        E(state_file,
          "useContext(AuthContext) forbidden — use `const { companyId } = useUser()` instead",
          auto=True)
    if "companyId = user?.companyId" in ui:
        E(state_file,
          "user?.companyId access pattern forbidden — useUser() exposes companyId directly",
          auto=True)

    # ── Header component (most common failure) ────────────────────────────
    # Current location is components/layout/Header; the legacy components/Header
    # path is still accepted so older single-page specs keep passing.
    if not re.search(r"import\s+Header\s+from\s+'(?:\.\./)+components/(?:layout/)?Header'", jsx):
        expected = (f"import Header from '{FEATURE_TO_SRC}components/layout/Header'" if mvvm
                    else "import Header from '../components/Header'")
        E(jsx_file, f"Missing: {expected}", auto=True)
    # IonHeader is forbidden at page level but IS allowed inside IonModal blocks.
    # Strip all IonModal content before checking so modals don't trigger false positives.
    _jsx_no_modals = re.sub(r'<IonModal[\s\S]*?</IonModal>', '', jsx)
    if re.search(r'<IonHeader\b', _jsx_no_modals):
        E(jsx_file, "Direct IonHeader usage forbidden — use custom <Header> component", auto=True)
    if "usePopovers" not in jsx and not ("<AlertPopover" in jsx and "<MailPopover" in jsx):
        E(jsx_file, "Header popovers not wired — use `const pops = usePopovers()` and `{...pops.headerProps}`")

    # ── catch (err: any) ─────────────────────────────────────────────────
    files = [(page_content, page_file), (api_content, api_file)]
    if mvvm:
        files += [(view_content, view_file), (logic_content, logic_file)]
    for c, fname in files:
        if re.search(r'\bcatch\s*\(\s*\w+\s*:\s*any\s*\)', c):
            E(fname, "catch (err: any) forbidden — use catch (err) with (err as Error).message", auto=True)

    # ── CustomEvent<any> and bare CustomEvent ─────────────────────────────
    # The bare-CustomEvent check must only look at TYPE-ANNOTATION usage
    # (e.g. `e: CustomEvent` or `e: CustomEvent<Foo>`), not the import line
    # -- `import { ..., CustomEvent } from 'react'` is the established,
    # correct convention (agents/frontend/prompt.py's own examples import
    # CustomEvent bare, then use it WITH a generic at each call site).
    # `\bCustomEvent\b(?!\s*<)` matched that import occurrence first (never
    # followed by `<`, since imports don't carry generic parameters) and
    # re.search only needs one match -- so a page with every single usage
    # correctly typed still failed review on the import line alone.
    # Confirmed live: factoryRunUsage's real generated page had 4
    # occurrences, all 3 real usages correctly typed
    # (CustomEvent<void>/<InputInputEventDetail>/<DatetimeChangeEventDetail>),
    # and it still failed on this check every iteration.
    for c, fname in ([(view_content, view_file), (logic_content, logic_file)] if mvvm
                     else [(page_content, page_file)]):
        if re.search(r'CustomEvent<any>', c):
            E(fname, "CustomEvent<any> forbidden — use specific generic (CheckboxChangeEventDetail, etc.)", auto=True)
        if re.search(r':\s*CustomEvent\b(?!\s*<)', c):
            E(fname, "Bare CustomEvent without generic forbidden — add specific type parameter", auto=True)

    # ── JSON.parse double-parse ───────────────────────────────────────────
    if re.search(r'JSON\.parse\s*\(\s*await\s+\w+\.json\s*\(\s*\)', api_content):
        E(api_file, "JSON.parse(await res.json()) is a double-parse error — use await res.json() only", auto=True)

    # ── fetch() only, no axios ────────────────────────────────────────────
    if "axios" in api_content:
        E(api_file, "axios import found — use plain fetch() only", auto=True)
    if "import.meta.env.VITE_API_URL" not in api_content:
        E(api_file, "BASE_URL must use import.meta.env.VITE_API_URL ?? '...'")

    # ── TypeScript interfaces exported ────────────────────────────────────
    if not re.search(r'^export\s+interface\s+\w', api_content, re.MULTILINE):
        E(api_file, "No exported TypeScript interfaces found in api file")

    # ── IonLoading + IonToast ─────────────────────────────────────────────
    if "IonLoading" not in jsx:
        E(jsx_file, "IonLoading missing — required for loading state")
    if "IonToast" not in jsx:
        E(jsx_file, "IonToast missing — required for error display")

    # ── IonInfiniteScroll when has_list_view and NOT wizard ──────────────
    if fspec.get("has_list_view", True):
        if ui_pattern != "Wizard Flow Layout" and "IonInfiniteScroll" not in jsx:
            E(jsx_file, "IonInfiniteScroll missing — required when has_list_view is true", auto=True)

    # ── UTC-7 toHermosillo helper ─────────────────────────────────────────
    if not re.search(r'toHermosillo|mxDate|7 \* 60 \* 60 \* 1000', ui):
        E(jsx_file, "UTC-7 date conversion (toHermosillo / mxDate from utils/format) missing — all dates must be converted")

    # ── IVA never computed ────────────────────────────────────────────────
    if re.search(r'\b(iva|tax|impuesto)\s*[=*+]', ui, re.IGNORECASE):
        E(state_file, "IVA/tax computation found in frontend — IVA is always 0, never compute it")

    # ── CSS scoped class names ────────────────────────────────────────────
    module_dashed = re.sub(r'([A-Z])', r'-\1', module).lstrip('-').lower()
    if css_content and not re.search(rf'\.{module_dashed}', css_content, re.IGNORECASE):
        # Also accept camelCase prefix
        if not re.search(rf'\.{module}', css_content, re.IGNORECASE):
            W(css_file, f"CSS class names should use '{module_dashed}-' prefix")

    # ── app_patches present ───────────────────────────────────────────────
    patches = fe.get("app_patches") or {}
    for key in ("import_line", "private_route", "menu_item"):
        if not patches.get(key):
            E(page_file, f"app_patches.{key} missing")
    if mvvm and patches.get("import_line") and f"./pages/{paths['area']}/{Module}Page" not in patches["import_line"]:
        E(page_file, f"app_patches.import_line must be: {paths['app_import_line']}", auto=True)

    # ── setting_patch present ─────────────────────────────────────────────
    setting = fe.get("setting_patch") or {}
    if not setting.get("section") or not setting.get("code"):
        E(page_file, "setting_patch missing section or code")

    # ── TIER_2: 2-decimal monetary display ────────────────────────────────
    if gate.get("tier") == "TIER_2_FINANCIAL":
        if not re.search(r'\.toFixed\s*\(\s*2\s*\)|\bfmtMXN\b|\bfmtNum\b', ui):
            E(jsx_file, "TIER_2_FINANCIAL: monetary amounts must display 2 decimals (fmtMXN / fmtNum or .toFixed(2))")

    # ── Wizard layout: IonList/IonInfiniteScroll forbidden ────────────────
    if ui_pattern == "Wizard Flow Layout":
        if "IonList" in jsx:
            E(jsx_file, "Wizard Flow Layout must not use IonList — use IonCard per step only", auto=True)
        if "IonInfiniteScroll" in jsx:
            E(jsx_file, "Wizard Flow Layout must not use IonInfiniteScroll", auto=True)

    return issues


# ============================================================================
# Main tool
# ============================================================================

def run_review(tool_context: ToolContext) -> dict:
    """
    Deterministic reviewer. Reads all artifacts from session state,
    runs Python checklist for each, scores 0-100, writes review_result.
    """
    def _load(key: str) -> dict:
        raw = tool_context.state.get(key, "")
        if not isinstance(raw, str):
            return raw if isinstance(raw, dict) else {}
        raw = raw.strip()
        if not raw:
            return {}
        if raw.startswith("```"):
            lines = [l for l in raw.splitlines() if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    gate     = _load("gate_result")
    spec     = _load("specification")
    db       = _load("database_artifacts")
    be       = _load("backend_artifacts")
    fe       = _load("frontend_artifacts")

    # Artifact-presence invariant (added after Experiment 4 caught this):
    # a missing/empty artifact must never silently score 100 by having its
    # checks skipped. "No artifact" is not "no issues" -- it means the
    # corresponding construction agent never ran, and the review has nothing
    # to say about a layer it never actually looked at. Score None (not 90+,
    # not 0) so it can never accidentally satisfy `passed`, and say so
    # explicitly in `issues` so it's visible without reading raw state.
    presence = {"database": bool(db), "backend": bool(be), "frontend": bool(fe)}

    all_issues: list[Issue] = []
    for artifact_name, present in presence.items():
        if not present:
            all_issues.append(Issue(
                artifact_name, "(missing)", "auto_error",
                f"{artifact_name}_artifacts is missing or empty -- the construction agent for this "
                f"layer never produced output. This layer was NOT reviewed, not reviewed-and-passed.",
            ))

    if db:
        all_issues.extend(_check_database(db, spec, gate))
    if be:
        all_issues.extend(_check_backend(be, spec, gate))
    if fe:
        all_issues.extend(_check_frontend(fe, spec, gate))

    def _score_or_none(name: str) -> Optional[int]:
        if not presence[name]:
            return None
        return _score(all_issues, name)

    db_score = _score_or_none("database")
    be_score = _score_or_none("backend")
    fe_score = _score_or_none("frontend")
    scores = {"database": db_score, "backend": be_score, "frontend": fe_score}
    passed = all(s is not None and s >= 90 for s in scores.values())

    missing = [name for name, present in presence.items() if not present]

    def _fmt(s: Optional[int]) -> str:
        return "N/A (missing)" if s is None else str(s)

    result = {
        "scores":  scores,
        "passed":  passed,
        "missing_artifacts": missing,
        "issues":  [
            {
                "artifact": i.artifact,
                "file":     i.file,
                "severity": "error" if i.severity in ("error", "auto_error") else "warning",
                "message":  i.message,
            }
            for i in all_issues
        ],
        "summary": (
            f"{'PASSED' if passed else 'FAILED'} — "
            f"database: {_fmt(db_score)}, backend: {_fmt(be_score)}, frontend: {_fmt(fe_score)}. "
            f"{len([i for i in all_issues if i.severity != 'warning'])} error(s) found."
            + (f" MISSING ARTIFACTS: {', '.join(missing)}." if missing else "")
        ),
    }

    tool_context.state["review_result"] = json.dumps(result)
    return result


# ============================================================================
# Thin Agent wrapper
# ============================================================================
