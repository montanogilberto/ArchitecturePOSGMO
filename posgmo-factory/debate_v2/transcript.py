"""Pretty-printer: renders the final blackboard as a round-by-round
transcript. Phase 2 favors observability over token/format efficiency —
this is meant to be read by a human deciding whether the debate behaved
sensibly, not consumed by another agent."""
from __future__ import annotations

import json

from debate_schema import read_blackboard, read_status


def render_transcript(state: dict) -> str:
    proposals = read_blackboard(state, "proposals")
    challenges = read_blackboard(state, "challenges")
    rebuttals = read_blackboard(state, "rebuttals")
    decisions = read_blackboard(state, "decisions")
    rejected = read_blackboard(state, "rejected_alternatives")
    scores = read_blackboard(state, "scores")
    status = read_status(state)

    verified = json.loads(state.get("context_verified_facts") or "[]")
    assumptions = json.loads(state.get("context_assumptions") or "[]")

    lines = [f"REQUEST: {state.get('request', '')}", ""]

    lines.append("ROUND 0 — ANALYZE (context)")
    for f in verified:
        lines.append(f"  [verified]   {f['claim']}")
    for a in assumptions:
        lines.append(f"  [assumption] {a['claim']}")
    lines.append("")

    if status.needs_user_input and not proposals:
        # Intake (Phase 6) escalated before any proposal was made — the
        # debate never started, so there is nothing further to render.
        lines.append("INTAKE — CLARIFICATION NEEDED (debate not started)")
        lines.append(f"  reason: {status.escalation_reason}")
        for q in status.open_questions:
            lines.append(f"    ? {q}")
        return "\n".join(lines)

    lines.append("ROUND 1 — PROPOSE")
    for p in proposals:
        lines.append(f"  {p.agent}")
        lines.append(f"    proposal:   {p.claim}")
        lines.append(f"    confidence: {p.confidence:.2f}")
        if p.evidence:
            lines.append(f"    evidence:   {p.evidence}")
    lines.append("")

    lines.append("ROUND 2 — CHALLENGE")
    for c in challenges:
        lines.append(f"  {c.agent} -> {c.target}")
        lines.append(f"    challenge: {c.claim}")
        lines.append(f"    reasoning: {c.reasoning_summary}")
        if c.evidence:
            lines.append(f"    evidence:  {c.evidence}")
    lines.append("")

    lines.append("ROUND 3 — REBUT")
    for r in rebuttals:
        lines.append(f"  {r.agent}")
        if r.alternative:
            lines.append(f"    rebuttal: {r.alternative}  (revised position)")
        else:
            lines.append(f"    rebuttal: {r.claim}  (defended original)")
        lines.append(f"    reasoning: {r.reasoning_summary}")
    lines.append("")

    lines.append("ROUND 4 — COMPARE / DECIDE")
    if status.needs_user_input:
        lines.append(f"  ESCALATED TO USER: {status.escalation_reason}")
        for q in status.open_questions:
            lines.append(f"    ? {q}")
    else:
        for s in scores:
            lines.append(f"  score: {s.total:>4} — {s.subject}")
        for d in decisions:
            lines.append(f"  DECISION:   {d.selected_claim}")
            lines.append(f"  rationale:  {d.rationale}")
            lines.append(f"  confidence: {d.confidence:.2f}")
        for r in rejected:
            lines.append(f"  REJECTED:   {r.claim}  (by {r.proposed_by})")
            lines.append(f"  reason:     {r.reason}")

    return "\n".join(lines)
