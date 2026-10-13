"""Business Intake agents: understanding (audio/text -> NormalizedNeed) and
analysis (need + evidence -> BusinessAnalysis). Neither has tools: all
grounding comes from evidence.gather_business_evidence(), which runs in
between as plain Python (see runner.py)."""
import os

from google.adk.agents import Agent

from agents.business_intake.prompt import ANALYST_INSTRUCTION, UNDERSTANDING_INSTRUCTION
from agents.business_intake.schema import BusinessAnalysis, NormalizedNeed

# Audio input needs a model with native audio understanding; gemini-2.5-flash has it.
INTAKE_MODEL = os.getenv("FACTORY_INTAKE_MODEL", "gemini-2.5-flash")

understanding_agent = Agent(
    name="intake_understanding_agent",
    description="Transcribes a business owner's audio note (or reads their text) and restates the need in English with domain terms.",
    model=INTAKE_MODEL,
    instruction=UNDERSTANDING_INSTRUCTION,
    output_schema=NormalizedNeed,
    output_key="intake_need",
    generate_content_config={"temperature": 0},
)

analyst_agent = Agent(
    name="intake_analyst_agent",
    description="Turns a business need plus deterministic repository evidence into a reuse / extend / create analysis.",
    model=INTAKE_MODEL,
    instruction=ANALYST_INSTRUCTION,
    output_schema=BusinessAnalysis,
    output_key="intake_analysis",
    generate_content_config={"temperature": 0.2},
)
