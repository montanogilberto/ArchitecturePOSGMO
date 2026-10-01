"""loop_exit_agent — pure Python stage, zero LLM calls.

Was an LLM Agent whose only job was to call check_and_exit(); that turn silently came
back empty / MALFORMED in real runs, so the deterministic logic sometimes
never ran. See agents/deterministic_stage.py (Step 1 evidence).
"""
from agents.deterministic_stage import DeterministicToolStage
from agents.loop_exit.rules import check_and_exit

loop_exit_agent = DeterministicToolStage(
    name="loop_exit_agent",
    description=(
        "Escalates the review/fix LoopAgent when review passed or the iteration limit is reached."
    ),
    fn=check_and_exit,
)
