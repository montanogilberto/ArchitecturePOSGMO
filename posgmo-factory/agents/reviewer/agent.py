"""Reviewer Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.reviewer.prompt import _INSTRUCTION
from agents.reviewer.rules import run_review

reviewer_agent = Agent(
    name="reviewer_agent",
    description=(
        "Deterministic Python reviewer. Scores database/backend/frontend artifacts "
        "0-100 using a fixed checklist. Pipeline proceeds only when all scores >= 90."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: _INSTRUCTION,
    tools=[FunctionTool(func=run_review)],
    # output_key omitted — run_review() writes review_result directly to
    # tool_context.state. Adding output_key would overwrite it with LLM text.
)