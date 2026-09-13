"""
Debate Orchestrator — the chairperson.

Runs exactly:
    FRAME -> ANALYZE -> PROPOSE -> CHALLENGE -> REBUT -> COMPARE -> DECIDE

Phase 2 proved this with a fixed 3-expert panel (product_owner, architect,
critic). Phase 4 generalizes CHALLENGE/REBUT to a DYNAMIC set of challengers
selected per-request by debate_v2/panel.py (doc §6/§7's fuller roster —
domain_expert always, plus security/integration/ux/qa/governance when the
request's keywords warrant it) — but PROPOSE stays exactly two proposers
(product_owner, architect), since that's the blind-independent-proposal
guarantee acceptance criterion #1 depends on and Phase 2 already proved.

Chairperson constraint (acceptance criterion #6): every `claim` that ends
up in `decisions` / `rejected_alternatives` is copied verbatim from a
DebateMessage already sitting on the blackboard. _wrap() is the only place
an ExpertOutput becomes a DebateMessage, and compute_decision_or_escalation()
is the only place a Decision/RejectedAlternative gets built — neither
function accepts a free-text claim parameter; both can only select among
fields already present in `state`.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Dict, List, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from debate_schema import (
    Conflict,
    DebateMessage,
    DebatePhase,
    Decision,
    MessageType,
    Participant,
    RejectedAlternative,
    ScoreCard,
    ScoreDimension,
    Severity,
    append_to_blackboard,
    read_blackboard,
    seed_blackboard_state,
)
from debate_v2.context import ContextAgent
from debate_v2.expert_output import ExpertOutput
from debate_v2.intake import IntakeOutput
from debate_v2.experts import ARCHITECT, PRODUCT_OWNER


def _wrap(
    expert_output: ExpertOutput, *, round_: int, phase: DebatePhase, agent: str,
    type_: MessageType, target: Optional[str] = None,
) -> DebateMessage:
    """The ONLY place an ExpertOutput becomes a DebateMessage. Every content
    field (claim/evidence/reasoning_summary/risks/alternative/confidence) is
    copied straight from the model's structured output — this function adds
    only the envelope (round/phase/agent/type/target), never content."""
    return DebateMessage(
        round=round_, phase=phase, agent=agent, type=type_,
        target=target or expert_output.target,
        claim=expert_output.claim,
        evidence=expert_output.evidence,
        reasoning_summary=expert_output.reasoning_summary,
        risks=expert_output.risks,
        alternative=expert_output.alternative,
        confidence=expert_output.confidence,
    )


def _heuristic_scorecard(candidate: dict) -> ScoreCard:
    """Phase 5 (doc §13): a transparency record for the debate, NOT a
    rigorous multi-dimension rubric — each dimension is a coarse heuristic
    over signals already on the blackboard (confidence, evidence volume).
    The actual winner is still chosen by confidence (proven in Phase 2/4
    testing); this exists so the final record shows more than one scalar,
    matching doc §13's "transparent scorecard" intent. A real rubric would
    need either a dedicated scoring LLM pass or hand-authored per-dimension
    criteria — a reasonable next refinement once this mechanism is proven."""
    confidence10 = round(candidate["confidence"] * 10, 1)
    evidence_signal = round(min(10.0, len(candidate["evidence"]) * 2.0), 1)
    scores = {
        ScoreDimension.reuse: evidence_signal,
        ScoreDimension.business_fit: confidence10,
        ScoreDimension.maintainability: confidence10,
        ScoreDimension.testability: evidence_signal,
    }
    return ScoreCard(
        subject=candidate["claim"], scores=scores,
        total=round(sum(scores.values()) / len(scores), 1),
        notes="Heuristic proxy (confidence + evidence volume) — not a full rubric.",
    )


def compute_decision_or_escalation(state: dict) -> Dict[str, str]:
    """Pure function: COMPARE + DECIDE. No LLM call, no I/O — directly
    unit-testable. Generalizes over however many challengers ran (Phase 4)
    and however many of {product_owner, architect} were actually
    challenged. NEVER invents a claim string: every `selected_claim` and
    `RejectedAlternative.claim` is copied from a DebateMessage.claim (or
    .alternative) already present in `state`.
    """
    proposals = read_blackboard(state, "proposals")
    challenges = read_blackboard(state, "challenges")
    rebuttals = read_blackboard(state, "rebuttals")
    conflicts = read_blackboard(state, "conflicts")

    if not challenges or not rebuttals:
        return {}

    rebuttal_by_target = {r.agent: r for r in rebuttals}
    conflict_by_pair = {tuple(sorted(c.participants)): c for c in conflicts}

    # Any challenge whose target's rebuttal did NOT offer a revised
    # `alternative` is unresolved. A high-severity unresolved challenge
    # blocks automatic convergence (acceptance criterion #7) — checked
    # across ALL challengers this round, not just the last one to speak.
    unresolved_high: List[DebateMessage] = []
    for ch in challenges:
        pair = tuple(sorted([ch.agent, ch.target or ""]))
        conflict = conflict_by_pair.get(pair)
        severity = conflict.severity if conflict else Severity.medium
        rebuttal = rebuttal_by_target.get(ch.target)
        resolved = bool(rebuttal and rebuttal.alternative is not None)
        if conflict and resolved:
            conflict.status = "resolved"
            conflict.resolution = rebuttal.alternative
        if severity == Severity.high and not resolved:
            unresolved_high.append(ch)

    if unresolved_high:
        reasons = "; ".join(
            f'{c.agent} vs {c.target}: "{c.claim}"' for c in unresolved_high
        )
        return {
            "conflicts": json.dumps([c.model_dump(mode="json") for c in conflicts]),
            "status": json.dumps({
                "round": 4, "phase": DebatePhase.decide.value, "confidence": 0.0,
                "needs_user_input": True,
                "escalation_reason": f"High-severity conflict(s) not resolved by rebuttal: {reasons}",
            }),
        }

    # COMPARE: each proposer's FINAL position — post-rebuttal if they were
    # challenged, otherwise their untouched original — picked by actual
    # confidence, never an automatic preference for whoever spoke last.
    candidates = []
    for p in proposals:
        rebuttal = rebuttal_by_target.get(p.agent)
        if rebuttal:
            candidates.append({
                "claim": rebuttal.alternative or rebuttal.claim, "agent": p.agent,
                "evidence": rebuttal.evidence, "confidence": rebuttal.confidence,
                "rationale": rebuttal.reasoning_summary or "",
                "original_claim": p.claim, "changed": rebuttal.alternative is not None,
            })
        else:
            candidates.append({
                "claim": p.claim, "agent": p.agent,
                "evidence": p.evidence, "confidence": p.confidence,
                "rationale": p.reasoning_summary or "",
                "original_claim": p.claim, "changed": False,
            })
    winner = max(candidates, key=lambda c: c["confidence"])

    decision = Decision(
        round=4, selected_claim=winner["claim"], rationale=winner["rationale"],
        evidence=winner["evidence"], confidence=winner["confidence"], decided_by="debate",
    )

    rejected_by_claim: Dict[str, RejectedAlternative] = {}
    for c in candidates:
        # A proposer's ORIGINAL pre-rebuttal claim, if they revised it —
        # superseded by their own rebuttal regardless of who wins overall.
        if c["changed"] and c["original_claim"] != winner["claim"]:
            rejected_by_claim[c["original_claim"]] = RejectedAlternative(
                claim=c["original_claim"], proposed_by=c["agent"],
                reason=f"Superseded by {c['agent']}'s own rebuttal after challenge(s).",
                evidence=[],
            )
        # Whichever candidate did NOT win the actual confidence comparison.
        if c["claim"] != winner["claim"] and c["claim"] not in rejected_by_claim:
            rejected_by_claim[c["claim"]] = RejectedAlternative(
                claim=c["claim"], proposed_by=c["agent"],
                reason=(f"Lower-confidence alternative not selected "
                        f"({c['confidence']:.2f} vs {winner['confidence']:.2f})."),
                evidence=c["evidence"],
            )
    rejected = list(rejected_by_claim.values())
    scorecards = [_heuristic_scorecard(c) for c in candidates]

    return {
        "decisions": json.dumps([decision.model_dump(mode="json")]),
        "rejected_alternatives": json.dumps([r.model_dump(mode="json") for r in rejected]),
        "conflicts": json.dumps([c.model_dump(mode="json") for c in conflicts]),
        "scores": json.dumps([s.model_dump(mode="json") for s in scorecards]),
        "status": json.dumps({
            "round": 4, "phase": DebatePhase.decide.value,
            "confidence": winner["confidence"], "needs_user_input": False,
            "escalation_reason": None,
        }),
    }


async def _speak(agent: BaseAgent, ctx: InvocationContext, capture: dict) -> AsyncGenerator[Event, None]:
    """Re-yields every event from `agent` (so the Runner applies state
    deltas as usual) while capturing the last non-empty text part — the
    structured-output JSON the orchestrator will validate as ExpertOutput."""
    async for event in agent.run_async(ctx):
        yield event
        if event.content and event.content.parts:
            text = "".join(
                p.text for p in event.content.parts if p.text and not getattr(p, "thought", False)
            )
            if text.strip():
                capture["text"] = text


class DebateOrchestratorAgent(BaseAgent):
    """Chairperson: selects who speaks, assembles context, records the
    decision. Never authors a claim of its own — see module docstring.

    sub_agents must be: [context_agent, intake_agent, product_owner, architect,
    *challengers] where *challengers is whatever debate_v2/panel.py selected
    for this request (built via debate_v2.experts.build_challenger_agent).
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        context_agent, intake_agent, product_owner, architect, *challengers = self.sub_agents
        proposer_by_name = {PRODUCT_OWNER: product_owner, ARCHITECT: architect}
        state = ctx.session.state

        # FRAME — procedural setup only. No expert claim authored here.
        seed = seed_blackboard_state()
        seed["participants"] = json.dumps([
            Participant(agent=PRODUCT_OWNER, role="product_owner").model_dump(mode="json"),
            Participant(agent=ARCHITECT, role="architect").model_dump(mode="json"),
            *[Participant(agent=c.name, role=c.name).model_dump(mode="json") for c in challengers],
        ])
        print(f"[orchestrator] FRAME — panel: product_owner, architect, "
              f"{', '.join(c.name for c in challengers)}", flush=True)
        yield Event(author=self.name, actions=EventActions(state_delta=seed))

        # ANALYZE — deterministic evidence gathering, before any expert speaks.
        print("[orchestrator] ANALYZE", flush=True)
        async for event in context_agent.run_async(ctx):
            yield event

        # INTAKE (Phase 6, doc §3) — decide whether the request's intent is
        # clear enough to debate, now that evidence exists to check against.
        # If not, escalate for human clarification INSTEAD OF debating.
        print("[orchestrator] INTAKE", flush=True)
        cap: dict = {}
        async for event in _speak(intake_agent, ctx, cap):
            yield event
        intake_output = IntakeOutput.model_validate_json(cap["text"])
        if intake_output.is_ambiguous:
            print(f"[orchestrator] INTAKE escalated — {len(intake_output.questions)} question(s)", flush=True)
            yield Event(author=self.name, actions=EventActions(state_delta={
                "status": json.dumps({
                    "round": 0, "phase": DebatePhase.frame.value, "confidence": 0.0,
                    "needs_user_input": True,
                    "escalation_reason": intake_output.reasoning,
                    "open_questions": intake_output.questions,
                }),
            }))
            yield Event(author=self.name, actions=EventActions(escalate=True))
            return

        # PROPOSE — product_owner and architect run BLIND to each other.
        # (Enforced by include_contents='none' plus each instruction builder
        # reading only request+context, never the `proposals` key.)
        for name, agent in proposer_by_name.items():
            print(f"[orchestrator] PROPOSE ({name})", flush=True)
            cap: dict = {}
            async for event in _speak(agent, ctx, cap):
                yield event
            output = ExpertOutput.model_validate_json(cap["text"])
            msg = _wrap(output, round_=1, phase=DebatePhase.propose, agent=name, type_=MessageType.proposal)
            yield Event(author=self.name, actions=EventActions(
                state_delta={"proposals": append_to_blackboard(state, "proposals", msg)}
            ))

        # CHALLENGE — every selected challenger runs independently, each
        # seeing both proposals + context but NOT each other's challenge
        # (include_contents='none' + each instruction only reads `proposals`).
        challenged_targets: set = set()
        for challenger in challengers:
            print(f"[orchestrator] CHALLENGE ({challenger.name})", flush=True)
            cap = {}
            async for event in _speak(challenger, ctx, cap):
                yield event
            output = ExpertOutput.model_validate_json(cap["text"])
            if output.target not in proposer_by_name:
                raise ValueError(
                    f"{challenger.name} returned an invalid target {output.target!r}; "
                    f"must be one of {list(proposer_by_name)}"
                )
            challenge_msg = _wrap(output, round_=2, phase=DebatePhase.challenge,
                                   agent=challenger.name, type_=MessageType.challenge)
            severity = Severity(output.severity or "medium")
            conflict = Conflict(
                id=f"conflict-r2-{challenger.name}-{challenge_msg.target}",
                description=challenge_msg.claim,
                participants=sorted([challenger.name, challenge_msg.target]),
                severity=severity,
            )
            challenged_targets.add(challenge_msg.target)
            yield Event(author=self.name, actions=EventActions(state_delta={
                "challenges": append_to_blackboard(state, "challenges", challenge_msg),
                "conflicts": append_to_blackboard(state, "conflicts", conflict),
            }))

        # REBUT — each DISTINCT challenged proposer is re-invoked ONCE,
        # responding to every challenge raised against them this round
        # (the SAME agent instance that proposed — acceptance criterion #4,
        # generalized from "the one critic" to "however many challengers
        # targeted this proposer").
        for target_name in sorted(challenged_targets):
            target_agent = proposer_by_name[target_name]
            print(f"[orchestrator] REBUT ({target_name})", flush=True)
            cap = {}
            async for event in _speak(target_agent, ctx, cap):
                yield event
            output = ExpertOutput.model_validate_json(cap["text"])
            rebuttal_msg = _wrap(output, round_=3, phase=DebatePhase.rebut,
                                  agent=target_name, type_=MessageType.rebuttal)
            yield Event(author=self.name, actions=EventActions(
                state_delta={"rebuttals": append_to_blackboard(state, "rebuttals", rebuttal_msg)}
            ))

        # COMPARE + DECIDE — pure function, no LLM call.
        print("[orchestrator] COMPARE / DECIDE", flush=True)
        decision_delta = compute_decision_or_escalation(state)
        if decision_delta:
            yield Event(author=self.name, actions=EventActions(state_delta=decision_delta))

        yield Event(author=self.name, actions=EventActions(escalate=True))
