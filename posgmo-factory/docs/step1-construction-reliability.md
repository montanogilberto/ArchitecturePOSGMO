# STEP 1 — Construction Reliability

Status: **see "Exit criterion" at the bottom** — filled from batch 4 (frozen code).

Raw evidence: `docs/evidence/step1/runs.jsonl` (one line per real Factory run),
`docs/evidence/step1/artifacts/<run>.json` (spec, gate, all three layers'
artifacts, review — per run), batch markers in `docs/evidence/step1/*.txt`.

## Objective

Make the construction layer reliable enough that a Factory run does not depend
on excessive stochastic retries. Starting point (Milestone 7,
`docs/commercial-app-milestones.md`): **32 full-pipeline attempts** to get
`factoryRunUsage` green on all three layers; `database_agent` the least reliable
layer; `MALFORMED_FUNCTION_CALL` the dominant failure.

## What was already implemented (verified in code, not assumed)

- SQL execution already moved out of the LLM tool call into
  `database_executor_agent` (Experiment 1). **Not sufficient**: database_agent
  still held the MCP toolset, and its SQL was still stochastic (snake_case PKs,
  companyId filters on TENANT_INDEPENDENT modules — e.g. the real `factoryRun`
  run that scored database 60).
- `pipeline_diagnostics.py` already classified malformed/empty turns — purely
  observational, no retry.
- `mcp_server.get_generation_rules()` contradicted the reviewer on two
  database rules ("snake_case column names", "sp_all: no parameter").

## Implementation

| Change | Where | Deterministic? |
|---|---|---|
| CRUD SQL rendered from `specification` + `gate_result` with **zero LLM calls** (CRUD_ONLY / CRUD_AND_CONNECTOR, TIER 1/2/4, both tenant models, soft-delete parents, indexes, FKs). Returns `None` — LLM fallback — for any shape or gate constraint it can't honor, never silently drops a rule. | `agents/database/sql_templates.py` | yes |
| `database_agent` = deterministic stage; LLM fallback (`database_llm_agent`) has **no tools** (knowledge pre-loaded) and a **server-validated repair loop**: SQL executed in a rolled-back transaction, server error fed back, ≤3 attempts. | `agents/database/agent.py`, `knowledge.py` | stage yes; fallback bounded |
| Existing live table outranks the spec: PK + column set corrected on `specification` itself before any construction layer reads it; spec columns missing live → `schema_drift` → reviewer error ("needs a migration decision"). | `agents/spec_reconciler/`, `agents/database/live_schema.py` | yes |
| Architect / backend / frontend: MCP knowledge **pre-loaded** instead of tool calls (all were zero/fixed-argument calls); no tools left. Prompts' rules unchanged. | `agents/preloaded_knowledge.py`, `agents/architect/knowledge.py` | yes |
| Bounded per-stage retry (≤3) for architect / backend / frontend when output is unusable; skipped when the gate is BLOCKED. | `agents/retry.py`, `agents/agent.py` | bounded |
| `FACTORY_SQL_MODE=validate`: executor runs every batch on the real server and rolls back. | `agents/database/rules.py` | yes |
| Reviewer: SQL execution error is now **blocking** (one failed batch used to score exactly 90 = pass); PK rule follows the spec's IDENTITY column; OPENJSON-plural check no longer fires on a correct TENANT_INDEPENDENT `sp_all` (the Milestone 7 "open" finding was this false positive). | `agents/reviewer/rules.py` | yes |
| Fixers: `one_{module}_sp` → `one_{plural}_sp` in module + route (3rd independent occurrence); `review_fixer` now repairs `CustomEvent<any>` (the existing fixer ran *before* the frontend existed, so it never applied). | `agents/fixer/rules.py`, `agents/review_fixer/rules.py` | yes |
| Knowledge: two contradictory generation rules corrected (camelCase columns, `sp_all` takes `@pjsonfile`). | `mcp_server/server.py` | — |

## Tests

- `tests/test_database_templates.py` (new, 45 tests) — template output passes the
  **same** deterministic reviewer with **zero** fixer changes across tenant
  models / tiers; real-run regression fixtures (factoryRun spec that scored 60;
  posRewardCatalogItem live PK; supplier `NVARCHAR(1)` active flag; leadCapture
  expression-index rejection; CustomEvent<any>; one_ wrapper drift); fallback
  boundaries; no-tool guarantee on every construction agent.
- `tests/test_database_construction_fixes.py` +1 (one_ wrapper rename).
- Pipeline-shape tests updated for the three new stage wrappers + reconciler.
- Full suite: see Exit criterion.

Real-server probe (`scripts/step1_sql_probe.py`, rolled back, `zz*` names):
tenant-independent and tenant-scoped TIER_2 modules — create, insert, list,
get, update, delete, cross-tenant isolation, 5,000-char NVARCHAR(MAX) round-trip
— **both PASS**. It also found a real template bug (UPDATE nulled an omitted
NOT NULL column) before any Factory run did.

## Real runs

Harness: `scripts/step1_reliability.py` — real pipeline minus PR/design stages
(no GitHub calls), SQL in validate mode. Modules chosen per condition:

| Module | Condition |
|---|---|
| supplier | tenant-scoped catalog, existing live table |
| posRewardCatalogItem | tenant-scoped TIER_2 financial, hand-built live table with non-standard PK |
| factoryRunUsage | tenant-independent (Milestone 7's 32-attempt module), existing live table |
| leadCapture | tenant-independent with ADR constraints → exercises the LLM fallback path |

### Batches 1–3 (24 runs, code evolving — diagnostic)

Each failure below was diagnosed from the saved artifacts, fixed, and covered
by a regression test before the next batch.

| # | Failure (where) | Root cause | Fix | Deterministic | Test |
|---|---|---|---|---|---|
| 1 | posRewardCatalogItem: every SP "Invalid column name 'posRewardCatalogItemId'" | live table PK is `catalogItemId`; architect inconsistently mirrored / invented it across runs | spec_reconciler: live table outranks spec | yes | yes |
| 2 | architect MALFORMED_FUNCTION_CALL 3/3 attempts → gate BLOCKED | temperature 0 + tool calls: retry = identical request | knowledge pre-loaded, no tools | yes | yes |
| 3 | backend MALFORMED_FUNCTION_CALL (8×, once 3/3) | same tool-call surface | retry, then pre-loaded knowledge | yes | yes |
| 4 | frontend "missing" | ~46 KB of code emitted as markdown blocks, not the JSON contract | retry on unusable output + tools removed | bounded | yes |
| 5 | backend 80 "Missing function one_…s_sp()" | singular naturalization, 3rd occurrence | fixer extended | yes | yes |
| 6 | frontend 80 CustomEvent<any> | fixer ran before frontend existed | review_fixer applies it | yes | yes |
| 7 | leadCapture LLM SQL: expression index rejected by server, yet scored 90 = PASS | reviewer severity hole | execution error blocking + repair loop | yes / bounded | yes |
| 8 | UPDATE nulled omitted NOT NULL column (probe) | template full-replace | NOT NULL keeps current value | yes | yes |
| 9 | backend retried 3× on a BLOCKED run | wasted calls | no retries when gate BLOCKED | yes | — |

Validate mode verified non-destructive: every live SP the runs touched still
shows a `modify_date` earlier than the first real run; no `zz*` probe object
exists.

**database_agent `MALFORMED_FUNCTION_CALL` across all 24 runs: 0.** (Rest of
the pipeline in the same runs: prd_enricher 17, architect 11, backend 8,
review_fixer 3, frontend 1.)

### Batch 4 (frozen code — exit-criterion evidence)

_Filled in below from runs.jsonl._

## Known, contained, carried forward (not Step 1 blockers)

- **prd_enricher_agent MALFORMED_FUNCTION_CALL in ~70% of runs** — its
  `save_enriched_prd(enriched_prd: dict)` passes a large dict as a tool
  argument (the pattern Step 1 removed elsewhere). Non-fatal by design (the
  architect falls back to the raw PRD), but it silently lowers spec quality —
  Step 2 (full module construction quality) is where it belongs.
- review_fixer_agent still reaches its tool through the MCP toolset (3
  malformed calls); the deterministic reviewer/fixers bound the impact.
- The LLM fallback's SQL is bounded (≤3 attempts, server-validated) but not
  deterministic; ADR-driven constraints (e.g. leadCapture's normalized-email
  UNIQUE rule) are the reason modules land there.
- Apply mode (`FACTORY_SQL_MODE` unset) writes to the shared live server as
  before; `CREATE OR ALTER` would replace a live SP of an existing table.
  Validation runs here used validate mode only.

## Exit criterion
