"""Design Consistency Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.design_consistency.prompt import INSTRUCTION
from agents.design_consistency.rules import fetch_design_reference

design_consistency_agent = Agent(
    name="design_consistency_agent",
    description=(
        "Fetches real existing pages from the frontend GitHub repo, extracts "
        "exact design patterns (component structure, CSS naming, modal style, "
        "API call patterns), and stores a design_context for the Frontend Agent."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[FunctionTool(func=fetch_design_reference)],
    output_key="design_brief",
)