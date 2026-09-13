"""Proves acceptance criterion #1 mechanically: Product Owner and Architect
cannot see each other's proposal before proposing. No LLM calls — this
inspects the instruction TEXT that would be sent to the model, and the
agent config that blocks conversation-history leakage."""

from debate_v2.experts import (
    ARCHITECT, PRODUCT_OWNER, build_architect_agent, build_critic_agent,
    build_product_owner_agent, _propose_instruction, _rebut_or_propose_instruction,
)


class _FakeReadonlyContext:
    """Minimal stand-in for google.adk.agents.readonly_context.ReadonlyContext —
    the instruction functions only touch `.state`."""
    def __init__(self, state: dict):
        self.state = state


def test_history_inclusion_is_disabled_for_all_three_experts():
    for build in (build_product_owner_agent, build_architect_agent, build_critic_agent):
        agent = build()
        assert agent.include_contents == "none", (
            f"{agent.name} must not receive default conversation history — "
            f"that would leak sibling proposals before this agent proposes."
        )


def test_experts_use_structured_output_not_free_prose():
    from debate_v2.expert_output import ExpertOutput
    for build in (build_product_owner_agent, build_architect_agent, build_critic_agent):
        assert build().output_schema is ExpertOutput


def test_propose_instruction_never_reads_the_proposals_key():
    """Plant a distinctive marker inside a fake sibling proposal already on
    the blackboard, and prove the PROPOSE-phase instruction text never
    contains it — the instruction builder must not read `state['proposals']`
    at all when building the blind, independent PROPOSE prompt."""
    marker = "SIBLING_SECRET_MARKER_should_never_leak"
    state = {
        "request": "create a new module for rewards",
        "context_verified_facts": "[]",
        "context_assumptions": "[]",
        "proposals": (
            '[{"agent": "architect", "claim": "' + marker + '", '
            '"confidence": 0.9, "evidence": [], "reasoning_summary": "x", "risks": []}]'
        ),
        "challenges": "[]",
    }
    ctx = _FakeReadonlyContext(state)

    instr = _propose_instruction(PRODUCT_OWNER, "role blurb")(ctx)
    assert marker not in instr


def test_rebut_or_propose_instruction_proposes_blind_when_no_challenge_exists():
    """Same guarantee, but through the actual function wired into the real
    agents (build_product_owner_agent/build_architect_agent use
    _rebut_or_propose_instruction, which falls back to the blind propose
    path when no challenge targets this agent yet)."""
    marker = "SIBLING_SECRET_MARKER_should_never_leak"
    state = {
        "request": "create a new module for rewards",
        "context_verified_facts": "[]",
        "context_assumptions": "[]",
        "proposals": (
            '[{"agent": "architect", "claim": "' + marker + '", '
            '"confidence": 0.9, "evidence": [], "reasoning_summary": "x", "risks": []}]'
        ),
        "challenges": "[]",  # no challenge yet -> must stay in blind PROPOSE mode
    }
    ctx = _FakeReadonlyContext(state)

    instr = _rebut_or_propose_instruction(PRODUCT_OWNER, "role blurb")(ctx)
    assert marker not in instr
    assert "independent, blind proposal" in instr


def test_rebut_instruction_only_activates_once_a_challenge_names_this_agent():
    """The flip side: once a challenge exists targeting this agent, the SAME
    instruction function must switch into REBUT mode and IS allowed to see
    the challenge (that's the whole point of criterion #4)."""
    state = {
        "request": "create a new module for rewards",
        "context_verified_facts": "[]",
        "context_assumptions": "[]",
        "proposals": (
            '[{"agent": "architect", "claim": "original architect claim", '
            '"confidence": 0.9, "evidence": [], "reasoning_summary": "x", "risks": []}]'
        ),
        "challenges": (
            '[{"agent": "critic", "target": "architect", "claim": "CHALLENGE_TEXT", '
            '"reasoning_summary": "why", "evidence": [], "severity": "high", "confidence": 0.8}]'
        ),
    }
    ctx = _FakeReadonlyContext(state)

    instr = _rebut_or_propose_instruction(ARCHITECT, "role blurb")(ctx)
    assert "CHALLENGE_TEXT" in instr
    assert "original architect claim" in instr

    # product_owner was NOT targeted — must still be in blind propose mode.
    po_instr = _rebut_or_propose_instruction(PRODUCT_OWNER, "role blurb")(ctx)
    assert "CHALLENGE_TEXT" not in po_instr
