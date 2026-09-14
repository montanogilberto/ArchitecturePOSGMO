"""
Phase 4 — dynamic panel selection (doc §6): "the number of participating
agents can be dynamic. A panel selector can activate only the experts
relevant to the problem." Deterministic keyword heuristics — no LLM call,
no added cost, fully predictable and testable.

Doc §7's opening paragraph names Product Owner, Domain/Business Expert,
Context/Repository Analyst, Architect, and Senior Engineer as the "core
agents" (Context/Repository Analyst = the deterministic ContextAgent from
Phase 2/3, not an LLM debater; Senior Engineer is folded into `critic` here,
same as Phase 2). Everything else in the doc's fuller roster — UX, Backend,
Frontend, Database, Integration, Security, QA, Governance — activates only
when the request plausibly touches that concern.
"""
from __future__ import annotations

from typing import List

# Doc §7's "core agents" (minus Context/Repository Analyst, which is the
# deterministic ContextAgent, not an LLM debate participant).
ALWAYS_ACTIVE_CHALLENGERS: List[str] = ["domain_expert", "critic"]

_KEYWORD_TRIGGERS = {
    "security_expert": [
        "auth", "permission", "role", "payment", "pii", "password", "token",
        "security", "kyc", "card", "bank", "clabe", "stripe", "biometric",
    ],
    "integration_expert": [
        "notification", "push", "chat", "whatsapp", "email", "sms",
        "integration", "webhook", "azure", "twilio", "marketplace",
    ],
    "ux_expert": [
        "ui", "screen", "page", "mobile", "workflow", "conversational",
        "wizard", "dashboard", "usability",
    ],
    "qa_expert": ["test", "edge case", "acceptance", "validation", "quality"],
    "governance_expert": ["compliance", "rule", "policy", "audit", "regulat", "governance"],
}


# Phase 5 (doc §14 "maximum debate rounds or token budget has been
# reached"): the round protocol itself is already fixed-length (7 phases),
# so the one open-ended cost knob is panel SIZE — cap it so a request that
# happens to match many keyword triggers can't silently balloon past this
# repo's currently-registered roster. Set to the full size of
# CHALLENGER_ROLE_BLURBS (7): this is a guard against future roster growth,
# not a truncation of today's roster — a request that legitimately touches
# every registered concern (as a cross-cutting AI-assistant feature does)
# should be able to activate all of them.
MAX_CHALLENGERS = 7


def select_challengers(request: str, verified_fact_text: str = "") -> List[str]:
    """Always includes domain_expert + critic; adds any conditional expert
    whose trigger keyword appears in the request (or the gathered evidence
    text, so e.g. a PRD that itself mentions "payment" pulls in Security
    even if the user's one-line request didn't say so). Capped at
    MAX_CHALLENGERS, always-active roles first."""
    text = (request + " " + verified_fact_text).lower()
    selected = list(ALWAYS_ACTIVE_CHALLENGERS)
    for role, keywords in _KEYWORD_TRIGGERS.items():
        if any(kw in text for kw in keywords):
            selected.append(role)
    return selected[:MAX_CHALLENGERS]
