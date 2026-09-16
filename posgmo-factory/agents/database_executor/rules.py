"""
Database Executor — deterministic post-generation SQL execution.

database_agent writes its SQL as plain text (output_key="database_artifacts"),
the same pattern backend_agent/frontend_agent already use. This module reads
that text back out of session state, and -- for the shapes execute_sql_on_server
already understands -- calls it directly as ordinary Python, never as an
LLM-facing tool call. There is no JSON-serialization boundary for the SQL to
cross here, so there's nothing for a model to get wrong.

Why this split exists: database_agent used to call execute_sql_on_server
itself, as a tool taking four large multi-line SQL strings as arguments.
Investigation (docs/experiment1-leadCapture-evaluation.md) traced this
agent's chronic MALFORMED_FUNCTION_CALL failures to that exact call --
correctly JSON-escaping large text full of quotes and GO statements inside a
function-call argument is a much harder generation task than writing the
same text as a plain response, and the old design made the model do it
twice (once as tool arguments, once again as output_key text). Removing the
tool call removes the failure mode; execute_sql_on_server itself is
unchanged (see agents/database/rules.py).
"""
from __future__ import annotations

import json

from agents.database.rules import execute_sql_on_server

_REQUIRED_KEYS = ("create_table", "sp_upsert", "sp_all", "sp_one")


def _safe_load(raw) -> dict:
    if not isinstance(raw, str):
        return raw if isinstance(raw, dict) else {}
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = "\n".join(
            l for l in raw.splitlines() if not l.strip().startswith("```")
        ).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def merge_execution_result(state: dict) -> dict:
    """Reads database_artifacts from state and, if it's in the shape
    execute_sql_on_server expects (CRUD_ONLY / CRUD_AND_CONNECTOR /
    WEBHOOK_HANDLER -- create_table + sp_upsert + sp_all + sp_one all
    present), executes it and returns the artifacts dict with an
    "execution" key added.

    Artifacts in a different shape (ACTION_ROUTER's sp_action_router,
    BUSINESS_LOGIC's sp_data/sp_persist, BLOB_UPLOAD's sql:null) are
    returned unchanged -- execute_sql_on_server only knows one shape today,
    and inventing a mapping for the others is a separate decision, not this
    fix's job. Same for an empty/malformed artifact: nothing to execute,
    returned as-is so the existing ARTIFACT_FAILURE/NOT_VERIFIABLE reporting
    downstream still sees it as missing.
    """
    artifacts = _safe_load(state.get("database_artifacts", ""))
    if not artifacts:
        return artifacts

    if not all(artifacts.get(k) for k in _REQUIRED_KEYS):
        return artifacts

    result = execute_sql_on_server(
        artifacts["create_table"], artifacts["sp_upsert"], artifacts["sp_all"], artifacts["sp_one"],
    )
    artifacts["execution"] = result
    return artifacts
