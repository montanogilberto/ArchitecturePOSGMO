"""fixer_agent — pure Python stage, zero LLM calls.

Was an LLM Agent whose only job was to call run_all_fixers(); that turn silently came
back empty / MALFORMED in real runs, so the deterministic logic sometimes
never ran. See agents/deterministic_stage.py (Step 1 evidence).
"""
from agents.deterministic_stage import DeterministicToolStage
from agents.fixer.rules import run_all_fixers

fixer_agent = DeterministicToolStage(
    name="fixer_agent",
    description=(
        "Deterministic post-generation fixer. Corrects SQL, Python, and TypeScript artifacts for the most common LLM generation violations — no LLM involved."
    ),
    fn=run_all_fixers,
)
