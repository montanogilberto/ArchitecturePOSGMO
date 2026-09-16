"""Acceptance criterion #10: Phase 2 must not generate code or modify the
existing factory pipeline. Static check — no file under debate_v2/ imports
from the production `agents` package (which is what agents/agent.py
assembles into root_agent) or from orchestrator.py/pr_agent/etc."""

import re
from pathlib import Path

_DEBATE_V2_DIR = Path(__file__).parent.parent / "debate_v2"

_FORBIDDEN_IMPORT_PATTERNS = [
    re.compile(r"^\s*from agents\b"),
    re.compile(r"^\s*import agents\b"),
    re.compile(r"^\s*from orchestrator\b"),
    re.compile(r"^\s*import orchestrator\b"),
]


def test_debate_v2_never_imports_the_production_factory():
    offending = []
    for py_file in _DEBATE_V2_DIR.glob("*.py"):
        for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
            if any(p.match(line) for p in _FORBIDDEN_IMPORT_PATTERNS):
                offending.append(f"{py_file.name}:{lineno}: {line.strip()}")
    assert not offending, f"debate_v2 must not import production factory code:\n" + "\n".join(offending)


def test_root_agent_pipeline_is_unchanged_by_debate_v2():
    """agents/agent.py's assembled pipeline still has exactly these stages —
    debate_v2 added nothing to it. (database_executor_agent was added
    2026-09-16 as a legitimate, deliberate factory change — a deterministic,
    zero-LLM step that executes database_agent's SQL, replacing a tool call
    that used to be database_agent's own responsibility. See
    docs/experiment1-leadCapture-evaluation.md for why. Nothing here comes
    from debate_v2 — see the import-boundary test above for that guarantee.)"""
    from agents.agent import root_agent
    stage_names = [a.name for a in root_agent.sub_agents]
    assert stage_names == [
        "host_architect_agent", "prd_parser_agent", "prd_enricher_agent",
        "schema_analyst_agent", "architect_agent", "decision_gate_agent",
        "generation_stage", "database_executor_agent", "fixer_agent", "frontend_agent",
        "review_fix_loop", "pr_agent",
    ]
