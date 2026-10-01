"""reviewer_agent — pure Python stage, zero LLM calls.

Was an LLM Agent whose only job was to call run_review(); that turn silently came
back empty / MALFORMED in real runs, so the deterministic logic sometimes
never ran. See agents/deterministic_stage.py (Step 1 evidence).
"""
from agents.deterministic_stage import DeterministicToolStage
from agents.reviewer.rules import run_review

reviewer_agent = DeterministicToolStage(
    name="reviewer_agent",
    description=(
        "Deterministic Python reviewer. Scores database/backend/frontend artifacts 0-100 using a fixed checklist. Pipeline proceeds only when all scores >= 90."
    ),
    fn=run_review,
)
