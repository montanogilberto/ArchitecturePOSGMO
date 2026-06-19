# Reviewer Agent — deterministic checklist scoring logic.
# No LLM involved. All checks are regex/string operations.

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from google.adk.tools.tool_context import ToolContext


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
    execution = db.get("execution", {})

    def E(msg: str, auto=False):
        issues.append(Issue("database", "create_table/SPs", "auto_error" if auto else "error", msg))

    def W(msg: str):
        issues.append(Issue("database", "create_table/SPs", "warning", msg))

    # ── Execution errors ──────────────────────────────────────────────────
    for detail in execution.get("details", []):
        if detail.get("status") == "error":
            E(f"SQL execution error: {detail.get('message','')[:120]}")

    # ── CREATE TABLE checks ───────────────────────────────────────────────
    if not re.search(r'\bcompanyId\b', create, re.IGNORECASE):
        E("companyId column missing from CREATE TABLE", auto=True)

    pk_pattern = rf'\b{module}Id\b.*\bIDENTITY\(1,1\)'
    if not re.search(pk_pattern, create, re.IGNORECASE):
        E(f"Primary key '{module}Id INT IDENTITY(1,1)' missing or malformed")

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
    if not re.search(r'WHERE\s+\[?companyId\]?\s*=\s*@companyId', sp_all, re.IGNORECASE):
        E("sp_all missing WHERE companyId = @companyId filter (cross-company data leak)", auto=True)

    # ── OPENJSON key must be plural ───────────────────────────────────────
    for sp_body, label in [(sp_ups, "sp_upsert"), (sp_all, "sp_all"), (sp_one, "sp_one")]:
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
    for sdp in gate.get("soft_delete_parents", []):
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
    connectors = gate.get("connector_endpoints", [])

    mod_path    = be.get("module_file", {}).get("path", "")
    mod_content = be.get("module_file", {}).get("content", "")
    rt_path     = be.get("route_file", {}).get("path", "")
    rt_content  = be.get("route_file", {}).get("content", "")
    docs        = be.get("docs_files", [])

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
    if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b(?!.*EXEC)', mod_content, re.IGNORECASE):
        # Only flag if it's not inside a comment or string that starts with EXEC
        raw_sql = re.findall(r'cursor\.execute\s*\(\s*["\'](?!EXEC)', mod_content)
        if raw_sql:
            E(mod_path, "Raw SQL detected — only EXEC [dbo].[sp_*] calls allowed")

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
        for ep in connectors:
            path = ep.get("path", "")
            # Check async function exists in module_file
            fn_hint = path.strip("/").replace("/", "_").replace("-", "_")
            if not re.search(r'\basync\s+def\s+\w+_connector\b', mod_content):
                E(mod_path, f"Missing async connector function for '{path}'", auto=True)
            # Check os.getenv usage
            if "os.getenv" not in mod_content:
                E(mod_path, "Connector must use os.getenv() for secrets — hardcoded credentials forbidden")
            # Check httpx.AsyncClient
            if "httpx.AsyncClient" not in mod_content:
                E(mod_path, "Connector must use httpx.AsyncClient for HTTP calls")
            # Check route exists
            # Check route exists -- PRD uses hyphens, generated code uses camelCase.
            # Normalize both by removing all separators before comparing.
            norm_prd = path.lstrip('/').lower().replace('-', '').replace('_', '')
            route_defs = re.findall(r"@router\.(post|get)\s*\(\s*['\"]([^'\"]+)", rt_content, re.IGNORECASE)
            found_route = any(
                h[1].lower().replace('-', '').replace('_', '') == norm_prd
                for h in route_defs
            )
            if not found_route:
                E(rt_path, f"Missing connector route for {path!r} (or camelCase equivalent)", auto=True)
    return issues


# ============================================================================
# FRONTEND checks
# ============================================================================

def _check_frontend(fe: dict, spec: dict, gate: dict) -> list[Issue]:
    issues: list[Issue] = []
    module    = spec.get("module", "")
    Module    = module[0].upper() + module[1:] if module else ""
    has_list  = spec.get("frontend", {}).get("has_list_view", True)
    ui_pattern = spec.get("prd_hints", {}).get("frontend_ui_pattern", "")

    page_content = fe.get("page_file", {}).get("content", "")
    api_content  = fe.get("api_file",  {}).get("content", "")
    css_content  = fe.get("css_file",  {}).get("content", "")

    def E(file: str, msg: str, auto=False):
        issues.append(Issue("frontend", file, "auto_error" if auto else "error", msg))
    def W(file: str, msg: str):
        issues.append(Issue("frontend", file, "warning", msg))

    page_file = f"src/pages/{Module}Page.tsx"
    api_file  = f"src/api/{module}Api.ts"

    # ── Auth hook — MUST use useUser, never AuthContext ──────────────────
    if "AuthContext" in page_content:
        E(page_file,
          "AuthContext import found — FORBIDDEN. Use `import { useUser } from '../components/UserContext'` instead",
          auto=True)
    if re.search(r"useContext\s*\(\s*AuthContext\s*\)", page_content):
        E(page_file,
          "useContext(AuthContext) forbidden — use `const { companyId } = useUser()` instead",
          auto=True)
    if "companyId = user?.companyId" in page_content:
        E(page_file,
          "user?.companyId access pattern forbidden — useUser() exposes companyId directly",
          auto=True)

    # ── Header component (most common failure) ────────────────────────────
    if "import Header from '../components/Header'" not in page_content:
        E(page_file, "Missing: import Header from '../components/Header'", auto=True)
    # IonHeader is forbidden at page level but IS allowed inside IonModal blocks.
    # Strip all IonModal content before checking so modals don't trigger false positives.
    _page_no_modals = re.sub(r'<IonModal[\s\S]*?</IonModal>', '', page_content)
    if re.search(r'<IonHeader\b', _page_no_modals):
        E(page_file, "Direct IonHeader usage forbidden — use custom <Header> component", auto=True)
    if "<AlertPopover" not in page_content:
        E(page_file, "Missing AlertPopover component alongside Header")
    if "<MailPopover" not in page_content:
        E(page_file, "Missing MailPopover component alongside Header")

    # ── catch (err: any) ─────────────────────────────────────────────────
    for content, fname in [(page_content, page_file), (api_content, api_file)]:
        if re.search(r'\bcatch\s*\(\s*\w+\s*:\s*any\s*\)', content):
            E(fname, "catch (err: any) forbidden — use catch (err) with (err as Error).message", auto=True)

    # ── CustomEvent<any> and bare CustomEvent ─────────────────────────────
    if re.search(r'CustomEvent<any>', page_content):
        E(page_file, "CustomEvent<any> forbidden — use specific generic (CheckboxChangeEventDetail, etc.)", auto=True)
    if re.search(r'\bCustomEvent\b(?!\s*<)', page_content):
        E(page_file, "Bare CustomEvent without generic forbidden — add specific type parameter", auto=True)

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
    if "IonLoading" not in page_content:
        E(page_file, "IonLoading missing — required for loading state")
    if "IonToast" not in page_content:
        E(page_file, "IonToast missing — required for error display")

    # ── IonInfiniteScroll when has_list_view and NOT wizard ──────────────
    if has_list_view := spec.get("frontend", {}).get("has_list_view", True):
        if ui_pattern != "Wizard Flow Layout" and "IonInfiniteScroll" not in page_content:
            E(page_file, "IonInfiniteScroll missing — required when has_list_view is true", auto=True)

    # ── UTC-7 toHermosillo helper ─────────────────────────────────────────
    if not re.search(r'toHermosillo|7 \* 60 \* 60 \* 1000', page_content):
        E(page_file, "UTC-7 date conversion (toHermosillo) missing — all dates must be converted")

    # ── IVA never computed ────────────────────────────────────────────────
    if re.search(r'\b(iva|tax|impuesto)\s*[=*+]', page_content, re.IGNORECASE):
        E(page_file, "IVA/tax computation found in frontend — IVA is always 0, never compute it")

    # ── CSS scoped class names ────────────────────────────────────────────
    module_dashed = re.sub(r'([A-Z])', r'-\1', module).lstrip('-').lower()
    if css_content and not re.search(rf'\.{module_dashed}', css_content, re.IGNORECASE):
        # Also accept camelCase prefix
        if not re.search(rf'\.{module}', css_content, re.IGNORECASE):
            W(f"src/pages/{Module}Page.css", f"CSS class names should use '{module_dashed}-' prefix")

    # ── app_patches present ───────────────────────────────────────────────
    patches = fe.get("app_patches", {})
    for key in ("import_line", "private_route", "menu_item"):
        if not patches.get(key):
            E(page_file, f"app_patches.{key} missing")

    # ── setting_patch present ─────────────────────────────────────────────
    setting = fe.get("setting_patch", {})
    if not setting.get("section") or not setting.get("code"):
        E(page_file, "setting_patch missing section or code")

    # ── TIER_2: toFixed(2) for monetary display ───────────────────────────
    if gate.get("tier") == "TIER_2_FINANCIAL":
        if not re.search(r'\.toFixed\s*\(\s*2\s*\)', page_content):
            E(page_file, "TIER_2_FINANCIAL: monetary amounts must use .toFixed(2) for display")

    # ── Wizard layout: IonList/IonInfiniteScroll forbidden ────────────────
    if ui_pattern == "Wizard Flow Layout":
        if "IonList" in page_content:
            E(page_file, "Wizard Flow Layout must not use IonList — use IonCard per step only", auto=True)
        if "IonInfiniteScroll" in page_content:
            E(page_file, "Wizard Flow Layout must not use IonInfiniteScroll", auto=True)

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

    all_issues: list[Issue] = []

    if db:
        all_issues.extend(_check_database(db, spec, gate))
    if be:
        all_issues.extend(_check_backend(be, spec, gate))
    if fe:
        all_issues.extend(_check_frontend(fe, spec, gate))

    db_score = _score(all_issues, "database")
    be_score = _score(all_issues, "backend")
    fe_score = _score(all_issues, "frontend")
    passed   = db_score >= 90 and be_score >= 90 and fe_score >= 90

    result = {
        "scores":  {"database": db_score, "backend": be_score, "frontend": fe_score},
        "passed":  passed,
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
            f"database: {db_score}, backend: {be_score}, frontend: {fe_score}. "
            f"{len([i for i in all_issues if i.severity != 'warning'])} error(s) found."
        ),
    }

    tool_context.state["review_result"] = json.dumps(result)
    return result


# ============================================================================
# Thin Agent wrapper
# ============================================================================
