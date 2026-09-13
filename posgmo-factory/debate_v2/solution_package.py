"""
Phase 7 — Solution Package / ADR (doc §15): "the factory should produce
MORE than code."

Phase 2-6 deliberately stop before code generation (acceptance criterion
#10), so this renders the items of doc §15's package that a pure debate CAN
produce: problem statement, clarified intent, existing-system/reuse map
(context graph), candidate solutions, debate summary + objections, selected
architecture, rationale + evidence, rejected alternatives, and open risks.
The remaining items (implementation plan, acceptance tests, generated
code, review results, PR-ready artifacts) are the EXISTING deterministic
factory's job once/if a Decision here is handed to it (Phase 8) — this
package is the record of WHY, not the HOW.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from debate_schema import read_blackboard, read_status


def render_solution_package(state: dict) -> str:
    status = read_status(state)
    verified = read_blackboard(state, "context_verified_facts")
    assumptions = read_blackboard(state, "context_assumptions")
    participants = read_blackboard(state, "participants")
    proposals = read_blackboard(state, "proposals")
    challenges = read_blackboard(state, "challenges")
    rebuttals = read_blackboard(state, "rebuttals")
    decisions = read_blackboard(state, "decisions")
    rejected = read_blackboard(state, "rejected_alternatives")
    scores = read_blackboard(state, "scores")

    lines = [
        "# Solution Package",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} — "
        f"agentic debate spike (Phase 2-7), not the production factory._",
        "",
        "## 1. Problem Statement",
        "",
        f"> {state.get('request', '')}",
        "",
    ]

    if status.needs_user_input and not proposals:
        lines += [
            "## 2. Status: Clarification Needed",
            "",
            "The debate did not run — intake judged the request's intent too ambiguous",
            "to debate productively.",
            "",
            f"**Reason:** {status.escalation_reason}",
            "",
            "**Open questions:**",
            *[f"- {q}" for q in status.open_questions],
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## 2. Existing-System / Reuse Map",
        "",
        "**Verified facts:**",
        *[f"- {f.claim}" + (f" (`{f.source}`)" if f.source else "") for f in verified],
        "",
        "**Unverified assumptions (flagged, not relied upon as fact):**",
        *[f"- {a.claim}" for a in assumptions],
        "",
        "## 3. Participants",
        "",
        *[f"- **{p.agent}** ({p.role})" for p in participants],
        "",
        "## 4. Candidate Solutions (independent, blind proposals)",
        "",
    ]
    for p in proposals:
        lines += [
            f"### {p.agent}",
            f"> {p.claim}",
            "",
            f"- confidence: {p.confidence:.2f}",
            *([f"- evidence: {e}" for e in p.evidence] if p.evidence else []),
            "",
        ]

    lines += ["## 5. Debate Summary", ""]
    for c in challenges:
        lines += [f"- **{c.agent}** challenged **{c.target}**: {c.claim}", f"  - {c.reasoning_summary}"]
    for r in rebuttals:
        stance = f"revised to: {r.alternative}" if r.alternative else "defended original position"
        lines += [f"- **{r.agent}** {stance}", f"  - {r.reasoning_summary}"]
    lines.append("")

    if scores:
        lines += ["## 6. Comparison", ""]
        for s in scores:
            lines.append(f"- `{s.total:>4}` — {s.subject}")
        lines.append("")

    lines += ["## 7. Decision", ""]
    if decisions:
        d = decisions[0]
        lines += [
            f"**Selected:** {d.selected_claim}",
            "",
            f"**Rationale:** {d.rationale}",
            "",
            f"**Confidence:** {d.confidence:.2f}",
            "",
            "**Evidence:**",
            *[f"- {e}" for e in d.evidence],
            "",
        ]
    else:
        lines += [
            "No decision reached — escalated to the user.",
            "",
            f"**Reason:** {status.escalation_reason}",
            "",
        ]

    lines += ["## 8. Rejected Alternatives", ""]
    for r in rejected:
        lines += [f"- **{r.claim}** (proposed by {r.proposed_by})", f"  - Reason: {r.reason}"]
    lines.append("")

    all_risks = []
    for msg in proposals + challenges + rebuttals:
        for risk in msg.risks:
            all_risks.append((msg.agent, risk))
    lines += ["## 9. Risks / Open Questions", ""]
    if all_risks:
        lines += [f"- ({agent}) {risk}" for agent, risk in all_risks]
    else:
        lines.append("- None flagged by any expert.")
    lines.append("")

    lines += [
        "## 10. Next Step",
        "",
        "This package records WHY a solution was selected. Generating the actual",
        "database/backend/frontend artifacts is the existing deterministic factory's",
        "job (`orchestrator.py`) — this debate does not do that (see acceptance",
        "criterion #10 in the Phase 2-7 design notes).",
    ]

    return "\n".join(lines)
