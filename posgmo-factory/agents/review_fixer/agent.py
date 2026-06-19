"""Review Fixer Agent — applies targeted fixes based on reviewer error list."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from agents.mcp_tools import get_mcp_toolset
from .prompt import INSTRUCTION
from .rules import apply_review_fixes

review_fixer_agent = Agent(
    name="review_fixer_agent",
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[
        get_mcp_toolset(),
        FunctionTool(func=apply_review_fixes),
    ],
    output_key="review_fixer_result",
)
