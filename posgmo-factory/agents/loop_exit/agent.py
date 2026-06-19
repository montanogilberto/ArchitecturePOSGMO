"""Loop Exit Agent — escalates the LoopAgent when review passes."""
from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from .rules import check_and_exit

_INSTRUCTION = """
You are the Loop Exit Check. Your ONLY job is to call check_and_exit() immediately.
Do not reason or evaluate anything yourself.
Call check_and_exit() and return its result as-is.
"""

loop_exit_agent = Agent(
    name="loop_exit_agent",
    model="gemini-2.5-flash",
    instruction=lambda _ctx: _INSTRUCTION,
    tools=[FunctionTool(func=check_and_exit)],
)
