"""
Agent contracts — did the agent do the job it was assigned, not merely did
the model respond.

Experiment 2 showed pipeline_diagnostics.classify_event() isn't enough on its
own: review_fixer_agent produced a turn with real text and a state write (so
classify_event correctly did not flag it), but that text was a free-form
prose summary instead of a call to apply_review_fixes -- the one tool its
instruction requires. "The agent did something observable" and "the agent
did what its instruction required" are different questions; this module
answers the second one.

Each pipeline agent has an explicit contract: the tool call it must complete
successfully, and/or the session-state key its work must populate with a
non-trivial, correctly-shaped value. After a run, `finalize()` checks both
against what actually happened and classifies every agent as:

  SATISFIED         -- contract fully met
  CONTRACT_FAILURE  -- the required tool call never completed successfully
  ARTIFACT_FAILURE  -- the tool succeeded (or wasn't required) but the
                       resulting state key is missing, empty, or malformed
  NOT_OBSERVED      -- this agent never ran at all in this session

Purely observational: never blocks, retries, or changes agent behavior.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


def _parse(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _nonempty_str(d: Any, key: str) -> bool:
    return isinstance(d, dict) and isinstance(d.get(key), str) and bool(d[key].strip())


@dataclass
class AgentContract:
    agent: str
    expected_tool: Optional[str] = None
    expected_artifact_key: Optional[str] = None
    # Given the parsed contents of expected_artifact_key, return True if it looks
    # like a real, complete artifact rather than empty/placeholder content.
    artifact_ok: Optional[Callable[[Any], bool]] = None


CONTRACTS: list[AgentContract] = [
    AgentContract("host_architect_agent", expected_artifact_key="app_profile",
                  artifact_ok=lambda v: isinstance(v, dict) and bool(v.get("profile_id"))),
    AgentContract("prd_parser_agent", expected_tool="store_prd_context"),
    AgentContract("prd_enricher_agent", expected_tool="save_enriched_prd"),
    AgentContract("schema_analyst_agent", expected_tool="analyze_database_schema",
                  expected_artifact_key="schema_analysis",
                  artifact_ok=lambda v: isinstance(v, dict) and len(v) > 0),
    AgentContract("architect_agent", expected_artifact_key="specification",
                  artifact_ok=lambda v: isinstance(v, dict) and all(
                      k in v for k in ("module", "db", "backend", "frontend"))),
    AgentContract("decision_gate_agent", expected_artifact_key="gate_result",
                  artifact_ok=lambda v: isinstance(v, dict) and bool(v.get("status"))),
    AgentContract("database_agent", expected_artifact_key="database_artifacts",
                  artifact_ok=lambda v: isinstance(v, dict) and all(
                      _nonempty_str(v, k) for k in ("create_table", "sp_upsert", "sp_all", "sp_one"))),
    AgentContract("backend_agent", expected_artifact_key="backend_artifacts",
                  artifact_ok=lambda v: isinstance(v, dict)
                  and _nonempty_str(v.get("module_file", {}), "content")
                  and _nonempty_str(v.get("route_file", {}), "content")),
    AgentContract("design_consistency_agent", expected_artifact_key="design_brief",
                  artifact_ok=lambda v: isinstance(v, dict) and len(v) > 0),
    AgentContract("fixer_agent", expected_tool="run_all_fixers"),
    AgentContract("frontend_agent", expected_artifact_key="frontend_artifacts",
                  artifact_ok=lambda v: isinstance(v, dict)
                  and _nonempty_str(v.get("api_file", {}), "content")
                  and _nonempty_str(v.get("page_file", {}), "content")),
    AgentContract("reviewer_agent", expected_tool="run_review",
                  expected_artifact_key="review_result",
                  artifact_ok=lambda v: isinstance(v, dict) and "scores" in v),
    AgentContract("loop_exit_agent", expected_tool="check_and_exit"),
    AgentContract("review_fixer_agent", expected_tool="apply_review_fixes"),
]

_BY_AGENT = {c.agent: c for c in CONTRACTS}


class ContractTracker:
    """Observes events live, then scores every contract against final state."""

    def __init__(self) -> None:
        self._agents_seen: set[str] = set()
        # (agent, tool_name) -> True once a real function_response (not an
        # error) for that call has been observed.
        self._tool_succeeded: dict[tuple[str, str], bool] = {}

    def observe(self, event: Any) -> None:
        author = getattr(event, "author", None)
        if not author:
            return
        self._agents_seen.add(author)

        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            return
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr and getattr(fr, "name", None):
                resp = getattr(fr, "response", None)
                # A malformed/errored call surfaces as an event-level error_code
                # rather than a function_response, so any function_response we
                # see here is a genuine, structurally valid tool return.
                self._tool_succeeded[(author, fr.name)] = True

    def finalize(self, final_state: dict) -> list[dict]:
        report = []
        for contract in CONTRACTS:
            agent = contract.agent
            entry: dict[str, Any] = {"agent": agent}

            if agent not in self._agents_seen:
                entry["verdict"] = "NOT_OBSERVED"
                entry["detail"] = "This agent never produced a single event in this run."
                report.append(entry)
                continue

            tool_ok = True
            if contract.expected_tool:
                tool_ok = self._tool_succeeded.get((agent, contract.expected_tool), False)
                entry["expected_tool"] = contract.expected_tool
                entry["tool_call_succeeded"] = tool_ok

            artifact_ok = True
            if contract.expected_artifact_key:
                raw = final_state.get(contract.expected_artifact_key)
                parsed = _parse(raw)
                artifact_ok = bool(contract.artifact_ok(parsed)) if contract.artifact_ok else bool(parsed)
                entry["expected_artifact"] = contract.expected_artifact_key
                entry["artifact_populated"] = artifact_ok

            if not tool_ok:
                entry["verdict"] = "CONTRACT_FAILURE"
                entry["detail"] = (
                    f"expected_tool={contract.expected_tool} actual_tool=none "
                    f"(never completed successfully for {agent})"
                )
            elif not artifact_ok:
                entry["verdict"] = "ARTIFACT_FAILURE"
                entry["detail"] = (
                    f"expected_artifact={contract.expected_artifact_key} "
                    f"actual_artifact=missing/empty/malformed"
                )
            else:
                entry["verdict"] = "SATISFIED"

            report.append(entry)
        return report


def summarize(report: list[dict]) -> dict:
    by_verdict: dict[str, int] = {}
    for entry in report:
        by_verdict[entry["verdict"]] = by_verdict.get(entry["verdict"], 0) + 1
    failures = [e["agent"] for e in report if e["verdict"] != "SATISFIED"]
    return {"counts": by_verdict, "failed_agents": failures}
