"""
Phase 6 — the dynamic Product Owner questionnaire (doc §3).

Doc §3: "The Product Owner agent should investigate what the user is
actually trying to accomplish. It should generate an intelligent,
domain-specific questionnaire instead of asking a generic fixed form...
Questions already answered by repository knowledge or project rules should
not be repeated."

This runs as its own INTAKE phase, right after ANALYZE (Phase 2/3's
ContextAgent) and before PROPOSE. It is deliberately positioned AFTER
evidence-gathering, not before: the whole point of "don't repeat questions
already answered by repository knowledge" is that this step can see the
verified_facts and assumptions already gathered and must only ask about
what is STILL genuinely unclear after that evidence — an intake step that
ran first would have nothing to check its questions against.

If the request is judged ambiguous, the orchestrator short-circuits: it
escalates for human clarification (reusing the same needs_user_input /
escalation_reason mechanism Phase 2/5 already built for unresolved
conflicts) INSTEAD OF spending a full debate on a request nobody has
confirmed the meaning of yet. This is a correctness gate, not a cost
optimization: doc §3's point is that a request like "create a new module
for Rewards" is only a starting point, and proposing solutions to an
unclarified request risks answering the wrong question well.
"""
from __future__ import annotations

import json
from typing import List, Optional

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from pydantic import BaseModel, Field

INTAKE_AGENT = "intake_agent"


class IntakeOutput(BaseModel):
    is_ambiguous: bool = Field(
        description="True only if the request's INTENT is genuinely unclear even after "
                    "the verified facts and assumptions below — not merely 'this will take "
                    "judgment to design'. A well-evidenced request should be False."
    )
    reasoning: str = Field(description="1-3 sentences on why intent is or isn't already clear.")
    questions: List[str] = Field(
        default_factory=list,
        description="ONLY if is_ambiguous: 1-4 short, specific clarifying questions. Never "
                    "ask something the verified facts already answer.",
    )


def _intake_instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    request = state.get("request", "")
    verified = json.loads(state.get("context_verified_facts") or "[]")
    assumptions = json.loads(state.get("context_assumptions") or "[]")
    verified_lines = "\n".join(f"  - {f['claim']}" for f in verified) or "  (none found)"
    assumption_lines = "\n".join(f"  - {a['claim']}" for a in assumptions) or "  (none)"
    return f"""You are the Product Owner running intake on a new feature request, before any
technical debate begins (doc principle: user intent must go deeper than the
initial request — a one-line request is only a starting point).

USER REQUEST: "{request}"

VERIFIED FACTS already gathered from the repository (do NOT ask about
anything this already answers):
{verified_lines}

UNVERIFIED ASSUMPTIONS (these MAY be worth turning into a clarifying
question, since they are explicitly unconfirmed):
{assumption_lines}

Decide: is the request's INTENT genuinely ambiguous even after the
evidence above, such that two reasonable engineers could design
completely different things from it? Or is there enough here (explicit
scope, an existing well-specified design, clear terminology) to proceed
straight to a technical debate?

If ambiguous, ask 1-4 SHORT, SPECIFIC questions that resolve exactly the
ambiguity — never a generic fixed-form question, and never one the
verified facts already answer. Reply ONLY with the required JSON schema."""


def build_intake_agent() -> Agent:
    return Agent(
        name=INTAKE_AGENT,
        description="Decides whether the request's intent needs human clarification before debating it.",
        model="gemini-2.5-flash",
        instruction=_intake_instruction,
        output_schema=IntakeOutput,
        include_contents="none",
        generate_content_config={"temperature": 0.2},
    )
