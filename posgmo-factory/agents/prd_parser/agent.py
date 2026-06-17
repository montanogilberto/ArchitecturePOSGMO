"""PRD Parser Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from agents.prd_parser.prompt import INSTRUCTION
from agents.prd_parser.rules import store_prd_context

prd_parser_agent = Agent(
    name="prd_parser_agent",
    description=(
        "Parses the incoming PRD JSON, extracts module naming variables, "
        "and writes them to session state so all downstream agents can "
        "use {module}, {plural}, {Module}, etc. in their instructions."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[FunctionTool(func=store_prd_context)],
    output_key="prd_context",
)