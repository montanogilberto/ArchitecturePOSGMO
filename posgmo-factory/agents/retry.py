"""
Bounded retry for LLM construction agents.

MALFORMED_FUNCTION_CALL / empty turns are model-level stochasticity
(Milestone 7, confirmed via isolated diagnostics): the same agent with the
same inputs usually succeeds on the next attempt. Before this, one such turn
failed the whole run and the fix was "re-run the entire 11-stage pipeline" --
32 times for factoryRunUsage. Retrying just the failed stage is cheaper and
contains the failure where it happens.

`RetryUntilUsable` wraps an existing LLM agent without changing it (same
prompt, tools and output_key); events keep the inner agent's author, so
pipeline_diagnostics still attributes every failed attempt correctly.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Callable

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions


def retry_key(agent_name: str) -> str:
    return f"_retry_notice:{agent_name}"


def retry_notice(state, agent_name: str) -> str:
    """Instruction suffix for a retried attempt (empty on the first attempt)."""
    notice = state.get(retry_key(agent_name)) if state is not None else None
    return f"\n\n## RETRY NOTICE\n{notice}\n" if notice else ""


def parse_json_object(raw) -> dict:
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


def describe_unusable(raw) -> str:
    """Why an attempt's output was rejected -- a bare "unusable output" left
    the cause of a costly retry undiagnosable (2026-09-24: 2/8 frontend
    attempts failed, not reproducible in 5 replays)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "empty"
    if parse_json_object(raw):
        return "JSON parsed but required content missing"
    body = str(raw).strip()
    if body.startswith("```"):
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("```")).strip()
    try:
        json.loads(body)
        return "JSON is not an object"
    except json.JSONDecodeError as e:
        return f"invalid JSON: {e.msg} at char {e.pos} of {len(body)}; starts {body[:60]!r}"


def _attempt_context(ctx, agent_name: str, attempt: int):
    """Each attempt runs on its own ADK branch, so it never sees the previous
    attempt's reply. Without this, ADK includes an agent's own earlier turns
    from the same invocation (even with include_contents='none'), and a retry
    answered "I have completed the previous request... provided in the last
    JSON output" instead of producing it (Step 1 evidence: frontend 3/3,
    architect 3/3, database repair 2/2)."""
    if not hasattr(ctx, "model_copy"):
        return ctx  # test doubles
    base = getattr(ctx, "branch", None)
    leaf = f"{agent_name}_attempt{attempt}"
    return ctx.model_copy(update={"branch": f"{base}.{leaf}" if base else leaf})


async def run_with_retries(
    agent: BaseAgent,
    ctx: InvocationContext,
    output_key: str,
    is_usable: Callable[[object], bool],
    max_attempts: int,
    report: dict,
) -> AsyncGenerator[Event, None]:
    """Runs `agent` until the value it writes to `output_key` passes
    `is_usable`, at most `max_attempts` times, re-yielding every event.
    Fills `report` with output / attempts / failures / succeeded. The output
    is captured from each event's state_delta, not re-read from session
    state, so it is independent of when the runner applies deltas."""
    failures: list[str] = []
    output = None
    attempt = 0
    for attempt in range(1, max_attempts + 1):
        output = None
        async for event in agent.run_async(_attempt_context(ctx, agent.name, attempt)):
            delta = event.actions.state_delta if event.actions else None
            if delta and output_key in delta:
                output = delta[output_key]
            if getattr(event, "error_code", None):
                failures.append(f"attempt {attempt}: {event.error_code}")
            yield event
        if is_usable(output):
            break
        failures.append(f"attempt {attempt}: unusable output ({describe_unusable(output)})")
        print(f"[retry] {agent.name} attempt {attempt}/{max_attempts} unusable", flush=True)
        # A retry with identical input is the identical request at temperature
        # 0 (Step 1 evidence: architect answered "I have completed my task..."
        # with no JSON, 3/3). The next attempt's instruction carries what was
        # wrong -- read by instruction providers via retry_notice().
        ctx.session.state[retry_key(agent.name)] = (
            f"Your previous response (attempt {attempt}) was not usable: it did not contain the "
            f"required JSON object for '{output_key}'. It began: {str(output or '')[:200]!r}. "
            "Nothing from that attempt was saved. Respond now with ONLY the complete JSON object."
        )
    ctx.session.state.pop(retry_key(agent.name), None)
    report.update(output=output, attempts=attempt, failures=failures, succeeded=is_usable(output))


class RetryUntilUsable(BaseAgent):
    """Pipeline stage that runs its single sub-agent with bounded retries and
    records the attempt history under `{output_key}_attempts` in state."""

    output_key: str
    max_attempts: int = 3
    is_usable: Callable[[object], bool]

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        report: dict = {}
        # A BLOCKED gate means construction output is discarded anyway --
        # retrying there only burns LLM calls (Step 1 evidence: backend_agent
        # ran 3x on a run whose spec never existed).
        gate = parse_json_object(ctx.session.state.get("gate_result"))
        attempts = 1 if gate.get("status") == "BLOCKED" else self.max_attempts
        async for event in run_with_retries(
            self.sub_agents[0], ctx, self.output_key, self.is_usable, attempts, report
        ):
            yield event
        summary = {k: report[k] for k in ("attempts", "failures", "succeeded")}
        print(f"[retry] {self.sub_agents[0].name} {summary}", flush=True)
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={f"{self.output_key}_attempts": json.dumps(summary)}),
        )


def has_backend_files(raw) -> bool:
    """backend_artifacts is usable when it carries non-empty module + route files."""
    data = parse_json_object(raw)

    def _content(entry) -> str:
        if isinstance(entry, dict):
            return str(entry.get("content", ""))
        return str(entry or "")

    return bool(_content(data.get("module_file")).strip() and _content(data.get("route_file")).strip())


def has_specification(raw) -> bool:
    """specification is usable when it names a module and at least one db column
    (decision_gate BLOCKs the whole run otherwise -- found live:
    posRewardCatalogItem run 2, architect_agent MALFORMED_FUNCTION_CALL)."""
    data = parse_json_object(raw)
    return bool(data.get("module")) and bool((data.get("db") or {}).get("columns"))


def has_frontend_files(raw) -> bool:
    """frontend_artifacts is usable when page + api files carry content
    (Step 1 evidence: factoryRunUsage run, frontend_agent returned nothing
    with no error event at all -- a silent empty turn)."""
    data = parse_json_object(raw)
    return all(str((data.get(k) or {}).get("content", "")).strip() for k in ("page_file", "api_file"))
