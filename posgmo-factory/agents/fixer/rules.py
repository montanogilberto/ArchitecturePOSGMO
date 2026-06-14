# Fixer Agent — deterministic SQL/Python/TypeScript fixers.
# No LLM involved. All transforms are regex/string operations.

from __future__ import annotations

import json
import re

from google.adk.tools.tool_context import ToolContext


# ============================================================================
# FIXER 1 — Database SQL
# ============================================================================

def _fix_datetime2(sql: str) -> tuple[str, list[str]]:
    """Non-IOT modules must use DATETIME, never DATETIME2."""
    fixes = []
    new = re.sub(r'\bDATETIME2\s*\(\s*\d+\s*\)', 'DATETIME', sql, flags=re.IGNORECASE)
    new = re.sub(r'\bDATETIME2\b', 'DATETIME', new, flags=re.IGNORECASE)
    if new != sql:
        fixes.append("Replaced DATETIME2 → DATETIME (non-IOT module)")
    return new, fixes


def _fix_sp_all_signature(sp_all: str, plural: str) -> tuple[str, list[str]]:
    """
    Ensure sp_all has @pjsonfile VARCHAR(MAX) parameter.
    Pattern: proc declaration with no parameter → inject it.
    """
    fixes = []

    # Already has the param?
    if '@pjsonfile' in sp_all:
        return sp_all, fixes

    # Match: CREATE [OR ALTER] PROC [dbo].[sp_X_all] followed by AS or newline (no param)
    pattern = re.compile(
        r'(CREATE\s+(?:OR\s+ALTER\s+)?PROC\s+(?:\[?dbo\]?\.)?\[?sp_\w+_all\]?)\s*\n(\s*AS)',
        re.IGNORECASE,
    )
    new = pattern.sub(r'\1 (@pjsonfile VARCHAR(MAX))\n\2', sp_all)
    if new != sp_all:
        fixes.append("Injected @pjsonfile VARCHAR(MAX) into sp_all signature")
        sp_all = new

    return sp_all, fixes


def _fix_sp_all_company_filter(sp_all: str, plural: str) -> tuple[str, list[str]]:
    """
    Ensure sp_all extracts @companyId from @pjsonfile and filters by it.
    Safe to inject only when both pieces are missing.
    """
    fixes = []

    has_declare = '@companyId' in sp_all
    has_where = re.search(r'WHERE\s+\[?companyId\]?\s*=\s*@companyId', sp_all, re.IGNORECASE)

    if has_declare and has_where:
        return sp_all, fixes

    if not has_declare:
        # Inject DECLARE block right after the first BEGIN
        extract = (
            f"\n    DECLARE @companyId INT;\n"
            f"    SET @companyId = TRY_CONVERT(INT,\n"
            f"        (SELECT TOP 1 JSON_VALUE(value, '$.companyId')\n"
            f"         FROM OPENJSON(@pjsonfile, '$.{plural}'))\n"
            f"    );\n"
        )
        # Insert after the first standalone BEGIN (not BEGIN TRY / BEGIN TRANSACTION)
        new = re.sub(
            r'(\bBEGIN\b)(\s*\n)(?!\s*(?:TRY|TRANSACTION|CATCH))',
            r'\1\2' + extract,
            sp_all,
            count=1,
            flags=re.IGNORECASE,
        )
        if new != sp_all:
            fixes.append("Injected @companyId extraction into sp_all")
            sp_all = new

    if not has_where:
        # Add WHERE before FOR JSON
        new = re.sub(
            r'(\s+FOR\s+JSON\b)',
            r'\n    WHERE [companyId] = @companyId\1',
            sp_all,
            count=1,
            flags=re.IGNORECASE,
        )
        if new != sp_all:
            fixes.append("Added WHERE companyId = @companyId filter to sp_all")
            sp_all = new

    return sp_all, fixes


def _fix_updated_at_isnull(sql: str) -> tuple[str, list[str]]:
    """
    updated_at in SELECT must use ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '').
    Fix raw [updated_at] references in SELECT statements.
    """
    fixes = []
    canonical = "ISNULL(CONVERT(VARCHAR(30), updated_at, 126), '')"
    if canonical.lower() in sql.lower():
        return sql, fixes

    # Replace bare updated_at in SELECT lines only.
    # Avoid Python regex lookbehind (must be fixed-width) by using line guards.
    lines = sql.split('\n')
    result = []
    in_select = False
    changed = False
    for line in lines:
        upper = line.strip().upper()
        if upper.startswith('SELECT'):
            in_select = True
        if upper.startswith('FROM') or upper.startswith('WHERE') or 'FOR JSON' in upper:
            in_select = False

        if in_select and re.search(r'\bupdated_at\b', line, re.IGNORECASE):
            # Skip lines where updated_at is already handled
            if 'ISNULL(' not in upper and 'CONVERT(' not in upper:
                line = re.sub(
                    r'\[?updated_at\]?',
                    canonical,
                    line,
                    flags=re.IGNORECASE,
                )
                changed = True

        result.append(line)

    if changed:
        fixes.append("Wrapped updated_at with ISNULL(CONVERT(VARCHAR(30), ..., 126), '')")
    return '\n'.join(result), fixes


def fix_database(db_artifacts: dict, gate_result: dict) -> tuple[dict, list[str]]:
    tier = gate_result.get("tier", "TIER_1_CATALOG")
    module = gate_result.get("_module", "")
    plural = f"{module}s" if module else ""
    all_fixes: list[str] = []

    sp_all  = db_artifacts.get("sp_all", "")
    sp_one  = db_artifacts.get("sp_one", "")
    sp_ups  = db_artifacts.get("sp_upsert", "")
    create  = db_artifacts.get("create_table", "")

    # 1. DATETIME2 → DATETIME for non-IOT
    if tier != "TIER_4_IOT":
        for attr, sql in [("sp_all", sp_all), ("sp_one", sp_one), ("sp_upsert", sp_ups), ("create_table", create)]:
            fixed, fixes = _fix_datetime2(sql)
            db_artifacts[attr] = fixed
            all_fixes.extend(fixes)
        sp_all = db_artifacts["sp_all"]

    # 2. sp_all: param + companyId filter
    if plural:
        sp_all, f1 = _fix_sp_all_signature(sp_all, plural)
        sp_all, f2 = _fix_sp_all_company_filter(sp_all, plural)
        db_artifacts["sp_all"] = sp_all
        all_fixes.extend(f1 + f2)

    # 3. updated_at ISNULL wrapping in sp_all and sp_one
    for attr in ("sp_all", "sp_one"):
        fixed, fixes = _fix_updated_at_isnull(db_artifacts.get(attr, ""))
        db_artifacts[attr] = fixed
        all_fixes.extend(fixes)

    return db_artifacts, all_fixes


# ============================================================================
# FIXER 2 — Backend Python
# ============================================================================

def _fix_round_calls(code: str) -> tuple[str, list[str]]:
    """
    Remove round(x, n) wrappers — return raw values from DB/API.
    Pattern: round(<expr>, <digits>) → <expr>
    Only removes single-argument-group round calls (not nested).
    """
    fixes = []
    # Match round(something, digits) — non-greedy inner group
    pattern = re.compile(r'\bround\(([^,()]+),\s*\d+\)', re.IGNORECASE)
    new = pattern.sub(r'\1', code)
    if new != code:
        fixes.append("Removed round() calls — raw values must be returned unchanged")
    return new, fixes


def _fix_all_sp_signature(code: str, plural: str) -> tuple[str, list[str]]:
    """
    all_{plural}_sp() with no args → all_{plural}_sp(json_file: dict)
    and update the SP EXEC call to pass @pjsonfile.
    """
    fixes = []
    fn_name = f"all_{plural}_sp"

    # Fix zero-arg: def all_X_sp(): → def all_X_sp(json_file: dict):
    no_arg = re.compile(rf'(def {re.escape(fn_name)})\(\s*\)\s*:', re.IGNORECASE)
    new = no_arg.sub(rf'\1(json_file: dict):', code)
    if new != code:
        fixes.append(f"Added json_file: dict param to {fn_name}()")
        code = new

    # Fix EXEC call missing @pjsonfile
    exec_no_param = re.compile(
        rf'(cursor\.execute\s*\(\s*"EXEC\s+\[?dbo\]?\.\[?sp_{re.escape(plural)}_all\]?"\s*)\)',
        re.IGNORECASE,
    )
    new = exec_no_param.sub(
        rf'cursor.execute("EXEC [dbo].[sp_{plural}_all] @pjsonfile = %s", (json.dumps(json_file),))',
        code,
    )
    if new != code:
        fixes.append(f"Fixed {fn_name} EXEC call to pass @pjsonfile")
        code = new

    return code, fixes


def _fix_route_get_to_post(code: str, plural: str) -> tuple[str, list[str]]:
    """router.get('/all_X') → router.post('/all_X')"""
    fixes = []
    pattern = re.compile(
        rf'(@router\.)(get)(\s*\(\s*["\']\/all_{re.escape(plural)}["\'])',
        re.IGNORECASE,
    )
    new = pattern.sub(r'\1post\3', code)
    if new != code:
        fixes.append(f"Changed router.get('/all_{plural}') → router.post()")
    return new, fixes


def fix_backend(backend_artifacts: dict, gate_result: dict) -> tuple[dict, list[str]]:
    module = gate_result.get("_module", "")
    plural = f"{module}s" if module else ""
    all_fixes: list[str] = []

    module_content = backend_artifacts.get("module_file", {}).get("content", "")
    route_content  = backend_artifacts.get("route_file", {}).get("content", "")

    # 1. Remove round() calls
    module_content, f1 = _fix_round_calls(module_content)
    all_fixes.extend(f1)

    # 2. Fix all_sp signature + EXEC call
    # 3. Ensure /all_ route is POST (not GET)
    if plural:
        module_content, f2 = _fix_all_sp_signature(module_content, plural)
        route_content,  f3 = _fix_route_get_to_post(route_content, plural)
        all_fixes.extend(f2 + f3)

    backend_artifacts["module_file"]["content"] = module_content
    backend_artifacts["route_file"]["content"]  = route_content
    return backend_artifacts, all_fixes


# ============================================================================
# FIXER 3 — Frontend TypeScript
# ============================================================================

# Maps Ionic component name → correct CustomEvent detail type
_ION_COMPONENT_EVENT_DETAIL: dict[str, str] = {
    "IonCheckbox":   "CheckboxChangeEventDetail",
    "IonRadioGroup": "RadioGroupChangeEventDetail",
    "IonSelect":     "SelectChangeEventDetail",
    "IonInput":      "InputInputEventDetail",
    "IonToggle":     "ToggleChangeEventDetail",
    "IonSearchbar":  "SearchbarInputEventDetail",
    "IonTextarea":   "TextareaChangeEventDetail",
}

# Additional imports required for the fixed types
_IONIC_IMPORTS_NEEDED = {
    "CheckboxChangeEventDetail":   "@ionic/react",
    "RadioGroupChangeEventDetail": "@ionic/react",
    "SelectChangeEventDetail":     "@ionic/react",
    "InputInputEventDetail":       "@ionic/react",
    "ToggleChangeEventDetail":     "@ionic/react",
    "SearchbarInputEventDetail":   "@ionic/react",
    "TextareaChangeEventDetail":   "@ionic/react",
}


def _fix_catch_any(code: str) -> tuple[str, list[str]]:
    """catch (err: any) → catch (err)"""
    fixes = []
    new = re.sub(r'\bcatch\s*\(\s*(\w+)\s*:\s*any\s*\)', r'catch (\1)', code)
    if new != code:
        fixes.append("Removed 'any' type annotation from catch parameters")
    return new, fixes


def _fix_double_json_parse(code: str) -> tuple[str, list[str]]:
    """
    JSON.parse(await res.json()) → await res.json()
    JSON.parse(response.json()) → response.json()  (if sync)
    """
    fixes = []
    # Async variant
    new = re.sub(r'JSON\.parse\(\s*(await\s+\w+\.json\(\))\s*\)', r'\1', code)
    if new != code:
        fixes.append("Removed double JSON.parse(await res.json()) — res.json() already parses")
        code = new
    # Sync variant
    new2 = re.sub(r'JSON\.parse\(\s*(\w+\.json\(\))\s*\)', r'\1', code)
    if new2 != code:
        fixes.append("Removed double JSON.parse(res.json())")
        code = new2
    return code, fixes


def _fix_custom_event_any(tsx: str) -> tuple[str, list[str]]:
    """
    Replace CustomEvent<any> with the correct typed generic.
    Strategy: scan lines; track the most recently seen Ionic component open tag;
    when we hit CustomEvent<any> in an event handler, map component → detail type.
    """
    fixes = []
    lines = tsx.split('\n')
    result = []
    current_component: str | None = None

    for line in lines:
        # Track most recently opened Ionic component (simple heuristic: look for <IonXxx)
        for component in _ION_COMPONENT_EVENT_DETAIL:
            if re.search(rf'<{component}\b', line):
                current_component = component
                break

        if 'CustomEvent<any>' in line:
            detail = (
                _ION_COMPONENT_EVENT_DETAIL.get(current_component, "")
                if current_component else ""
            )
            if detail:
                new_line = line.replace('CustomEvent<any>', f'CustomEvent<{detail}>')
                fixes.append(
                    f"Fixed CustomEvent<any> → CustomEvent<{detail}> (near {current_component})"
                )
                line = new_line
            else:
                # No component context — use e.detail.checked as signal
                if 'checked' in line or 'e.detail.checked' in tsx[max(0, tsx.find(line)-200):tsx.find(line)+200]:
                    new_line = line.replace('CustomEvent<any>', 'CustomEvent<CheckboxChangeEventDetail>')
                    fixes.append("Fixed CustomEvent<any> → CheckboxChangeEventDetail (fallback)")
                    line = new_line

        result.append(line)

    return '\n'.join(result), fixes


def _fix_bare_custom_event(tsx: str) -> tuple[str, list[str]]:
    """
    Replace bare CustomEvent (no generic) in event handler parameters.
    Pattern: (e: CustomEvent) — missing generic entirely.
    """
    fixes = []
    # Find (e: CustomEvent) or (ev: CustomEvent) that is NOT followed by <
    pattern = re.compile(r'(\w+:\s*CustomEvent)(?!\s*<)')
    new = pattern.sub(r'\1<void>', tsx)
    if new != tsx:
        fixes.append("Added <void> generic to bare CustomEvent parameters")
    return new, fixes


def _ensure_ionic_imports(tsx: str, fixes: list[str]) -> str:
    """
    If we introduced new detail types, make sure they are imported from @ionic/react.
    Finds the existing @ionic/react import block and appends missing types.
    """
    needed = set()
    for detail_type in _ION_COMPONENT_EVENT_DETAIL.values():
        if detail_type in tsx:
            needed.add(detail_type)

    if not needed:
        return tsx

    # Find existing @ionic/react import
    import_match = re.search(
        r"(import\s*\{)([^}]+)(\}\s*from\s*['\"]@ionic/react['\"])",
        tsx,
        re.DOTALL,
    )
    if not import_match:
        return tsx

    existing_imports = import_match.group(2)
    already_imported = set(t.strip() for t in existing_imports.split(',') if t.strip())
    to_add = needed - already_imported

    if not to_add:
        return tsx

    # Append to existing import list
    new_imports = existing_imports.rstrip() + ',\n  ' + ',\n  '.join(sorted(to_add)) + '\n'
    tsx = tsx[:import_match.start(2)] + new_imports + tsx[import_match.end(2):]
    fixes.append(f"Added missing Ionic imports: {', '.join(sorted(to_add))}")
    return tsx


def fix_frontend(frontend_artifacts: dict, gate_result: dict) -> tuple[dict, list[str]]:
    all_fixes: list[str] = []

    page_content = frontend_artifacts.get("page_file", {}).get("content", "")
    api_content  = frontend_artifacts.get("api_file", {}).get("content", "")

    # 1. catch (err: any) → catch (err)
    for attr, content in [("page_file", page_content), ("api_file", api_content)]:
        fixed, fixes = _fix_catch_any(content)
        frontend_artifacts[attr]["content"] = fixed
        all_fixes.extend(fixes)

    # 2. Remove double JSON.parse
    api_content = frontend_artifacts["api_file"]["content"]
    fixed, fixes = _fix_double_json_parse(api_content)
    frontend_artifacts["api_file"]["content"] = fixed
    all_fixes.extend(fixes)

    # 3. CustomEvent<any> → typed
    page_content = frontend_artifacts["page_file"]["content"]
    fixed, fixes = _fix_custom_event_any(page_content)
    all_fixes.extend(fixes)

    # 4. Bare CustomEvent (no generic)
    fixed, f2 = _fix_bare_custom_event(fixed)
    all_fixes.extend(f2)

    # 5. Ensure imports are present for any new types
    fixed = _ensure_ionic_imports(fixed, all_fixes)
    frontend_artifacts["page_file"]["content"] = fixed

    return frontend_artifacts, all_fixes


# ============================================================================
# Tool entry point — called by the thin Agent wrapper
# ============================================================================

def run_all_fixers(tool_context: ToolContext) -> dict:
    """
    Reads database_artifacts, backend_artifacts, and gate_result from session state.
    Applies all three fixers. Writes corrected artifacts back to session state.
    Returns a summary of every fix applied.
    """
    def _load(key: str) -> dict:
        raw = tool_context.state.get(key, "{}")
        if not isinstance(raw, str):
            return raw if isinstance(raw, dict) else {}
        raw = raw.strip()
        if not raw:
            return {}
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    gate_result      = _load("gate_result")
    db_artifacts     = _load("database_artifacts")
    backend_artifacts = _load("backend_artifacts")
    frontend_artifacts = _load("frontend_artifacts")

    tier   = gate_result.get("tier", "TIER_1_CATALOG")
    module = tool_context.state.get("module", "")
    gate_result["_module"] = module  # pass module name into fixers

    report: dict[str, list[str]] = {}

    # Fixer 1 — Database
    if db_artifacts and db_artifacts.get("sp_all"):
        db_artifacts, db_fixes = fix_database(db_artifacts, gate_result)
        report["database"] = db_fixes
        raw = json.dumps(db_artifacts)
        tool_context.state["database_artifacts"] = raw

    # Fixer 2 — Backend
    if backend_artifacts and backend_artifacts.get("module_file"):
        backend_artifacts, be_fixes = fix_backend(backend_artifacts, gate_result)
        report["backend"] = be_fixes
        tool_context.state["backend_artifacts"] = json.dumps(backend_artifacts)

    # Fixer 3 — Frontend (may not exist yet at this stage — safe to skip)
    if frontend_artifacts and frontend_artifacts.get("page_file"):
        frontend_artifacts, fe_fixes = fix_frontend(frontend_artifacts, gate_result)
        report["frontend"] = fe_fixes
        tool_context.state["frontend_artifacts"] = json.dumps(frontend_artifacts)

    total = sum(len(v) for v in report.values())
    report["summary"] = f"{total} fix(es) applied across {len(report)-1} artifact(s)."
    return report


# ============================================================================
# Thin Agent wrapper
# ============================================================================
