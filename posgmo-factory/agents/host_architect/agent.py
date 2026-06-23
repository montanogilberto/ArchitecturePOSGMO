"""
Host Architect Agent

First agent in the pipeline. Reads the user's free-text intent and produces an
AppProfileJSON that declares which application profile and modules to enable.

All downstream agents read `session.state["app_profile"]` to scope their work.
"""
from google.adk.agents import Agent
from agents.host_architect.prompt import INSTRUCTION

host_architect_agent = Agent(
    name="host_architect_agent",
    description=(
        "Detects the user's intended application type from natural language "
        "(POS, Loans, Vending, Custom) and emits an AppProfileJSON that enables "
        "or disables specific modules for the entire pipeline."
    ),
    model="gemini-2.5-flash",
    instruction=lambda _ctx: INSTRUCTION,
    output_key="app_profile",
    generate_content_config={"temperature": 0},
)
