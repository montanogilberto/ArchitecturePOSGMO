"""
Debate Schema — the blackboard and message contract for the agentic debate
engine (Phase 1). Additive: nothing in the existing deterministic pipeline
(agents/agent.py) reads or writes any of this yet.

Design principles this schema encodes (per the debate architecture doc and
the revised phasing agreed on 2026-09-13):
  - The blackboard represents the CONVERSATION, not just the final answer —
    proposals/challenges/rebuttals all persist; nothing is overwritten.
  - Rejected proposal != deleted proposal. `rejected_alternatives` is a
    permanent record, not a discard pile.
  - The orchestrator is a chairperson, not an expert: nothing here lets an
    orchestrator author a `claim` — only experts (named `agent`s) do, via
    DebateMessage. The orchestrator only writes Decision/DebateStatus,
    which are derived records, never freeform claims.
  - Context is split into verified_facts / assumptions / evidence so the
    factory never treats an unverified assumption as ground truth.

Usage:
    from debate_schema import DebateMessage, DebateSession, append_to_blackboard, read_blackboard

    # inside a custom BaseAgent._run_async_impl:
    state = ctx.session.state
    msg = DebateMessage(round=1, phase=DebatePhase.PROPOSE, agent=self.name,
                         type=MessageType.proposal, claim="...", confidence=0.6)
    delta = {"proposals": append_to_blackboard(state, "proposals", msg)}
    yield Event(author=self.name, actions=EventActions(state_delta=delta))
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Dict, List, Optional, Type

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DebatePhase(str, Enum):
    """Minimal 7-phase protocol (Phase 2 starting point). This is a subset
    of the fuller 9-round protocol in the source doc (§11) — FRAME/ANALYZE
    fold in problem-framing + evidence-collection, COMPARE/DECIDE fold in
    alternative-comparison + validation + convergence. Extend, don't replace,
    when the full round protocol is built."""
    frame     = "frame"
    analyze   = "analyze"
    propose   = "propose"
    challenge = "challenge"
    rebut     = "rebut"
    compare   = "compare"
    decide    = "decide"


class MessageType(str, Enum):
    proposal   = "proposal"
    challenge  = "challenge"
    rebuttal   = "rebuttal"
    evidence   = "evidence"
    concession = "concession"   # e.g. "Product Owner: Agreed."


class ContextItemKind(str, Enum):
    verified_fact = "verified_fact"
    assumption    = "assumption"
    evidence      = "evidence"


class Severity(str, Enum):
    low    = "low"
    medium = "medium"
    high   = "high"


class ScoreDimension(str, Enum):
    """Exact dimensions from the source doc §13."""
    reuse                      = "reuse"
    architecture_compatibility = "architecture_compatibility"
    business_fit                = "business_fit"
    security                    = "security"
    ux                          = "ux"
    maintainability              = "maintainability"
    complexity                   = "complexity"
    testability                  = "testability"
    integration_compatibility    = "integration_compatibility"
    rule_compliance              = "rule_compliance"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

class ContextItem(BaseModel):
    """One fact/assumption/evidence entry on the blackboard's context."""
    kind: ContextItemKind
    claim: str
    source: Optional[str] = Field(
        default=None,
        description="Citation, e.g. 'repo:smartloans_backend/modules/income.py' or "
                    "'knowledge:Backend/backend_business_domains.json.json'.",
    )


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

class Participant(BaseModel):
    agent: str = Field(description="Matches the BaseAgent/LlmAgent .name that speaks as this participant.")
    role: str = Field(description="Free-form role label, e.g. 'product_owner', 'architect', 'critic' — "
                                   "not an enum because the expert panel is dynamic (doc §6).")


# ---------------------------------------------------------------------------
# Debate messages — the structured message contract (doc §12)
# ---------------------------------------------------------------------------

class DebateMessage(BaseModel):
    round: int = Field(ge=1)
    phase: DebatePhase
    agent: str = Field(description="Author of this message — must be a Participant.agent.")
    type: MessageType
    target: Optional[str] = Field(
        default=None, description="agent name this message responds to, if any.",
    )
    claim: str
    evidence: List[str] = Field(default_factory=list, description="Citations, e.g. 'repo:path', 'knowledge:file'.")
    reasoning_summary: Optional[str] = Field(
        default=None, description="Concise reasoning — never private chain-of-thought (doc §12).",
    )
    risks: List[str] = Field(default_factory=list)
    alternative: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Conflicts, scoring, risks
# ---------------------------------------------------------------------------

class Conflict(BaseModel):
    id: str
    description: str
    participants: List[str]
    severity: Severity
    status: str = Field(default="open", pattern=r"^(open|resolved)$")
    resolution: Optional[str] = None


class ScoreCard(BaseModel):
    subject: str = Field(description="Which claim/proposal this scores, e.g. a DebateMessage.claim or id.")
    scores: Dict[ScoreDimension, float] = Field(default_factory=dict)
    total: Optional[float] = None
    notes: Optional[str] = None


class Risk(BaseModel):
    description: str
    severity: Severity
    mitigation: Optional[str] = None
    owner: Optional[str] = Field(default=None, description="Agent responsible for tracking this risk.")


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

class Decision(BaseModel):
    round: int
    selected_claim: str
    rationale: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    decided_by: str = Field(default="debate", pattern=r"^(debate|escalation)$")


class RejectedAlternative(BaseModel):
    claim: str
    proposed_by: Optional[str] = None
    reason: str
    evidence: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Status — the loop's own control state (doc §14 stopping conditions)
# ---------------------------------------------------------------------------

class DebateStatus(BaseModel):
    round: int = 0
    phase: DebatePhase = DebatePhase.frame
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_user_input: bool = False
    escalation_reason: Optional[str] = None
    open_questions: List[str] = Field(
        default_factory=list,
        description="Adaptive clarifying questions from the intake gate (Phase 6) — "
                    "populated only when needs_user_input is True because intent, not "
                    "a technical disagreement, was unclear.",
    )


# ---------------------------------------------------------------------------
# The blackboard root
# ---------------------------------------------------------------------------

class DebateSession(BaseModel):
    """The full blackboard shape. In ADK session state this is NOT stored as
    one nested blob — each list lives under its own flat state key (see
    BLACKBOARD_LIST_KEYS below), matching this repo's existing convention
    (state["specification"], state["gate_result"], etc. are each their own
    key). DebateSession exists to validate/assemble a coherent snapshot —
    e.g. for the Solution Package / ADR — not as the literal state shape."""
    request: str

    verified_facts: List[ContextItem] = Field(default_factory=list)
    assumptions: List[ContextItem] = Field(default_factory=list)
    evidence: List[ContextItem] = Field(default_factory=list)

    participants: List[Participant] = Field(default_factory=list)

    proposals: List[DebateMessage] = Field(default_factory=list)
    challenges: List[DebateMessage] = Field(default_factory=list)
    rebuttals: List[DebateMessage] = Field(default_factory=list)

    conflicts: List[Conflict] = Field(default_factory=list)
    scores: List[ScoreCard] = Field(default_factory=list)
    risks: List[Risk] = Field(default_factory=list)

    decisions: List[Decision] = Field(default_factory=list)
    rejected_alternatives: List[RejectedAlternative] = Field(default_factory=list)

    status: DebateStatus = Field(default_factory=DebateStatus)


# ---------------------------------------------------------------------------
# Flat session-state keys <-> models, and (de)serialization helpers
# ---------------------------------------------------------------------------

# Maps the literal ADK session.state key -> the item model stored as a JSON
# list under that key. "status" is the one non-list key (a single object).
BLACKBOARD_LIST_KEYS: Dict[str, Type[BaseModel]] = {
    "context_verified_facts": ContextItem,
    "context_assumptions":    ContextItem,
    "context_evidence":       ContextItem,
    "participants":           Participant,
    "proposals":              DebateMessage,
    "challenges":             DebateMessage,
    "rebuttals":              DebateMessage,
    "conflicts":              Conflict,
    "scores":                 ScoreCard,
    "risks":                  Risk,
    "decisions":              Decision,
    "rejected_alternatives":  RejectedAlternative,
}


def seed_blackboard_state() -> Dict[str, str]:
    """Empty-blackboard state deltas, for an orchestrator to seed at session
    creation — mirrors orchestrator.py's existing pattern of pre-seeding
    JSON-blob keys (e.g. "gate_result": "{}") so downstream json.loads()
    never crashes on a key no prior agent has written yet."""
    seeded = {key: "[]" for key in BLACKBOARD_LIST_KEYS}
    seeded["status"] = DebateStatus().model_dump_json()
    return seeded


def append_to_blackboard(state: dict, key: str, item: BaseModel) -> str:
    """Read-append-write a blackboard list key. ADK's state_delta is a dict
    MERGE, not a list push, so every write must round-trip the full list —
    same pattern proven in tests/test_debate_orchestrator_spike.py."""
    if key not in BLACKBOARD_LIST_KEYS:
        raise ValueError(f"Unknown blackboard key: {key!r}")
    expected_model = BLACKBOARD_LIST_KEYS[key]
    if not isinstance(item, expected_model):
        raise TypeError(f"{key!r} holds {expected_model.__name__}, got {type(item).__name__}")

    current = json.loads(state.get(key) or "[]")
    current.append(item.model_dump(mode="json"))
    return json.dumps(current)


def read_blackboard(state: dict, key: str) -> list:
    """Parse and validate a blackboard list key back into typed models."""
    if key not in BLACKBOARD_LIST_KEYS:
        raise ValueError(f"Unknown blackboard key: {key!r}")
    model = BLACKBOARD_LIST_KEYS[key]
    raw = json.loads(state.get(key) or "[]")
    return [model.model_validate(row) for row in raw]


def read_status(state: dict) -> DebateStatus:
    raw = state.get("status")
    return DebateStatus.model_validate_json(raw) if raw else DebateStatus()


def write_status(status: DebateStatus) -> str:
    return status.model_dump_json()
