"""
The Phase 4 expert panel: Product Owner and Architect (proposers) plus a
dynamically-selected set of challengers (debate_v2/panel.py chooses which
of these actually run for a given request).

Each is a real Gemini-backed google.adk.agents.Agent with:
  - output_schema=ExpertOutput  — Gemini's structured-output mode. The raw
    reply IS validated JSON; the orchestrator never has to interpret prose.
    (This is a deliberate departure from the rest of this repo's LLM agents,
    which use output_key with a prompt-described JSON shape but no
    schema-level enforcement — Phase 2 exists partly to prove the stricter
    contract is worth adopting.)
  - include_contents='none'    — no automatic conversation-history
    leakage. Everything an expert is allowed to see is explicitly built
    into its instruction string below; nothing else reaches it. This is
    what makes acceptance criterion #1 (Product Owner and Architect cannot
    see each other's proposal) mechanically true rather than just prompted.
  - Proposers (product_owner, architect) use a single instruction function
    that inspects the blackboard to decide whether it is being invoked to
    PROPOSE (no challenge against it exists yet) or to REBUT (one or more
    challenges naming it already exist) — this is what lets the
    orchestrator re-invoke the SAME agent instance for acceptance
    criterion #4, and now handles MULTIPLE simultaneous challengers
    (Phase 4), not just the single Critic from Phase 2.
  - Challengers (critic, domain_expert, security_expert, ...) all share one
    generic challenge-instruction builder, parameterized by role blurb —
    doc §7's fuller roster is a registry entry, not a bespoke function.
"""
from __future__ import annotations

import json
from typing import Dict

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from debate_v2.expert_output import ExpertOutput

PRODUCT_OWNER = "product_owner"
ARCHITECT = "architect"
CRITIC = "critic"

PROPOSER_ROLE_BLURBS: Dict[str, str] = {
    PRODUCT_OWNER: (
        "You represent the business/user perspective: what capability does the user "
        "actually need, and does an existing workflow already cover it?"
    ),
    ARCHITECT: (
        "You represent technical architecture: should this be a new module, an extension "
        "of an existing one, or an orchestration layer over existing capabilities?"
    ),
}

# doc §7's fuller roster, beyond the always-on core (product_owner, architect,
# critic, domain_expert). debate_v2/panel.py decides which of these actually
# run for a given request.
CHALLENGER_ROLE_BLURBS: Dict[str, str] = {
    CRITIC: (
        "You are the Critic (Senior Engineer / Red-Team role): find the weakest, "
        "riskiest, or least evidence-backed claim and challenge it."
    ),
    "domain_expert": (
        "You are the Domain/Business Expert: validate domain semantics and business "
        "assumptions — does this proposal use the platform's existing terms and data "
        "ownership correctly, or does it invent a parallel concept for something that "
        "already has an owner?"
    ),
    "security_expert": (
        "You are the Security/Authorization Expert: every action must inherit existing "
        "company/branch/user/role authorization. Challenge any proposal that is vague "
        "about tenant isolation, permission checks, or handling of sensitive data."
    ),
    "integration_expert": (
        "You are the Integration Expert: identify existing Push, Chat, WhatsApp, Email, "
        "or payment-gateway capabilities that should be reused. Challenge a proposal "
        "that would duplicate an integration the platform already has."
    ),
    "ux_expert": (
        "You are the UX Expert: challenge the interaction model. A CRUD-heavy screen may "
        "be the wrong shape for this request — say so if a conversational or embedded "
        "flow would serve the user better."
    ),
    "qa_expert": (
        "You are the QA/Validation Expert: attempt to falsify the proposal. Identify "
        "missing acceptance criteria or edge cases the proposal doesn't address."
    ),
    "governance_expert": (
        "You are the Governance/Rules Expert: validate compliance with the project's own "
        "stated rules (e.g. no raw SQL from routes, companyId never hand-authored in a "
        "PRD, existing-system-first). Challenge a proposal that would violate one."
    ),
}


def _context_block(state) -> str:
    verified = json.loads(state.get("context_verified_facts") or "[]")
    assumptions = json.loads(state.get("context_assumptions") or "[]")
    verified_lines = [
        f"  - {f['claim']}" + (f" [source: {f['source']}]" if f.get("source") else "")
        for f in verified
    ] or ["  (none found)"]
    assumption_lines = [f"  - {a['claim']}" for a in assumptions] or ["  (none)"]
    return (
        "VERIFIED FACTS (ground truth — you may cite these as evidence):\n"
        + "\n".join(verified_lines)
        + "\n\nUNVERIFIED ASSUMPTIONS (do NOT cite these as evidence — they may be wrong):\n"
        + "\n".join(assumption_lines)
    )


def _propose_instruction(agent_name: str, role_blurb: str):
    def _instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        request = state.get("request", "")
        return f"""You are the {agent_name} in a software-factory design debate.
{role_blurb}

USER REQUEST: "{request}"

{_context_block(state)}

Propose your initial solution to this request. You do NOT know what any
other expert is proposing — this is an independent, blind proposal meant
to avoid groupthink. Reply ONLY with the required JSON schema. Cite
VERIFIED FACTS by their exact text if you rely on them; never cite an
unverified assumption as if it were fact. Leave `alternative`, `target`,
and `severity` null — those are only used in later rounds."""
    return _instruction


def _rebut_or_propose_instruction(agent_name: str, role_blurb: str):
    """Handles Phase 4's multi-challenger case: an agent may be challenged
    by SEVERAL experts (critic, security_expert, ...) in the same round —
    all of it is bundled into ONE rebuttal instruction, so the agent is
    re-invoked once per round, not once per challenger."""
    propose_fn = _propose_instruction(agent_name, role_blurb)

    def _instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        challenges = json.loads(state.get("challenges") or "[]")
        my_challenges = [c for c in challenges if c.get("target") == agent_name]
        if not my_challenges:
            return propose_fn(ctx)

        proposals = json.loads(state.get("proposals") or "[]")
        my_proposal = next((p for p in proposals if p.get("agent") == agent_name), None)
        request = state.get("request", "")
        challenge_lines = "\n".join(
            f"  From {c['agent']} (severity: {c.get('severity', 'unknown')}):\n"
            f"    \"{c['claim']}\"\n"
            f"    reasoning: {c.get('reasoning_summary', '')}\n"
            f"    evidence cited: {c.get('evidence', [])}"
            for c in my_challenges
        )
        return f"""You are the {agent_name} in a software-factory design debate.
{role_blurb}

USER REQUEST: "{request}"

{_context_block(state)}

YOUR ORIGINAL PROPOSAL: "{my_proposal['claim'] if my_proposal else ''}"

{len(my_challenges)} CHALLENGE(S) were raised against your proposal:
{challenge_lines}

Respond to ALL of these challenges together in a single revised position.
If they change your position, set `alternative` to your REVISED claim
(addressing every challenge above) and explain why in `reasoning_summary`.
If you still believe your original proposal is correct despite ALL of
these challenges, leave `alternative` null and defend it in
`reasoning_summary` — do not concede just to be agreeable. Reply ONLY
with the required JSON schema."""
    return _instruction


def _challenge_instruction_for(role_name: str, role_blurb: str):
    def _instruction(ctx: ReadonlyContext) -> str:
        state = ctx.state
        request = state.get("request", "")
        proposals = json.loads(state.get("proposals") or "[]")
        proposal_lines = "\n".join(
            f"  - [{p['agent']}] \"{p['claim']}\" (confidence {p['confidence']})" for p in proposals
        )
        agent_names = ", ".join(p["agent"] for p in proposals)
        return f"""You are the {role_name} in a software-factory design debate.
{role_blurb}

Your job is to find the weakest, riskiest, or least evidence-backed claim
among the proposals below and challenge it from YOUR specific angle — do
not rubber-stamp agreement, and do not invent a problem outside your area
of responsibility if the proposals are genuinely well-supported.

USER REQUEST: "{request}"

{_context_block(state)}

PROPOSALS ON THE TABLE:
{proposal_lines}

Pick exactly ONE proposal to challenge. Set `target` to the EXACT agent
name from the proposals above (must be one of: {agent_names}). Set
`severity` to "low", "medium", or "high" based on how serious the
disagreement is. Cite VERIFIED FACTS as evidence if you have them — never
invent evidence you were not given. Reply ONLY with the required JSON
schema."""
    return _instruction


def build_product_owner_agent() -> Agent:
    return Agent(
        name=PRODUCT_OWNER,
        description="Discovers business intent; argues from user value and existing-workflow fit.",
        model="gemini-2.5-flash",
        instruction=_rebut_or_propose_instruction(PRODUCT_OWNER, PROPOSER_ROLE_BLURBS[PRODUCT_OWNER]),
        output_schema=ExpertOutput,
        include_contents="none",
        generate_content_config={"temperature": 0.4},
    )


def build_architect_agent() -> Agent:
    return Agent(
        name=ARCHITECT,
        description="Proposes technical architecture; argues from reuse and system boundaries.",
        model="gemini-2.5-flash",
        instruction=_rebut_or_propose_instruction(ARCHITECT, PROPOSER_ROLE_BLURBS[ARCHITECT]),
        output_schema=ExpertOutput,
        include_contents="none",
        generate_content_config={"temperature": 0.4},
    )


def build_challenger_agent(role_name: str) -> Agent:
    """Generic factory for any entry in CHALLENGER_ROLE_BLURBS — this is
    what makes the panel data-driven instead of one bespoke function per
    expert (doc §7's roster is a dict entry, not new code)."""
    if role_name not in CHALLENGER_ROLE_BLURBS:
        raise ValueError(f"Unknown challenger role: {role_name!r}")
    return Agent(
        name=role_name,
        description=f"Cross-examines proposals from the {role_name} angle.",
        model="gemini-2.5-flash",
        instruction=_challenge_instruction_for(role_name, CHALLENGER_ROLE_BLURBS[role_name]),
        output_schema=ExpertOutput,
        include_contents="none",
        generate_content_config={"temperature": 0.1},
    )


def build_critic_agent() -> Agent:
    """Kept as a named convenience wrapper — build_challenger_agent(CRITIC)
    is equivalent and is what debate_v2/panel.py actually uses."""
    return build_challenger_agent(CRITIC)
