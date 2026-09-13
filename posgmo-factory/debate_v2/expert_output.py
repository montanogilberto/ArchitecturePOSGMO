"""
Raw LLM output contract for Phase 2 experts (Product Owner / Architect / Critic).

Deliberately NARROWER than debate_schema.DebateMessage: an expert is only
trusted to supply the *content* of its claim, never the message envelope
(round/phase/agent/type). The orchestrator (chairperson) assigns the
envelope fields itself when it wraps an ExpertOutput into a DebateMessage —
this is what makes "the expert cannot impersonate another agent or spoof
its own round/phase, and the orchestrator cannot manufacture a claim"
enforceable in code, not just by prompt instruction (see debate_v2/orchestrator.py::_wrap).

Passed as google.adk.agents.Agent(output_schema=ExpertOutput, ...) so Gemini's
structured-output mode returns validated JSON directly — the model's reply
IS the data, not prose an orchestrator has to interpret.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ExpertOutput(BaseModel):
    claim: str = Field(
        description="The proposal, challenge, or rebuttal statement itself. One or two sentences."
    )
    reasoning_summary: str = Field(
        description="Concise reasoning for the claim — 1-3 sentences. Never raw chain-of-thought."
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Citations to the VERIFIED FACTS you were given (quote them). "
                    "Do not cite anything not present in the verified facts you were shown.",
    )
    risks: List[str] = Field(default_factory=list)
    alternative: Optional[str] = Field(
        default=None,
        description="ONLY for a rebuttal: your REVISED claim if the challenge changed your "
                    "position. Leave null if you are defending your original claim unchanged.",
    )
    target: Optional[str] = Field(
        default=None,
        description="ONLY for a challenge: the exact agent name (from the proposals you were "
                    "shown) whose claim you are disputing.",
    )
    severity: Optional[str] = Field(
        default=None,
        description="ONLY for a challenge: 'low', 'medium', or 'high' — how serious is this disagreement?",
    )
    confidence: float = Field(ge=0.0, le=1.0)
