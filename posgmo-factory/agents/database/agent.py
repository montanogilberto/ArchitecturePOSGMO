"""Database Agent definition."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.mcp_tools import get_mcp_toolset
from agents.database.prompt import INSTRUCTION
from agents.database.rules import execute_sql_on_server

database_agent = Agent(
    name="database_agent",
    description=(
        "Generates CREATE TABLE and all stored procedures for a POS GMO module, "
        "then executes them directly against SQL Server."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    tools=[get_mcp_toolset(), FunctionTool(func=execute_sql_on_server)],
    output_key="database_artifacts",
)