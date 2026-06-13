"""Fixer Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.fixer.prompt import _INSTRUCTION
from agents.fixer.rules import run_all_fixers

fixer_agent = Agent(
    name="fixer_agent",
    description=(
        "Deterministic post-generation fixer. Corrects SQL, Python, and TypeScript "
        "artifacts for the most common LLM generation violations — no LLM involved."
    ),
    model="gemini-2.5-flash",
    instruction=_INSTRUCTION,
    tools=[FunctionTool(func=run_all_fixers)],
    # output_key omitted — run_all_fixers() writes corrected artifacts directly to
    # tool_context.state. Adding output_key would overwrite artifacts with LLM text.
)