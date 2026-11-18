"""
Agent output that is valid JSON except for raw control characters inside its
strings is re-encoded, not retried. Found 2026-11-07 (prd_voiceCall):
backend_agent wrote its 47 KB module with literal newlines inside the JSON
string, 3/3 attempts -> no backend artifact -> review failed -> no PR.
"""
import asyncio
import json
from types import SimpleNamespace

from google.adk.events import Event, EventActions

from agents.retry import normalize_json_text, run_with_retries

BROKEN = '{"module_file": {"path": "modules/x.py", "content": "def f():\n\treturn 1\n"}}'


def test_raw_newlines_inside_strings_are_re_encoded():
    fixed = normalize_json_text(BROKEN)
    assert json.loads(fixed)["module_file"]["content"] == "def f():\n\treturn 1\n"


def test_fenced_output_is_also_re_encoded():
    assert json.loads(normalize_json_text(f"```json\n{BROKEN}\n```"))["module_file"]["path"] == "modules/x.py"


def test_strict_json_and_non_json_are_left_alone():
    assert normalize_json_text('{"a": "b\\nc"}') is None          # already strict
    assert normalize_json_text("I have completed the task") is None
    assert normalize_json_text('{"a": ') is None                   # truly broken: still a retry
    assert normalize_json_text("[1, 2]") is None                   # not an object
    assert normalize_json_text("") is None and normalize_json_text(None) is None


class _FakeAgent:
    name = "backend_agent"

    def __init__(self):
        self.calls = 0

    async def run_async(self, ctx):
        self.calls += 1
        yield Event(author=self.name, actions=EventActions(state_delta={"backend_artifacts": BROKEN}))


def test_retry_loop_uses_the_re_encoded_output_and_does_not_retry():
    agent, report, events = _FakeAgent(), {}, []
    ctx = SimpleNamespace(session=SimpleNamespace(state={}))

    async def go():
        async for e in run_with_retries(agent, ctx, "backend_artifacts",
                                        lambda raw: bool(raw) and "modules/x.py" in raw and json.loads(raw) is not None,
                                        3, report):
            events.append(e)
    asyncio.run(go())

    assert agent.calls == 1 and report["succeeded"] is True
    written = events[-1].actions.state_delta["backend_artifacts"]
    assert json.loads(written)["module_file"]["content"].startswith("def f():")
