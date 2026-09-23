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

## Phase 3 — Implementation RAG — DONE (2026-09-21)

**Status: proven, committed (`10fe021`).** Fourth collection on the same
`search_factory_experience` tool/index: real generated code from
`local_export/*/artifacts.json` (SQL, FastAPI routes/modules, React/Ionic
pages+APIs+CSS). One chunk per generated file — "show me how we implemented
a similar module" is a whole-file browsing case, not a line-search case.

**The filter that had to be per-layer, not per-module, proven on real
data:** each layer indexed only if that layer's own reviewer score is
`>= 80`. `notificationDispatch` scored `backend: 20` (broken) but
`database: 100, frontend: 100` (genuinely good) in the *same run* — a
per-module filter would have gotten one of those two judgments wrong,
either offering broken backend code as a pattern to copy or discarding two
genuinely good implementations.

**The concrete proof:** *"a React page component with infinite scroll
pagination for a list of records"* — no module named — retrieves actual
generated React/Ionic page code containing real `IonInfiniteScroll`/
`IonList` markup, across multiple modules' real implementations. Not
findings about the code; the code itself.

**Reported honestly, not swept under the rug — two real things found
while proving this, not just the clean result:**
1. `notificationDispatch`'s `frontend_artifacts` is stored as raw
   `` ```typescript `` code, not JSON — an older, incompatible pipeline
   schema shape (pre-dating even this session). `_parse_artifact_json`
   degrades gracefully (returns `{}`) rather than crashing or indexing
   garbage from it.
2. A first proof-query attempt — *"a FastAPI backend module with a public
   endpoint that doesn't require authentication"* — did NOT retrieve
   `pricingPlan`'s backend as expected. Traced it: not a retrieval bug.
   `pricingPlan`'s actual generated `route_file` genuinely never contains
   the custom public endpoint its own PRD asked for — `backend_agent`
   silently omitted it. Worse: `run_local_export.py` (used for *every*
   real run this entire session) never wires in
   `check_backend_endpoint_completeness` at all — only `orchestrator.py`'s
   full `run_factory()` does. This gap existed the whole time and was only
   surfaced as a side effect of Phase 3's retrieval work. **Flagged as a
   follow-up, not fixed** — out of Phase 3's own scope.

**Also observed, not yet acted on:** semantic retrieval measurably performs
better on frontend/UI code (React/Ionic import structure correlates
reasonably with natural-language UI descriptions) than it would likely
perform on backend/database code for *behavioral* queries — each
implementation chunk's `finding` label is currently just a generic file
descriptor (`module — layer — path — score`), with no description of what
the code actually *does*. Enriching that label (e.g. from the PRD's own
endpoint descriptions) would likely improve backend/database retrieval
quality. A real quality gap for a future pass, not pretended away.

## Phase 4 — Agentic PRD Builder — DONE (2026-09-21)

**Status: proven, committed (`1306fb9`).** The gap named explicitly before
Phase 1 started: every PRD in this whole series (`leadCapture` through
`factoryArtifact`) was hand-authored by reading prior PRDs and docs, not
generated by an agent. The actual `agents/prd_builder_agent.py` was deleted
in a past restructure (commit `2c044c9`) and never rebuilt;
`prd-builder/agent.py` still imported it and was still broken right up
until this phase — fixed as part of it.

**Not a revival of the old agent — a deliberate replacement.** The deleted
version assumed every module gets a `companyId` automatically and never
asked. That exact assumption caused ADR-001's real `leadCapture` bug. The
new `agents/prd_builder/` researches `search_factory_experience` (Phases
1-3) and MCP's structured getters *before* writing anything, and decides
tenant model from evidence every time — the same discipline every
hand-written PRD in this series already follows, now automated instead of
requiring a person to remember it.

**The concrete proof — a real, in-scope request, not a toy example:**
*"I need a way to track how much LLM usage (tokens, cost) each Factory Run
consumed, so we can eventually bill for it"* — the actual next module in
this roadmap's own dependency chain (`factoryRun → factoryArtifact → Usage
→ Billing`). Produced a complete PRD (`tests/prd_factoryRunUsage.json`)
with correct tenant-model reasoning, the correct plain-reference-not-FK
pattern citing real precedent modules (`organization`, `projects`,
`factoryArtifact`) by name, and three substantial open architectural
questions — while genuinely researching first (`search_factory_experience`,
`get_decisions_for_module`, `get_table_list`, `get_generation_rules`,
confirmed via captured tool-call traces). Zero-LLM tenant classifier:
`TENANT_INDEPENDENT`, resolved directly, no ADR needed — same clean-pass
shape as the best hand-written PRDs in this series.

**Two real defects found across 3 live runs, not glossed over — the second
one almost slipped through:**
1. Run 1: `database.tables`/`storedProcedures` came back as rich objects,
   not the plain strings `PRDDatabaseHints` requires. `PRDInput.model_
   validate()` correctly raised — caught immediately. Fixed the prompt with
   an explicit example.
2. Run 2: `CONSTRAINTS`/`OPEN ARCHITECTURAL QUESTIONS` came back as
   **separate top-level JSON keys**, not embedded in `description` like
   every real PRD in this repo. `PRDInput.model_validate()` printed
   **"VALID" anyway** — Pydantic silently drops unrecognized extra fields
   by default, so the richest content in the PRD (the exact material Phase
   2's RAG indexes) would have been silently discarded by every downstream
   consumer, undetected, if not caught by reading the *whole* output
   instead of trusting the validation result. Fixed at the schema level,
   not just the prompt: `prd_schema.py`'s `PRDInput` now sets
   `model_config = ConfigDict(extra="forbid")` — verified against all 32
   existing `tests/prd_*.json` fixtures first, confirming nothing already
   relied on the old silently-permissive behavior, before enabling it.

Run 3, with both fixes in place, produced fully clean, strict-schema-valid
output. That's the version saved as `tests/prd_factoryRunUsage.json`.

**Update (2026-09-22): done.** `factoryRunUsage` was taken through real
construction — see `docs/commercial-app-milestones.md` Milestone 7. Took 32
attempts (construction-layer stochasticity, same character documented since
Milestone 1 — not a Phase 4 defect), surfaced a real reviewer bug along the
way (a bare-`CustomEvent` false positive, fixed), and landed a genuine
simultaneous pass on all three layers: `database: 90, backend: 100,
frontend: 100`. The real `FactoryRunUsages` table + SPs that resulted are
being kept in the live database as the actual `Usage` module, not treated
as sandboxed test residue — an explicit decision, not a default.

## Phase 5 — Full Factory Agent — DONE (2026-09-21)

**Status: proven, committed (`d6eefc6`).** The closed loop: understand
requirement → PRD Builder → Knowledge/RAG (Experience + Architecture +
Implementation, all three) → MCP/Graph → Architecture → Construction →
Reviewer → (fail → Fix Loop | pass → Artifact) → Factory Memory, which
feeds the next run.

**What Phase 5 actually built, and what it deliberately didn't.**
Construction, review, and the fix loop already existed — `factory_agent.py`
is orchestration, not new pipeline machinery: `run_factory_agent()` wires a
raw request into `prd_builder_agent` (Phase 4), validates the result under
the now-strict `PRDInput` schema, feeds it into `run_local_export.run_local()`
(the exact same sandboxed pipeline every module in this series has run
through), and refreshes the Factory Experience index afterward.

**Two boundaries held deliberately, not relaxed for "closing the loop":**
- **Still sandboxed.** `run_local()` still strips `pr_agent` — no GitHub
  call of any kind, win or lose. Enabling real pushes is a separate,
  explicit decision this script does not make for you.
- **No automatic retry on failure.** Same standing principle since
  Milestone 1: chasing a lucky pass "measures API-call stochasticity, not
  learn anything new about the architecture." A FAIL is reported honestly,
  with the real `review_result`, not hidden behind another attempt.

**The proof — one real, live, fully unattended run of the whole loop,**
not a mocked demonstration: the same raw request Phase 4 used ("track LLM
usage per Factory Run for billing") produced a *new* PRD (`usageMeter`,
saved to `tests/prd_usageMeter.json`, validated cleanly under the strict
schema) and ran it straight into construction. Result: `backend: 100`,
`database`/`frontend` produced no output — the same well-documented
construction-layer stochasticity tracked since Milestone 1, not a Phase 5
defect. Reported honestly: `status: constructed`, `passed: false`, real
issues listed, no pretending. **Factory Memory genuinely closed the loop,
not just in theory:** the index grew 165 → 177 chunks, including 6 new
`usageMeter` chunks confirmed present and retrievable — available to the
*next* `prd_builder_agent` call, not merely computed and discarded.

**Not yet done, by design, same as every phase before it:** an automatic
retry/repair strategy for construction-layer stochasticity remains out of
scope everywhere in this project, not just here — that's still a
separately-tracked, not-yet-urgent problem, consistent with Milestone 1's
original verdict. Real GitHub pushes remain a human decision.

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
what Phase 1 indexes and what Phases 2-3 extended to. All five phases below
are now done — this is the actual progression that happened, not a plan:

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
