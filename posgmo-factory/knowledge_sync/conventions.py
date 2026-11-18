"""
Style conventions — the rules the product repos already wrote down for
themselves, plus one recent real module per layer as the reference template
generators should imitate. Nothing here is invented: every rule is a
verbatim file from the repo, every template is real code from it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_TEMPLATE_CHAR_CAP = 6000   # per file — enough to show the style, bounded prompt cost
_REFERENCE_MAX_LINES = 400  # a focused module, not a catch-all like users.py (600+ lines)
_MIN_RULE_DOC_CHARS = 200   # skip placeholder docs (smartloans_backend README is just a title)

# Rule documents per repo, first existing wins per entry.
_RULE_DOCS = {
    "frontend": ["CLAUDE.md"],
    "backend": ["CLAUDE.md", "README.md"],
    "agents": ["CLAUDE.md", "README.md"],
}

# The frontend's own CLAUDE.md names its MVVM template; keep it in one place.
FRONTEND_TEMPLATE_FEATURE = "src/pages/loans/BorrowerOnboarding"


def git_info(repo: Path) -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                  text=True, timeout=10).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    return {"commit": run("rev-parse", "--short", "HEAD"), "branch": run("branch", "--show-current"),
            "commitDate": run("log", "-1", "--format=%cI")}


def _last_commit_ts(repo: Path, rel: str) -> int:
    try:
        out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%ct", "--", rel],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _excerpt(repo: Path, rel: str) -> dict:
    path = repo / rel
    text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    return {"file": rel, "lines": text.count("\n") + 1 if text else 0,
            "content": text[:_TEMPLATE_CHAR_CAP],
            "truncated": len(text) > _TEMPLATE_CHAR_CAP}


def _rule_docs(repo: Path, layer: str) -> list[dict]:
    docs = []
    for name in _RULE_DOCS[layer]:
        p = repo / name
        if p.is_file() and p.stat().st_size >= _MIN_RULE_DOC_CHARS:
            docs.append({"file": name, "content": p.read_text(encoding="utf-8", errors="ignore")})
            break
    return docs


def backend_reference(backend: Path) -> dict | None:
    """Most recently changed FOCUSED module (≤ _REFERENCE_MAX_LINES) that has the
    full modules/ + routes_/ pair, calls a stored procedure, and is instrumented
    with observability — i.e. the current style of a complete, compliant module."""
    candidates = []
    for mod in (backend / "modules").glob("*.py"):
        route = backend / "routes_" / mod.name
        if not route.is_file():
            continue
        text = mod.read_text(encoding="utf-8", errors="ignore")
        if "EXEC" not in text or not ("log_audit" in text or "timed_integration" in text):
            continue
        if text.count("\n") > _REFERENCE_MAX_LINES:
            continue
        ts = max(_last_commit_ts(backend, f"modules/{mod.name}"),
                 _last_commit_ts(backend, f"routes_/{mod.name}"))
        candidates.append((ts, mod.stem))
    if not candidates:
        return None
    _, name = max(candidates)
    return {
        "module": name,
        "why": "most recently changed focused module with modules/ + routes_/ pair, SP calls and observability",
        "files": [_excerpt(backend, f"routes_/{name}.py"), _excerpt(backend, f"modules/{name}.py")],
    }


def backend_migration_reference(backend: Path) -> dict | None:
    """Newest migration that ships with its _ROLLBACK partner."""
    mig = backend / "sql" / "migration_history" / "migrations"
    if not mig.is_dir():
        return None
    pairs = sorted(f for f in mig.glob("*.sql")
                   if not f.stem.endswith("_ROLLBACK") and (mig / f"{f.stem}_ROLLBACK.sql").is_file())
    if not pairs:
        return None
    newest = pairs[-1]
    rel = str(newest.relative_to(backend))
    return {"why": "newest migration with a paired _ROLLBACK.sql — the required migration shape",
            "files": [_excerpt(backend, rel), {"file": rel.replace(".sql", "_ROLLBACK.sql")}]}


def frontend_reference(frontend: Path) -> dict | None:
    feat = frontend / FRONTEND_TEMPLATE_FEATURE
    if not feat.is_dir():
        return None
    name = feat.name
    tree = sorted(str(f.relative_to(frontend)) for f in feat.rglob("*") if f.is_file())
    shell = f"{Path(FRONTEND_TEMPLATE_FEATURE).parent}/{name}Page.tsx"
    return {
        "feature": FRONTEND_TEMPLATE_FEATURE,
        "why": "named as the MVVM template in the frontend repo's own CLAUDE.md",
        "tree": tree,
        "files": [_excerpt(frontend, shell),
                  _excerpt(frontend, f"{FRONTEND_TEMPLATE_FEATURE}/{name}View.tsx"),
                  _excerpt(frontend, f"{FRONTEND_TEMPLATE_FEATURE}/{name}Logic.ts")],
    }


def agents_reference(agents_repo: Path) -> dict | None:
    """Most recently changed agent folder that proposes writes (pending_actions pattern)."""
    candidates = []
    for agent_py in (agents_repo / "agents").glob("*/agent.py"):
        if "propose_action" not in agent_py.read_text(encoding="utf-8", errors="ignore"):
            continue
        rel = str(agent_py.parent.relative_to(agents_repo))
        candidates.append((_last_commit_ts(agents_repo, rel), rel))
    if not candidates:
        return None
    _, rel = max(candidates)
    return {"agent": rel, "why": "most recently changed agent using the PROPOSE (pending_actions) pattern",
            "files": [_excerpt(agents_repo, f"{rel}/agent.py"), _excerpt(agents_repo, f"{rel}/prompt.py"),
                      _excerpt(agents_repo, "tools/pending_actions.py")]}


def repo_conventions(paths: dict[str, Path]) -> dict:
    fe, be, ag = paths["frontend"], paths["backend"], paths["agents"]
    return {
        "frontend": {"repo": str(fe), **git_info(fe), "rules": _rule_docs(fe, "frontend"),
                     "reference_feature": frontend_reference(fe)},
        "backend": {"repo": str(be), **git_info(be), "rules": _rule_docs(be, "backend"),
                    "reference_module": backend_reference(be),
                    "reference_migration": backend_migration_reference(be)},
        "agents": {"repo": str(ag), **git_info(ag), "rules": _rule_docs(ag, "agents"),
                   "reference_agent": agents_reference(ag)},
    }
