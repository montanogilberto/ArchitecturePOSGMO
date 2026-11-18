# Raw-SQL detector for generated/hand-written backend modules.
# No LLM, no ADK imports -- pure stdlib, so it can also be copied into the
# backend repo as a CI check (smartloans_backend/scripts/check_raw_sql.py
# is a verbatim copy of find_raw_sql + helpers; keep them in sync).
#
# Backend rule: modules never issue raw SQL -- only EXEC [dbo].[sp_*].
#
# Why AST and not the old regex: the previous rule only matched
# `cursor\.execute\s*\(\s*["\'](?!EXEC)`, so any other cursor name
# (`cur.execute(...)` -- 16 of 23 real violations found in the backend on
# 2026-09-23), SQL built in a variable first, or f-strings slipped through.
# Two independent signals, either one flags:
#   1. execute_literal: <anything>.execute/executemany(<string literal>) whose
#      text does not start with EXEC (case-insensitive) -- any receiver name.
#   2. sql_literal: any non-docstring string literal that reads as a DML/DDL
#      statement (UPPERCASE keywords + a table-shaped clause), which catches
#      `sql = "SELECT ... FROM ..."; cur.execute(sql)`. Uppercase-only on
#      purpose: prose like "select all information from the table" in route
#      summaries must not trip it; lowercase SQL passed straight to
#      execute() is still caught by signal 1.

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

_EXEC_PREFIX = re.compile(r"^\s*EXEC(UTE)?\b", re.IGNORECASE)

_TABLE = r"[\w\[\]#@.]+"
_SQL_STATEMENT = re.compile(
    r"^\s*(?:"
    r"SELECT\b[\s\S]*?\bFROM\s+" + _TABLE +
    r"|INSERT\s+(?:INTO\s+)?" + _TABLE +
    r"|UPDATE\s+" + _TABLE + r"\s+SET\b"
    r"|DELETE\s+(?:FROM\s+)?" + _TABLE +
    r"|MERGE\s+(?:INTO\s+)?" + _TABLE +
    r"|TRUNCATE\s+TABLE\b"
    r"|(?:CREATE|ALTER|DROP)\s+(?:TABLE|PROC|PROCEDURE|VIEW|INDEX)\b"
    r")"
)


@dataclass(frozen=True)
class RawSql:
    line: int
    kind: str      # "execute_literal" | "sql_literal"
    snippet: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.snippet}"


def _literal_text(node: ast.AST) -> str | None:
    """Text of a str constant, or the constant parts of an f-string
    (placeholders become '{}'); None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and _literal_text(body[0].value) is not None:
                ids.add(id(body[0].value))
    return ids


def _snippet(text: str) -> str:
    return " ".join(text.split())[:100]


def _find_with_regex(source: str) -> list[RawSql]:
    """Fallback for content that does not parse (LLM output mid-repair)."""
    found = []
    pat = re.compile(r"""\.execute(?:many)?\s*\(\s*[fFrRbBuU]{0,2}("{3}|'{3}|"|')(.*?)\1""", re.DOTALL)
    for m in pat.finditer(source):
        text = m.group(2)
        if not _EXEC_PREFIX.match(text):
            found.append(RawSql(source.count("\n", 0, m.start()) + 1, "execute_literal", _snippet(text)))
    return found


def find_raw_sql(source: str) -> list[RawSql]:
    """All raw-SQL sites in a Python module's source. [] means clean."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _find_with_regex(source)

    docstrings = _docstring_nodes(tree)
    found: dict[tuple[int, str], RawSql] = {}
    execute_args: set[int] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("execute", "executemany")
            and node.args
        ):
            text = _literal_text(node.args[0])
            if text is not None:
                execute_args.add(id(node.args[0]))
                if not _EXEC_PREFIX.match(text):
                    found[(node.lineno, "execute_literal")] = RawSql(node.lineno, "execute_literal", _snippet(text))

    # f-string pieces are visited as Constants too; judge the whole JoinedStr only
    fstring_parts = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    skip = docstrings | execute_args | fstring_parts

    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        text = _literal_text(node)
        if text is None:
            continue
        if _SQL_STATEMENT.match(text):
            line = getattr(node, "lineno", 0)
            if (line, "execute_literal") not in found:
                found[(line, "sql_literal")] = RawSql(line, "sql_literal", _snippet(text))

    return sorted(found.values(), key=lambda r: (r.line, r.kind))
