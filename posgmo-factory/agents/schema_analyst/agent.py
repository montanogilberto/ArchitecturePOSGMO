"""Schema Analyst Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from agents.schema_analyst.prompt import INSTRUCTION
from agents.schema_analyst.rules import analyze_database_schema

schema_analyst_agent = Agent(
    name="schema_analyst_agent",
    description=(
        "Connects to the live SQL Server, reads all tables/columns/FKs/indexes, "
        "detects conflicts, validates FK targets, and stores a db_context for the Architect."
    ),
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    tools=[FunctionTool(func=analyze_database_schema)],
    output_key="schema_analysis",
)