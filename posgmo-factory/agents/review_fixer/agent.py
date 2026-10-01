"""review_fixer_agent — pure Python stage, zero LLM calls.

Was an LLM Agent whose only job was to call apply_review_fixes(); that turn silently came
back empty / MALFORMED in real runs, so the deterministic logic sometimes
never ran. See agents/deterministic_stage.py (Step 1 evidence).
"""
from agents.deterministic_stage import DeterministicToolStage
from agents.review_fixer.rules import apply_review_fixes

review_fixer_agent = DeterministicToolStage(
    name="review_fixer_agent",
    description=(
        "Applies deterministic fixes for the reviewer's findings to the artifacts in state."
    ),
    fn=apply_review_fixes,
)
