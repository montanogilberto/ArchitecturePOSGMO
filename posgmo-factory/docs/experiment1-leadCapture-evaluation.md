# Experiment 1 — Commercial Factory / leadCapture

**Purpose:** measure what the current Software Construction Factory (`agents/agent.py::root_agent`) can actually derive from a real, deliberately under-specified requirement — not to build a perfect `leadCapture` module.

**Not fed to the agents.** This document is an evaluation rubric, written before the run, read only by a human (or a future reviewer agent) after the run. The PRD (`tests/prd_leadCapture.json`) is the only input the factory sees.

- Factory pipeline: `host_architect → prd_parser → prd_enricher → schema_analyst → architect → decision_gate → {database, backend, design_consistency} → fixer → frontend → review_fix_loop(reviewer → loop_exit → review_fixer, ×3) → pr`
- PRD: `tests/prd_leadCapture.json`
- Run: 2026-09-16. Excludes `pr_agent` (see run notes below) — no branch push, no PR opened. Full session state: `experiment1_state.json` (repo root, gitignored working file).

## Known-in-advance facts about the factory (from reading the code, not from running it)

- No Security, Governance, QA, or Product Owner agent exists. No debate mechanism runs inside `root_agent` (a separate `debate_v2/` experiment exists in this repo but is not wired into `orchestrator.py`).
- `decision_gate` is deterministic Python: tier classification + `CRUD_ONLY` vs `CRUD_AND_CONNECTOR` detection by keyword. It has no concept of "public/unauthenticated endpoint" as a risk category.
- `reviewer_agent` is deterministic Python logic (`run_review`) wrapped in an LLM tool-call shell. Its ~60 checks are POS GMO code-convention linting (naming, `companyId` presence in `CREATE TABLE`/`sp_all`, transaction wrapping, Ionic component usage). It has zero checks for rate limiting, CORS, payload-size limits, duplicate detection, consent, retention, or audit-trail existence.
- `companyId` insertion into `CREATE TABLE` is one of the reviewer's `auto_error` (-20 pt) checks — i.e. the reviewer actively penalizes *omitting* `companyId`, regardless of whether it makes business sense for this module.
- There is no test-generation stage anywhere in the pipeline. `backend_agent`'s `docs_files` are plain-text endpoint descriptions consumed by FastAPI's `description=` param, not tests.

## Headline result

**Every layer independently decided the public lead-capture form must supply `companyId`.** Database Agent made it `NOT NULL` with no default; Backend Agent put it in the *public* endpoint's `allowed_fields` allow-list (the one list whose entire purpose was to keep internal-only fields out); Frontend Agent's generated `PublicLeadCreatePayload` TypeScript type marks `companyId: number` as required. Three independent LLM calls, no coordination between them, same wrong answer — exactly outcome **B** from the pre-run hypothesis ("factory blindly adds companyId because that's what existing conventions expect"), and confirmed at every layer rather than just one. Nothing in the pipeline ever surfaced this as a conflict with the PRD's explicit "this lead has no existing companyId relationship" statement.

That single decision, combined with a second independently-reasonable decision (Database Agent's own unique-index answer to the duplicate-lead question), compounds into a concrete vulnerability: see row 4/5/7 below.

## Evaluation criteria

| # | Area | Question | Observed |
|---|------|----------|----------|
| 1 | Requirement fidelity | Did the generated module implement everything explicitly requested (public create, list/search/filter, detail view, status, assignment)? | Mostly yes at the surface level: `sp_leadCaptures`/`_all`/`_one`, `POST /leadCaptures` family, `POST /leadCaptures/public`-equivalent (`/api/leadCapture/public`), `/api/leadCapture/{id}/assign`, list+detail TSX with status/assignment selects all exist. But "implemented" and "implemented correctly" diverge sharply below — see rows 4-9. |
| 2 | Architecture | For the things the PRD deliberately left open, did the Architect make a *reasoned, stated* decision, or silently pick something without acknowledging the ambiguity? | Silent. `SpecificationJSON.description` was collapsed to one generic sentence — none of the PRD's Business Requirements/Constraints/Open Design Questions prose survived into the Architect's own output description. The five open questions were never enumerated or flagged anywhere in `specification`; they were answered later (or not) by whichever downstream agent happened to touch that concern, with zero cross-referencing. |
| 3 | Database | Schema, FK to `employees`, indexes — correct and justified? | Schema itself is clean: correct types, `FK_LeadCaptures_Employees → employees.employeeId`, sensible indexes on `companyId`, `assignedTo`, `status`, `leadSource`, `interestArea`, `created_At`. No `active`/soft-delete column (reasonable — nothing in the PRD asked for it). |
| 4 | companyId / tenancy | **Outcome B, confirmed.** `companyId INT NOT NULL` in `CREATE TABLE`, no FK, no acknowledgment of the PRD's explicit statement. `prd_enricher`'s `domain_context.business_rules` asserted `"companyId is required for multi-tenant isolation"` as a blanket rule (`matched_module: "leadcapture"` — TIER_1_CATALOG default, not a real lookup match) and the Architect carried it through unquestioned. Confirmed at Backend (public endpoint accepts `companyId` from an anonymous caller) and Frontend (`PublicLeadCreatePayload.companyId: number`, required) too. |
| 5 | Backend — public endpoint security | **Confirmed gap, exactly as hypothesized.** `public_lead_submission_connector` has: no rate limiting, no CORS restriction, no payload-size cap, no bot/spam mitigation — nothing. It reads like an ordinary internal CRUD function with the auth dependency removed, not like code written by anyone who considered "this is reachable from the open internet." Likely structural, not just an oversight: the Backend Agent only emits two files (`modules/{plural}.py`, `routes_/{module}.py`); CORS and rate limiting are `main.py`/middleware-level concerns outside that file scope, so the current per-module generation contract may not have anywhere to put an answer even if the LLM wanted to. |
| 6 | Backend — internal-field protection | Partially good. `allowed_fields` in `public_lead_submission_connector` correctly excludes `status`, `assignedTo`, `created_At`, `updated_at` — status is hardcoded to `"new"` server-side. But the same allow-list includes `companyId` (row 4), which is the one field that actually matters for tenant isolation. |
| 7 | Duplicate handling | **Answered, then quietly broken by row 4.** Database Agent added `UNIQUE NONCLUSTERED INDEX UQ_LeadCaptures_email_companyId ON (companyId, email)` and `sp_leadCaptures` explicitly checks for and rejects a duplicate `(companyId, email)` with the message `"Lead with this email already exists for this company."` — a real, legible, unprompted design decision for an open question, and a good one *if* `companyId` were trustworthy. Because the public endpoint accepts client-supplied `companyId`, the uniqueness check is trivially bypassed by varying `companyId` per submission — and, worse, an anonymous caller can *probe* which `(companyId, email)` pairs already exist across tenants by reading the duplicate-vs-inserted response, which is a real cross-tenant information leak neither agent could see because neither had visibility into the other's decision. |
| 8 | Status lifecycle | **Unaddressed.** `status NVARCHAR(50) NOT NULL DEFAULT 'new'`, no `CHECK` constraint, no transition validation in `sp_leadCaptures`'s `UPDATE` branch (`status = p.status`, unconditionally) or anywhere in Python. Any caller of the standard `/leadCaptures` update path can set `status` to any string and jump between any two values (`converted` → `new` included). Open design question #3 was not answered — not even partially. |
| 9 | Assignment / audit | **Partial, and inconsistent.** `assign_lead_connector` does call `observability.log_audit(entity="LeadCapture", entity_id=..., field="assignedTo", old_value=..., new_value=..., action="UPDATE_ASSIGNMENT")` — a genuine, correct use of this repo's audit mechanism (Core Rule #6 compliance), and a real answer to open question #4 for that one path. But status changes and any other field edit made through the generic `/leadCaptures` update endpoint bypass `log_audit` entirely — only the dedicated assign path is audited, so "was this lead's status ever changed, by whom" still has no answer. |
| 10 | Validation | Minimal but present: `privacyConsentAccepted` is checked and required (400 if falsy); email gets a crude length/`@`/`.` check. No normalization (case, whitespace) anywhere despite the PRD field note asking for consistent normalization — which directly undermines the row 7 duplicate check too (two emails differing only by case would not collide). |
| 11 | Pagination / API consistency | No real pagination anywhere — `all_leadCaptures_sp` returns every row for the company in one shot (matches this repo's existing convention for other modules, as far as could be observed; this codebase doesn't appear to do true cursor/page-based server pagination). Frontend's `IonInfiniteScroll` is client-side chunking over that full result set, consistent with `LoanChatPage`-style existing pages. Not a leadCapture-specific gap. |
| 12 | Frontend completeness | Implemented: list with status badges, `useIonViewWillEnter` refetch, `IonSelect` filters, detail page with status-change and assign-to selects. Uses `useUser()` (not `AuthContext`), `Header`/`AlertPopover`/`MailPopover`, matching the established frontend conventions. One concrete bug from an inter-file mismatch: `res.ok` is used to detect API errors, but `leadCaptures_sp` always returns HTTP 200 (embedding `error`/`msg` in the JSON body per this repo's existing SP-response convention) — so a duplicate-lead rejection (row 7) would read as a *successful* submission in the UI. Each side follows its own local convention correctly; the combination is wrong. |
| 13 | Tests | None generated — confirmed there is no test-generation stage in this pipeline at all (see "Known-in-advance facts"). Not a leadCapture-specific finding. |
| 14 | Reviewer blind spots | **Could not be evaluated as originally scoped — see row 15.** In principle every one of rows 4-11 would have sailed past the reviewer's checklist even if it had run, since none of those categories exist in `agents/reviewer/rules.py`. |
| 15 | Failure mode | **A reliability gap, separate from the code-quality findings above.** `review_result` in the final session state is still the untouched seed value (`"{}"`), and `review_fixer_result` (the `review_fixer_agent`'s declared `output_key`) never appears in state at all. Both are consistent with the `review_fix_loop` (reviewer → loop_exit → review_fixer, ×3) never productively running the deterministic `run_review` tool in this session — i.e., **the "pipeline only proceeds if all scores ≥ 90" gate does not appear to have actually executed**, meaning the artifacts evaluated above were generated but never scored. This needs its own targeted follow-up (rerun with per-event logging) before trusting the reviewer stage at all — and it retroactively validates skipping `pr_agent` for this run, since an ungated push to real GitHub repos would have gone out otherwise. |

## Prioritized takeaways for Experiment 2

Ranked by how much they'd change the outcome if fixed, not by how easy they are:

1. **`companyId` on a public, unauthenticated endpoint is a real vulnerability, not a style nit** — it lets an anonymous caller write into (and, via the duplicate check, partially enumerate) any tenant's data. This is the single highest-value fix.
2. **The reviewer loop's non-execution (row 15) has to be understood before anything else is trusted** — if the gate isn't running, no amount of prompt tuning elsewhere is verifiable.
3. **Requirements/constraints text doesn't survive into the Architect's own output** (row 2) — `prd_hints.backend_endpoints[].description` did carry through faithfully to the Backend Agent (rows 6, 9, 10 show it was read and partially acted on), so the PRD→agent information path works; what's missing is the Architect surfacing *unresolved* questions instead of silently discarding them.
4. **Status lifecycle (row 8) has zero enforcement anywhere** — the cheapest of the open questions to at least partially close (a `CHECK` constraint or an allow-listed transition table).

## Next step

Feed only the confirmed weaknesses above back into agent prompts / `decision_gate` rules / `reviewer` checks for Experiment 2, per the improvement loop:

```
Experiment 1 → observed gaps → improve agents/prompts/validators → Experiment 2 → compare
```

Don't fix these by hand-patching the generated `leadCapture` files — the point is to improve the factory, not this one output.

## Addendum — Phase 1 investigation: why did the review loop not fire?

Before touching any agent prompt, we investigated row 15 (the reviewer never actually scoring this run) directly, per the principle that a broken verification step would make Experiment 2 unfalsifiable. Findings, from three runs of the *identical* PRD through the *identical* code:

- **Run 1 (this document's findings above):** `review_result` stayed at its seed value all the way through — `run_review()` was never invoked.
- **Run 2 (event-level instrumentation added):** confirmed directly from raw ADK events — `reviewer_agent` and `loop_exit_agent` produced completely empty turns (no tool call, no text) on all 3 loop iterations; `review_fixer_agent` hit `MALFORMED_FUNCTION_CALL` on all 3. The *same* failure mode also hit `prd_enricher_agent` and `database_agent` earlier in that run — the latter with no fallback, so `database_artifacts` came back empty, worse than Run 1.
- **Run 3 (after adding `pipeline_diagnostics.py`, see below):** the review loop actually ran and *passed* (`database: 100, backend: 100, frontend: 90`) — but only after silently absorbing 7 failed/empty turns first (`prd_enricher_agent`, `design_consistency_agent`, `backend_agent`, `fixer_agent`, `reviewer_agent` ×2, `loop_exit_agent` ×2).

**Conclusion: this is not a wiring bug in `review_fix_loop`.** An isolated run of the loop alone (short conversation context) executed perfectly every time. The failure is `gemini-2.5-flash` tool-calling reliability degrading — non-deterministically, not at a fixed stage — as the shared conversation history accumulates across `root_agent`'s single continuous session. It affects any single-tool-call LLM agent in the pipeline (`fixer_agent` and `reviewer_agent` are LLM agents wrapping one tool call each, despite their own docstrings saying "no LLM involved" — only `decision_gate_agent` is genuinely pure Python), not just the review stage.

**The three runs produced three qualitatively different outcomes from the same input**, which is the real headline: without visibility into this, a single successful-looking run (like Run 3's clean pass) is not distinguishable from a run that got lucky on retries, and a single bad run (Run 2's empty `database_artifacts`) is not distinguishable from a genuine prompt/architecture defect. Comparing Experiment 1 vs. Experiment 2 without this signal risks reporting "the agents got better" when what actually happened is "this run got luckier."

**Change made:** `pipeline_diagnostics.py` (new) classifies every event for empty LLM turns / malformed tool calls; `orchestrator.py`'s `run_factory` now attaches `pipeline_diagnostics` (the flagged list) and `pipeline_diagnostics_summary` (counts per agent) to the saved session state, and prints each one live during a run. This is purely observational — no agent behavior, retry logic, or prompt was changed. Any future run (including Experiment 2) now carries its own reliability signal instead of requiring manual event-log archaeology.

**Deliberately not done yet:** reducing the accumulated context per agent, adding retries on empty/malformed turns, or picking a different model for the mechanical single-tool-call agents. All three are plausible fixes for the underlying flakiness, but doing them before this visibility layer existed would have made it impossible to tell whether a fix actually worked or the next run just got lucky.

## Experiment 2 — same PRD, same factory, diagnostics on

No agent, prompt, or `decision_gate`/`reviewer` code changed between this run and Experiment 1 — the only difference is `pipeline_diagnostics` now runs live. This is a same-condition replicate, not a "did the agents get better" test (nothing was changed for them to get better at).

**Reliability, self-reported this time instead of reconstructed after the fact:** `pipeline_diagnostics_summary` = 8 flagged events — `prd_enricher_agent` (1 `MALFORMED_FUNCTION_CALL`), `design_consistency_agent` (1 empty turn), `reviewer_agent` (3 empty turns), `loop_exit_agent` (3 empty turns). The review loop went 0-for-3 again — `review_result` stayed at the seed value, `review_loop_iteration` never incremented. Across the four runs of this identical PRD so far (1, 1B, 1C, 2), the review loop has produced a real score exactly **once**. `database_artifacts`/`backend_artifacts`/`frontend_artifacts` were all populated this time (no repeat of Run 1B's total data loss).

**A failure mode the diagnostics classifier doesn't catch, found by reading the artifact instead of the log:** `review_fixer_result` has real content this run — but it's a free-form prose summary of the artifacts, not the output of calling `apply_review_fixes` (the one tool its instruction says it must call). `classify_event()` didn't flag this because the turn had text and a state write; it just wasn't the *right* text. "The agent did something observable" and "the agent did what its instruction required" are different checks, and right now only the first one is automated.

**The companyId finding reproduced, and got more specific, not less:**
- `CREATE TABLE` this run added `CONSTRAINT FK_LeadCaptures_Companies FOREIGN KEY (companyId) REFERENCES dbo.companies(companyId)` — a real foreign key Experiment 1's version didn't have. A stronger tenancy assumption than last time, not a weaker one.
- The public submission function (`public_leadCapture_sp`) this run contains its own explanation, in a comment, of exactly the problem: *"companyId is required for multi-tenancy. For public unauthenticated leads, it should either be passed from the frontend (e.g., from a hidden field on the form) or inferred by the API gateway. Assuming it's present in the payload or handled by upstream logic before this function."* — then enforces it as a hard 400-if-missing requirement on the anonymous request body anyway.
- The assign function's comment is sharper still: `# companyId should come from the authenticated user context, not body.` — followed immediately by `company_id = payload.get("companyId")`, reading it from the body anyway. The model articulated the correct architectural principle and then didn't apply it.
- Frontend's public-create payload still includes `companyId` as a field the caller must supply.

This is a more informative result than a clean repro would have been: it rules out "the agent just doesn't know better." It knows the correct principle articulately enough to write it as a code comment. Whatever's missing is between knowing the rule and acting on it in the same generation pass — closer to a self-correction / verification gap than a knowledge gap.

**What varied between runs (same PRD, same prompts, different sample):**
- *Improved:* email is now normalized (`lower().strip()`) and regex-validated in the public endpoint — Experiment 1's email-normalization gap (row 10) is fixed in this sample. A `_filter_sensitive_data()` redaction helper is used before logging the public submission.
- *Regressed:* `log_audit` is not called anywhere in this run's backend — Experiment 1's one clean audit-trail win (assignment changes logged via `observability.log_audit`) did not reproduce. This run's `assign_leadCapture_sp` only does a plain `logger.info(...)` line, and its exception handler logs the raw, unredacted payload (the redaction helper exists but isn't applied there).
- *Unchanged:* no status-transition validation anywhere, in either run.

**Takeaway:** individual code-quality findings from a single run (Experiment 1's specific list of what's good/bad) are a sample, not a fixed property of the factory — rerunning the identical input changed which specific things were done well or poorly, while the structural finding (companyId overriding the explicit business requirement on a public endpoint) reproduced consistently across both runs that got far enough to check it. That's the finding worth treating as reliable; the individual per-run scorecards are not, on their own, without more samples.

## Experiments 3-4 — targeted context, and the decision registry's first real use

**Verification layers added** (all standalone, none fed into any agent, none changing generation behavior):
- `agent_contracts.py` — did each agent execute its assigned tool / produce its `output_key`? Verdicts: `SATISFIED` / `CONTRACT_FAILURE` (tool never completed) / `ARTIFACT_FAILURE` (tool succeeded but the resulting state key is missing/empty/malformed) / `NOT_OBSERVED` (agent produced zero events all run).
- `requirement_trace.py` — traces 5 named requirements (companyId/tenancy, status/assignment, duplicate handling) through PRD → Decision → Database → Backend → Frontend. Verdicts: `PASS` / `FAIL` / `UNKNOWN` (no decision or PRD language addresses it — a genuine architectural silence) / `NOT_VERIFIABLE` (the artifact needed to check is missing — a tooling/execution gap, not an architectural fact) / `N/A`. **`UNKNOWN` and `NOT_VERIFIABLE` must never collapse into `PASS` or `FAIL`** — that distinction is load-bearing throughout everything below.
- `artifact_contracts.py` — did the artifact satisfy a specific construction obligation (e.g. "every custom PRD endpoint exists in the generated route file"), independent of any named business requirement.

**The reviewer artifact-presence invariant** (`agents/reviewer/rules.py`): before this fix, `run_review()` only ran a layer's checks `if db:` / `if be:` / `if fe:` — an empty/missing artifact skipped its checks entirely and defaulted to a score of 100. Caught live in a real run: `database_artifacts={}`, `backend_artifacts={}`, and `review_result` still reported `passed: true`. Fixed so a missing artifact scores `None` (never a number, never able to satisfy `passed`) and appears explicitly in `missing_artifacts`.

**Targeted context** (`agents/state_injection.py`): `reviewer_agent`/`loop_exit_agent`/`review_fixer_agent`/`fixer_agent` set `include_contents='none'` (their tools take zero arguments, read purely from session state — the full conversation history was pure bloat for them). `database_agent`/`backend_agent`/`frontend_agent` instead get `with_state(INSTRUCTION, [keys their own prompt already names])` — the exact state their prompt declares needing, inlined directly, plus `include_contents='none'` to drop the rest. This is context *selection*, not elimination; each of these three genuinely needs `specification`/`gate_result` (and `design_brief`/`backend_artifacts` for frontend) to do its job.

**The decision registry's first real decision — ADR-001 (tenant_model).** `decision_gate`'s tenant handling used to be `companyId INT NOT NULL` unconditionally, for every module, with no override. Replaced with `_classify_tenant_model()`: `TENANT_SCOPED` (default) / `TENANT_INDEPENDENT` / `TENANT_DERIVED` / `UNKNOWN` — and `UNKNOWN` now hard-blocks construction (`decision_gate` returns `status: BLOCKED`) instead of silently assuming `companyId` is required. `decision_registry.py`'s existing ADR persistence (already built for `debate_v2`, previously unused by the deterministic pipeline) was extended with `topic`/`constraints`/`appliesTo` and a `get_decision_for_topic(module, topic)` lookup, then ADR-001 was recorded: `TENANT_INDEPENDENT`, with explicit constraints forbidding the public endpoint from reading/defaulting/validating a client-supplied `companyId`.

**Result, verified zero-LLM-cost via `compute_gate_result()` directly, then confirmed in real generation (Experiment 4, 3 attempts):** with ADR-001 recorded, `gate_result.tenant_model = TENANT_INDEPENDENT`, `applicable_decisions: ["ADR-001"]`, and `mandatory_constraints.database` carries ADR-001's constraint text verbatim. Database Agent applied it and cited the ADR by id in its own SQL comment: `companyId INT NULL, -- ADR-001: Public submissions have no companyId, so it can be NULL`. REQ-002/REQ-003 Decision+Database verdicts: `FAIL` (Experiments 1/2) → `PASS` (Experiment 4). **Zero prompt changes** — `database_agent`'s existing prompt already said "apply every rule in gate_result.mandatory_constraints.database"; the fix worked entirely through the channel that already existed.

**Backend (the "critical test") took 3 attempts to even observe**, each lost to a different agent's `MALFORMED_FUNCTION_CALL`/empty-turn (`schema_analyst_agent`, `backend_agent`, then `database_agent`+`backend_agent` together) — execution reliability, not decision-propagation, confirmed by the fact these exact failures also hit agents nothing else had touched. One of those failures, discovered along the way: `review_result` scored `100/100/100, passed: true` with `database_artifacts` and `backend_artifacts` both `{}` — the reviewer invariant fix above exists because of this exact event.

## Experiment 5 — targeted context result, and a new gap it surfaced

With targeted context live, `backend_agent` and `frontend_agent` both completed successfully for the first time in this whole sequence (`database_agent` still failed — 2/3, not 3/3, on this one sample). But the successful `backend_artifacts` **omitted both custom endpoints entirely** (`/leadCapture/public`, `/leadCapture/{id}/assign`) despite `specification.prd_hints.backend_endpoints` containing them, complete and correct, inlined directly into `backend_agent`'s own instruction. Traced to the actual root cause, not inferred: `agents/backend/prompt.py` never references `prd_hints.backend_endpoints` in any form, and `decision_gate._classify_backend_pattern()` only forwards a custom endpoint into `gate_result` when it matches a connector-service keyword — a plain custom REST action (neither standard CRUD nor connector-flavored) is silently discarded at that exact line, before `backend_agent` ever runs. There was never a contract; every prior success (Experiments 1/2/3) was the model noticing the buried JSON on its own initiative. `artifact_contracts.check_backend_endpoint_completeness(prd, backend_artifacts)` now checks this directly (`required`/`found`/`missing`/`status`) against every future run, checked against the **PRD directly**, not the specification copy.

## Experiment 6 — ADR-002 (duplicate_policy): a behavioral, per-layer decision

Unlike `tenant_model` (one fact, near-identical constraint text per layer), duplicate handling needs genuinely different obligations per layer — `decision_registry.record_decision()` gained `layer_constraints: dict[str, list[str]]` alongside the existing flat `constraints` (mutually exclusive; supplying both raises `ConflictingConstraintsError` rather than silently picking one), normalized by `get_effective_constraints()`. `decision_gate` gained one small **generic** propagation loop — `_apply_generic_decisions()` — instead of a second bespoke `_classify_duplicate_policy()`: every recorded decision except `tenant_model` (which keeps its existing, tested, specialized block-on-`UNKNOWN` logic untouched) flows through this one path. No future decision topic should ever require new `decision_gate` code.

ADR-002 recorded: `REJECT_NORMALIZED_EMAIL`, with distinct `database`/`backend`/`frontend` constraints (normalize+unique-constrain at the DB layer; inspect the SP's embedded `error` field and return non-2xx at the backend layer; don't rely on `res.ok` alone at the frontend layer). Verified zero-LLM-cost first: `gate_result.applicable_decisions` contains both ADR-001 and ADR-002 with no cross-contamination, `mandatory_constraints.{database,backend,frontend}` each carry exactly their own layer's constraint text.

**Real generation:** only `backend_agent` survived this run (`database_agent`, `frontend_agent` both hit `MALFORMED_FUNCTION_CALL` — an execution failure, reported as `NOT_VERIFIABLE`, never coerced into `FAIL`). Backend's result is the strongest evidence so far — genuinely *new control flow*, not merely an omission fixed:

```python
result = json.loads(json_result)
# ADR-002: Inspect embedded result.error for duplicate rejection
if isinstance(result, dict) and "error" in result:
    if "duplicate" in result["error"].lower() or "unique constraint" in result["error"].lower():
        return JSONResponse(content=result, status_code=409)  # Conflict
    return JSONResponse(content=result, status_code=400)  # Bad Request
return JSONResponse(content=result, status_code=200)
```

Cited ADR-002 by id in its own comment, correctly distinguishing duplicate-flavored errors (409) from other errors (400) from success (200) — synthesized from prose constraints alone. Verified via a dedicated artifact contract (`check_backend_duplicate_error_propagation`, not just the requirement-trace text scan — that scan's original regex was tuned to older code shapes and would have returned a false `FAIL` here; fixed to check for the concept, not one exact syntax, and re-verified against Experiments 1/2 to confirm no regression). REQ-005 Backend: `FAIL` (Experiments 1/2) → `PASS` (Experiment 6). Database and Frontend remain unobserved, not failed — this run is preserved as evidence (`experiment6_run1_state_PRESERVED.json`) rather than risked to an overwrite, before any retry.

**State of evidence, precisely:**

| Layer | Decision | Construction execution | Verification |
|---|---|---|---|
| Database | PASS (ADR-002 present) | not observed (MALFORMED_FUNCTION_CALL) | NOT_VERIFIABLE |
| Backend | PASS | PASS | **PASS** |
| Frontend | PASS (ADR-002 present) | not observed (MALFORMED_FUNCTION_CALL) | NOT_VERIFIABLE |

Custom-endpoint omission (Experiment 5's finding) reconfirmed in this same run, unrelated to ADR-002 — a separate, independent, stable gap.

## Experiment 6 retry — the complementary layer, and a tool-consistency bug

One controlled retry, saved separately (`experiment6b_state.json`) rather than overwriting run 1. Result: `database_agent` failed again (`MALFORMED_FUNCTION_CALL` — its 2nd failure in 2 Experiment-6 attempts, the most consistent failure of the three targeted-context agents on this PRD so far), `backend_agent` also failed this time, but **`frontend_agent` succeeded** — exactly the layer missing from run 1. Quality was excellent and citation-explicit:

```typescript
// Per ADR-002, check for embedded error even if res.ok is true
const result: LeadCaptureActionResponse = await res.json();
if (!res.ok || (result.result && result.result.error)) {
    throw new Error(result.result?.error || res.statusText);
}
```

This run's frontend also independently reconfirmed ADR-001, unprompted by anything in this experiment specifically: `getAllLeadCaptures()` takes no `companyId` parameter at all (comment: `"modified to remove companyId as per ADR-001"`), and the `LeadCapture` interface itself no longer declares a `companyId` field — stronger compliance than any earlier run, which had at least kept a nullable `companyId` field around.

**A tool-consistency bug caught before reporting:** `artifact_contracts.check_frontend_duplicate_error_handling` correctly scored this `SATISFIED`, but `requirement_trace._req005_frontend` — built earlier, checking for the same fact a different way — incorrectly required the literal word `"public"` to appear in the file before crediting an embedded-error check, a leftover assumption from when the custom public endpoint was expected to exist. Since it doesn't this run (the endpoint-omission gap, again), the check fell through to `FAIL` despite the real embedded-error logic being right there in `createLeadCapture()`. Fixed to check for the concept everywhere in the file, not gated on a function name; re-verified against Experiments 1/2 (still correctly `FAIL` — no regression) and both Experiment 6 runs.

**Combined picture across both Experiment 6 attempts** (not from a single run — no run has produced all three layers together yet):

| Layer | Decision | Construction execution | Verification |
|---|---|---|---|
| Database | PASS (ADR-002 present) | not observed, 2/2 attempts | NOT_VERIFIABLE |
| Backend | PASS | PASS (run 1) / not observed (retry) | **PASS** (run 1) |
| Frontend | PASS (ADR-002 present) | not observed (run 1) / PASS (retry) | **PASS** (retry) |

Backend and Frontend have each independently demonstrated correct ADR-002 implementation once. Database has not yet been observed executing at all under ADR-002 — 0/2, the clearest concentration of execution-reliability risk remaining for this PRD. Per explicit decision: not fixing this now — preserving the observation, not chasing a third attempt for its own sake.
