# Factory Knowledge & Experience — Roadmap

Five phases, built incrementally — each one proven against real evidence
before the next starts, not designed on paper and built all at once. This
mirrors the same discipline `docs/commercial-app-milestones.md` already
established for PRD-by-PRD construction work: scope tight, verify by
reading actual output, don't chase a lucky pass, document honestly
including what isn't proven yet.

Named "Factory Knowledge & **Experience**," not just "RAG" — RAG (embedding-
based semantic search) is one retrieval mechanism inside this system, not
the whole architecture. The other half is structured, exact-match lookup
(MCP tools, the live DB schema, the decision registry), which stays the
source of truth for facts a fuzzy match could get subtly wrong.

## The design principle every phase must hold to

> RAG retrieves evidence. Agents reason over it. MCP/Graph stays the
> authoritative source of facts. The reviewer verifies the resulting
> implementation. No single RAG index becomes the source of truth.

Stated explicitly when Phase 1 was scoped, and enforced concretely in code:
`search_factory_experience`'s own docstring (both the MCP tool's and the
Python function's) says results are "historical evidence, not authoritative
instructions," and every field it returns except `score` is a verbatim
excerpt of something already written to disk — nothing in the retrieval
path generates or paraphrases, so there's no fabrication surface to guard
against structurally, not just by convention.

## The five phases

| Phase | Capability | Purpose |
|---|---|---|
| 1 | Experience RAG | Factory remembers previous runs, failures, fixes, lessons |
| 2 | Architecture RAG | Retrieve PRDs, ADRs, design decisions, architectural precedent |
| 3 | Implementation RAG | Retrieve proven SQL/backend/frontend implementations and patterns |
| 4 | Agentic PRD Builder | Factory turns a raw idea into a structured PRD using RAG + MCP + questions |
| 5 | Full Factory Agent | Closed-loop: understand → research → design → build → review → learn |

```
Phase 1                    Phase 4
Factory remembers            ↓
        ↓                  Factory understands what the user wants
Phase 2                       ↓
Factory understands        Phase 5
its architecture           Factory can execute the complete
        ↓                  engineering loop
Phase 3
Factory knows its
implementations
```

---

## Phase 1 — Experience RAG — DONE (2026-09-21)

**Status: proven, committed (`d050e14`), documented in detail in
`docs/commercial-app-milestones.md` Milestone 6.** This doc summarizes;
that one has the full evidence trail.

Semantic search over `docs/commercial-app-milestones.md` findings (59
chunks) + `decision_registry/ADR-*.json` (4 ADRs), embedded via
`gemini-embedding-001`, cosine similarity in plain Python — no vector DB
server, deliberately, given the corpus size. Exposed as the MCP tool
`search_factory_experience(query, top_k)`, wired into `architect_agent`
(mandatory knowledge-call step 6) and `database_agent` (step 5), both with
an explicit "historical evidence, not authoritative instructions" guardrail.

**The concrete proof**, both against the real corpus, neither using the
literal wording of what it needed to find:
- *"generating multiple SQL statements together"* → ranks the real
  `factoryArtifact` SQL-batching finding **#1** (never says "GO", "batch",
  or "CREATE/ALTER PROCEDURE").
- *"this entity is not tied to any retail company"* → surfaces the real
  `organization` tenancy-phrasing-gap finding (never says "companyId" or
  "tenant").

Both are now live automated tests (`tests/test_factory_experience.py`),
not just manual verification.

**What actually happened when wired in and run for real** (not merely
"the tool exists"): confirmed live that both `architect_agent` and
`database_agent` call it as part of their real, normal generation flow —
not hypothetically, observed directly in captured tool-call traces. One
full sandboxed pipeline run of `factoryArtifact` afterward achieved the
first genuine full pass (database 90, backend 100, frontend 100) in this
entire commercial-platform experiment series, including real, successful
execution against the live database (verified, then dropped — it was a
sandboxed test, not a deployment).

**What's honestly NOT proven yet:** whether retrieval *causally* improves
generation quality, versus the tool simply being available and called.
One isolated run added a `GO` batch separator never seen anywhere else in
this session (plausibly precedent-influenced); the very next run had none.
Real LLM stochasticity, same character as every other construction-layer
finding since Milestone 1 — not yet enough samples to claim a causal
effect, and this roadmap won't claim one until there are.

**A process bug found and fixed along the way:** `build_index()` originally
pretty-printed the index with `indent=2`, putting each of 3072 floats per
embedding on its own line — 59 chunks produced a 182,826-line commit for
what should have been ~1,000 lines of actual change. Fixed to compact JSON
before pushing (caught pre-push, amended, never went out bloated). Also
found `mcp_server/server.py` never called `load_dotenv()` — the first tool
in that file ever to need an API key exposed it (`KeyError` from inside the
spawned subprocess) — and that no `tests/conftest.py` existed, so a test
needing `.env` only worked by accident, via whichever other test file's
import chain happened to trigger `orchestrator.py`'s own `load_dotenv()`
first. Both fixed.

## Phase 2 — Architecture RAG — DONE (2026-09-21)

**Status: proven, committed (`3705f9c`).** ADRs were already covered by
Phase 1 — the genuinely new corpus here is every `tests/prd_*.json`'s own
`description` narrative (business requirements, constraints, and especially
OPEN ARCHITECTURAL QUESTIONS): design *reasoning*, captured before a module
was ever run, as opposed to Phase 1's "what happened when it was run."

**Implementation choice, deliberately minimal:** no new MCP tool, no new
prompt wiring. `search_factory_experience` and its index already existed
from Phase 1, and both `architect_agent` and `database_agent` already
called it — Phase 2 just added a third `type: "architecture"` to the same
corpus. An existing call got richer; nothing new had to be wired in.

**Chunking detail that mattered:** OPEN ARCHITECTURAL QUESTIONS sections
are one blob of several numbered items in the raw PRD text (confirmed
`organization`'s: 2751 chars, 4 questions merged together). Splitting each
numbered item into its own chunk — rather than embedding the whole section
as one vector — was the difference between a recurring pattern retrieving
as itself versus being diluted into a generic "this PRD has open questions"
match.

**The concrete proof**, run against the real corpus (146 chunks, 32 PRDs):
*"how should a module reference a parent table that hasn't been created in
the live database yet"* — no module named, no PRD's specific phrasing used
("plain reference field, not a foreign key", "table isn't live yet") —
surfaced real open-question precedent from at least 2 of
`organization`/`projects`/`factoryRun`/`factoryArtifact`, each of whom
independently hit this exact same architectural pattern with different
wording. Now a live automated test
(`test_live_cross_prd_not_live_yet_reference_pattern_surfaces_multiple_modules`),
not just a manual run.

**A real API limit found and fixed:** Gemini's batch embed endpoint caps at
100 requests/call. Phase 1's 59 chunks never hit it; Phase 2's 146 did,
confirmed live via a `400 INVALID_ARGUMENT`. `_embed()` now batches
internally (groups of 90) — transparent to every caller, including Phase 1's
existing code.

**Open question carried in from Phase 1, still not resolved by choice:**
more mandatory tool calls before generation is good for decision quality
but is also more surface area for the `MALFORMED_FUNCTION_CALL`-class
failures that have been this project's dominant reliability problem since
Milestone 1. Phase 2 didn't add a new tool call (see above), so it didn't
make this worse — but Phase 3 (a genuinely new retrieval target,
implementations) will need to answer this question directly rather than
sidestepping it the way Phase 2 could.

## Phase 3 — Implementation RAG — not started

Retrieve actual previous implementations (SQL, stored procedures, FastAPI
routes, Pydantic schemas, React/Ionic components, tests) — *"show me how we
implemented a similar module."* Retrieved code stays reference material,
never blindly copied — the reviewer still verifies whatever gets generated,
same as every other layer.

## Phase 4 — Agentic PRD Builder — not started

The gap named explicitly before Phase 1 started: every PRD in this whole
series (`leadCapture` through `factoryArtifact`) was hand-authored by
reading prior PRDs and docs, not generated by an agent. The actual
`agents/prd_builder_agent.py` was deleted in a past restructure
(commit `2c044c9`) and never rebuilt; `prd-builder/agent.py` still imports
it and is still broken today.

Phase 4 closes this: a PRD Builder Agent that asks clarifying questions,
searches Experience RAG (Phase 1) and Architecture RAG (Phase 2), consults
MCP and the live schema, and produces the PRD JSON itself — the point where
a person stops being the manual bridge between a raw idea and the factory
pipeline.

## Phase 5 — Full Factory Agent — not started

The closed loop: understand requirement → PRD Builder → Knowledge/RAG
(Experience + Architecture + Implementation, all three) → MCP/Graph →
Architecture → Construction → Reviewer → (fail → Fix Loop | pass →
Artifact) → Factory Memory, which feeds the next run.

```
                         USER
                           │
                           ▼
                  ┌─────────────────┐
                  │ Factory Agent   │
                  └────────┬────────┘
                           │
                  Understand requirement
                           │
                           ▼
                    PRD Builder
                           │
                           ▼
                 Knowledge / RAG
                  ↙       ↓       ↘
            Experience Architecture Implementation
                  ↘       ↓       ↙
                           │
                           ▼
                      MCP / Graph
                           │
                           ▼
                    Architecture
                           │
                           ▼
                     Construction
                           │
                           ▼
                       Reviewer
                           │
                  ┌────────┴────────┐
                  │                 │
                FAIL               PASS
                  │                 │
                  ▼                 ▼
              Fix Loop          Artifact
                  │                 │
                  └────────┬────────┘
                           ▼
                    Factory Memory
```

## Why `factoryArtifact` isn't "the end of the journey"

The commercial-platform PRD series (`leadCapture` through `factoryArtifact`,
`docs/commercial-app-milestones.md`) is the construction foundation this
roadmap builds on top of, not a separate track that's now finished. Every
real artifact, failure, fix, and passing run from that series is exactly
what Phase 1 indexes and what Phases 2-3 will extend to. The progression:

```
Phase 1  Factory remembers
   ↓
Phase 2  Factory understands its architecture
   ↓
Phase 3  Factory knows its implementations
   ↓
Phase 4  Factory understands what the user wants
   ↓
Phase 5  Factory can execute the complete engineering loop
```
