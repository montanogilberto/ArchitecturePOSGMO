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
    # include_contents='none': apply_review_fixes takes no arguments and reads
    # review_result/frontend_artifacts/backend_artifacts directly from
    # tool_context.state, so this agent needs no conversation history to do
    # its job. Experiment 2 caught this agent skipping its mandatory tool
    # call and writing a prose summary instead once the accumulated context
    # got long -- see agent_contracts.py, which now checks for exactly that.
    include_contents="none",
)
