"""
Deterministic extractors — each reads one fact source and returns plain
dicts in the shape of the knowledge file it feeds. No LLM, no writes.
A source that can't be read raises; sync.py records it and keeps the
previous knowledge file instead of overwriting it with an empty one.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
_SP_NAME_RE = re.compile(r"\b(sp_[A-Za-z0-9_]+)")


# ---------------------------------------------------------------------------
# Backend (smartloans_backend)
# ---------------------------------------------------------------------------

def _router_kwargs(tree: ast.Module) -> dict:
    """prefix/tags passed to `router = APIRouter(...)`, if any."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "APIRouter"):
            out = {}
            for kw in node.keywords:
                try:
                    out[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    pass
            return out
    return {}


def backend_routes(backend: Path) -> list[dict]:
    """routes_/*.py → [{path, file, tags, methods, handlers}] (one entry per path)."""
    by_path: dict[str, dict] = {}
    for file in sorted((backend / "routes_").glob("*.py")):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        router = _router_kwargs(tree)
        prefix = router.get("prefix", "") or ""
        tags = router.get("tags") or [file.stem]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in _HTTP_METHODS and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    continue
                path = prefix + str(dec.args[0].value)
                entry = by_path.setdefault(path, {
                    "path": path, "file": f"routes_/{file.name}", "tags": list(tags),
                    "methods": [], "handlers": [],
                })
                method = dec.func.attr.upper()
                if method not in entry["methods"]:
                    entry["methods"].append(method)
                if node.name not in entry["handlers"]:
                    entry["handlers"].append(node.name)
    return sorted(by_path.values(), key=lambda r: r["path"])


def sp_module_bindings(backend: Path) -> dict[str, str]:
    """sp name → first modules/*.py that references it."""
    bindings: dict[str, str] = {}
    for file in sorted((backend / "modules").glob("*.py")):
        for name in _SP_NAME_RE.findall(file.read_text(encoding="utf-8", errors="ignore")):
            bindings.setdefault(name, f"modules/{file.name}")
    return bindings


# ---------------------------------------------------------------------------
# Live database (read-only)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
       COALESCE(CAST(c.CHARACTER_MAXIMUM_LENGTH AS varchar(20)),
                CAST(c.NUMERIC_PRECISION AS varchar(20)), 'NULL') AS len,
       c.IS_NULLABLE,
       CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END AS is_pk,
       CASE WHEN fk.parent_column IS NOT NULL THEN 'YES' ELSE 'NO' END AS is_fk
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
LEFT JOIN (
    SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
) pk ON pk.TABLE_SCHEMA = c.TABLE_SCHEMA AND pk.TABLE_NAME = c.TABLE_NAME AND pk.COLUMN_NAME = c.COLUMN_NAME
LEFT JOIN (
    SELECT DISTINCT OBJECT_NAME(fkc.parent_object_id) AS parent_table,
           COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS parent_column
    FROM sys.foreign_key_columns fkc
) fk ON fk.parent_table = c.TABLE_NAME AND fk.parent_column = c.COLUMN_NAME
WHERE c.TABLE_SCHEMA = 'dbo'
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
"""

_FK_SQL = """
SELECT OBJECT_NAME(fk.referenced_object_id) AS parent_table,
       OBJECT_NAME(fk.parent_object_id)     AS child_table,
       fk.name
FROM sys.foreign_keys fk
ORDER BY parent_table, child_table, fk.name
"""

_SP_SQL = """
SELECT p.name, prm.name AS param
FROM sys.procedures p
LEFT JOIN sys.parameters prm ON prm.object_id = p.object_id
WHERE p.schema_id = SCHEMA_ID('dbo')
ORDER BY p.name, prm.parameter_id
"""


def _connect():
    from agents.schema_analyst.rules import _connect as connect  # same creds as schema_analyst
    return connect()


def live_database() -> dict:
    """{"columns": [csv rows], "relationships": [...], "procedures": {name: [params]}}."""
    with _connect() as conn:
        cur = conn.cursor()
        columns = [list(map(lambda v: "" if v is None else str(v), r))
                   for r in cur.execute(_SCHEMA_SQL).fetchall()]
        relationships = [
            {"parent_table": r[0], "child_table": r[1], "type": "||--o{",
             "fk_constraint_name": f"fk_{r[2]}"}
            for r in cur.execute(_FK_SQL).fetchall()
        ]
        procedures: dict[str, list[str]] = {}
        for name, param in cur.execute(_SP_SQL).fetchall():
            params = procedures.setdefault(name, [])
            if param:
                params.append(param)
    return {"columns": columns, "relationships": relationships, "procedures": procedures}


# ---------------------------------------------------------------------------
# Frontend (POSVending)
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(r"""import\s+(\w+)\s+from\s+['"](\.{1,2}/[^'"]+)['"]""")
_LAZY_RE = re.compile(r"""const\s+(\w+)\s*=\s*(?:React\.)?lazy\(\s*\(\)\s*=>\s*import\(\s*['"](\.{1,2}/[^'"]+)['"]""")
_ROUTE_OPEN_RE = re.compile(r"<(PrivateRoute|Route)\b")


def _route_tags(text: str):
    """Yield (tag, attrs) for each <Route>/<PrivateRoute> opening tag. Scans
    brace depth so a `>` inside `render={() => <Redirect …/>}` doesn't end it."""
    for m in _ROUTE_OPEN_RE.finditer(text):
        depth, i = 0, m.end()
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        yield m.group(1), text[m.end():i].rstrip("/")
_ATTR_RE = re.compile(r"""(\w+)=(?:"([^"]*)"|\{([^{}]*)\})""")


def _resolve_tsx(src: Path, base: Path, spec: str) -> str | None:
    target = (base / spec).resolve()
    for cand in (target, target.with_suffix(".tsx"), target.with_suffix(".ts"), target / "index.tsx"):
        if cand.is_file():
            return str(cand.relative_to(src.parent))
    return None


def frontend_routes(frontend: Path) -> list[dict]:
    """src/App.tsx <Route>/<PrivateRoute> → [{path, component, authenticated, feature}]."""
    app = frontend / "src" / "App.tsx"
    text = app.read_text(encoding="utf-8")
    imports = {name: spec for name, spec in _IMPORT_RE.findall(text)}
    imports.update({name: spec for name, spec in _LAZY_RE.findall(text)})
    routes: dict[str, dict] = {}
    for tag, attrs in _route_tags(text):
        # attribute values without nested braces; render={...} is detected separately
        found = {k: (v1 or v2) for k, v1, v2 in _ATTR_RE.findall(attrs)}
        path = found.get("path")
        if not path or "{" in path:
            continue
        comp = found.get("component")
        component = None
        if comp and comp in imports:
            component = _resolve_tsx(frontend / "src", app.parent, imports[comp])
        elif "Redirect" in attrs:
            component = "redirect"
        routes.setdefault(path, {
            "path": path,
            "component": component or comp,
            "authenticated": tag == "PrivateRoute",
            "feature": found.get("feature"),
        })
    return sorted(routes.values(), key=lambda r: r["path"])


_PROPS_RE = re.compile(r"(?:interface|type)\s+(\w*Props)\s*=?\s*\{(.*?)\n\}", re.S)
_PROP_LINE_RE = re.compile(r"^\s*(?:readonly\s+)?(\w+)(\??)\s*:\s*(.+?);?\s*(?://.*)?$")


def frontend_components(frontend: Path) -> list[dict]:
    """src/components/**/*.tsx → [{componentName, filePath, folder, props}]."""
    out = []
    root = frontend / "src" / "components"
    for file in sorted(root.rglob("*.tsx")):
        if file.name.endswith((".test.tsx", ".spec.tsx")):
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        props = []
        m = _PROPS_RE.search(text)
        if m:
            for line in m.group(2).splitlines():
                pm = _PROP_LINE_RE.match(line)
                if pm:
                    props.append({"name": pm.group(1), "type": pm.group(3).strip().rstrip(";"),
                                  "required": pm.group(2) != "?"})
        out.append({
            "componentName": file.stem,
            "filePath": str(file.relative_to(frontend)),
            "folder": str(file.parent.relative_to(root)) if file.parent != root else "",
            "props": props,
        })
    return out


def frontend_api_clients(frontend: Path) -> list[dict]:
    """src/api/*.ts → [{file, functions: [{name, method, path}]}] (paths None when dynamic)."""
    from ecosystem_graph.frontend_calls import extract_frontend_edges

    out = []
    for file in sorted((frontend / "src" / "api").glob("*.ts")):
        edges = extract_frontend_edges(str(file))
        out.append({
            "file": f"src/api/{file.name}",
            "functions": [{"name": e["frontend_func"], "method": e["method"], "path": e["path"]}
                          for e in edges],
        })
    return out


def frontend_features(frontend: Path) -> list[dict]:
    """src/pages/{area}/{Feature}/ folders and whether they follow the MVVM layout."""
    pages = frontend / "src" / "pages"
    out = []
    for area in sorted(p for p in pages.iterdir() if p.is_dir()):
        for feat in sorted(p for p in area.iterdir() if p.is_dir() and p.name[:1].isupper()):
            name = feat.name
            files = sorted(str(f.relative_to(frontend)) for f in feat.rglob("*") if f.is_file())
            has = lambda suffix: (feat / f"{name}{suffix}").is_file()  # noqa: E731
            shell = area / f"{name}Page.tsx"
            out.append({
                "area": area.name,
                "feature": name,
                "folder": str(feat.relative_to(frontend)),
                "pageShell": str(shell.relative_to(frontend)) if shell.is_file() else None,
                "mvvm": has("View.tsx") and has("Logic.ts"),
                "fileCount": len(files),
            })
    return out


# ---------------------------------------------------------------------------
# Agents (LoanAgents_SmartLoans)
# ---------------------------------------------------------------------------

def agents_catalog(agents_repo: Path) -> list[dict]:
    """agents/*/agent.py → [{folder, name, model, description, tools, autonomy_hint}]."""
    out = []
    for agent_py in sorted((agents_repo / "agents").glob("*/agent.py")):
        try:
            tree = ast.parse(agent_py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None)
                    in {"Agent", "LlmAgent", "SequentialAgent", "ParallelAgent", "LoopAgent"}):
                continue
            kw = {k.arg: k.value for k in node.keywords}

            def lit(key):
                try:
                    return ast.literal_eval(kw[key]) if key in kw else None
                except ValueError:
                    return None

            tools = []
            for t in getattr(kw.get("tools"), "elts", []):
                if isinstance(t, ast.Call):
                    func = next((k.value for k in t.keywords if k.arg == "func"), t.args[0] if t.args else None)
                    tools.append(getattr(func, "id", None) or getattr(t.func, "id", "?"))
                elif isinstance(t, ast.Name):
                    tools.append(t.id)
            out.append({
                "folder": f"agents/{agent_py.parent.name}",
                "name": lit("name"),
                "kind": node.func.id,
                "model": lit("model"),
                "description": (lit("description") or "")[:400],
                "tools": tools,
                "proposes_writes": "propose_action" in tools,
            })
            break  # first agent definition per file is the folder's agent
    return out
