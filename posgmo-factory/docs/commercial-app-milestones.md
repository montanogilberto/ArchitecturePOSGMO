# Commercial App — Milestones

Phase 2 of the commercialization plan (docx: "Commercial Foundation"): using the
now-hardened Software Construction Factory (see
`docs/experiment1-leadCapture-evaluation.md` for the full leadCapture experiment
series) to build Factory AI GMO's own commercial platform, one module at a time,
starting with the dependency order the leadCapture/organization work surfaced:
`factoryAccount` (identity) before `organization` (workspace) before anything
that depends on an owner existing.

## Milestone 1 — factoryAccount tenant-model generalization

**Question:** does the decision-gate mechanism built for `leadCapture`'s
`companyId` defect (ADR-001, `_classify_tenant_model`, the `UNKNOWN`-blocks-
construction invariant) generalize to a brand-new module it was never built
for, or was it a one-off fix specific to `leadCapture`?

**Input:** `tests/prd_factoryAccount.json` — a new commercial-platform module
(account/identity), deliberately written with the same tenancy-exception
language as `leadCapture`, targeting a codebase confirmed live to be
multi-product (POS, SmartLoans, Rewards, Arcade — `users.appProfile='loans'`
found in production data) rather than POS-exclusive.

| Test | Result |
|---|---|
| `leadCapture` + ADR-001 (regression check) | ✅ Existing behavior preserved |
| `factoryAccount` without a recorded decision | ✅ Correctly `BLOCKED`, `tenant_model=UNKNOWN` |
| `factoryAccount` + ADR-003 recorded | ✅ Correctly `APPROVED`, `tenant_model=TENANT_INDEPENDENT` |
| ADR-003's layer-specific constraints | ✅ Propagated to the correct layer each — database/backend/frontend, not conflated |
| Zero-LLM gate verification (`compute_gate_result` called directly) | ✅ Passed before any real run was spent |
| Full test suite | ✅ 128/128 |
| Real pipeline, decision layer | ✅ `applicable_decisions=['ADR-003']`, correct constraints reached `gate_result` |
| Real pipeline, construction artifacts | ❌ `database_agent`, `backend_agent`, `frontend_agent` all failed (`MALFORMED_FUNCTION_CALL` ×2, empty turn) |

**The load-bearing evidence:** the factory did not guess a tenant model for a
module it had never seen before. It hit a genuine architectural ambiguity
(no existing companyId relationship + an unauthenticated public write path),
represented that as `UNKNOWN`, blocked construction rather than silently
defaulting, then — once given an explicit decision — propagated that
decision's *specific* constraints into the *correct* construction layers.
That is the decision-layer behavior the mechanism was designed to have, now
demonstrated on a second, independently-authored module.

**A real bug, found and fixed by this same discipline, before it reached a
real run:** `compute_gate_result`'s tenant-decision handling originally read
a decision's flat `constraints` field only. ADR-001 (leadCapture) was
authored with flat constraints, so it worked. ADR-003 (factoryAccount) was
authored with `layer_constraints` (a per-layer dict — the more precise
authoring pattern `ADR-002`/duplicate_policy introduced) — and the old code
silently ignored it, unblocking construction with none of ADR-003's actual
constraints attached. Fixed by routing the tenant-decision path through the
same `decision_registry.get_effective_constraints()` normalizer every other
decision already uses, rather than patching factoryAccount's authoring to
match the old code's narrower expectation. Verified fixed via zero-LLM gate
checks on *both* ADR-001 and ADR-003 before spending the real run that
confirmed it end-to-end — changing the generic mechanism, not special-casing
the new module, was deliberate: it's what makes the ADR-001 regression check
meaningful evidence rather than an assumption.

**Conclusion — two separate findings, not one:**

- **Decision/architecture layer: validated.** Generalizes correctly to a new
  module. Blocks on genuine ambiguity. Propagates precisely once resolved.
- **Construction layer: known, independent reliability limitation.** All
  three generation agents failing in the same run does not weaken the
  decision-layer finding above — it's the same reliability characteristic
  already identified and partially addressed (targeted context,
  database/execution separation) for `leadCapture`, now observed hitting a
  different module. Retrying until all three happen to succeed would mostly
  measure API-call stochasticity, not learn anything new about the
  architecture — so this was deliberately not done. The experiment answered
  the question it was designed to ask.

**Decisions recorded this milestone:** `ADR-003` (`decision_registry/ADR-003.json`)
— `factoryAccount` / `tenant_model` / `TENANT_INDEPENDENT`.

**Not yet done, by design:** applying any generated artifact to a real
repository. Every run in this milestone (like every run in the leadCapture
series) stayed local/sandboxed, `pr_agent` excluded.

## Milestone 2 — organization: clean pass, no ADR needed, and a second calibration bug caught

**Input:** `tests/prd_organization.json` — the workspace/tenant entity, correctly
sequenced after `factoryAccount` since an Organization needs an owner.
Updated before running to reflect that `factoryAccount` now exists as a
*designed* module (ADR-003) even though its table isn't live yet (construction
reliability, not an architectural gap) — the PRD's `ownerEmail` field and
Open Question #1 were rewritten to say so precisely, not left stale.

**A tenancy classification gap found before spending anything real:** the
first draft of `organization`'s PRD described the tenancy exception only in
free prose ("must not be confused with... POS GMO's own existing retail
tenants") — none of `_classify_tenant_model`'s recognized trigger phrases
appeared in it, so it silently classified as `TENANT_SCOPED` (would have
required a `companyId`, the exact defect this whole thread exists to catch —
on a module that is *itself* a competing tenant concept to POS GMO's
`companies` table). Fixed by rewording the constraint to state plainly that
an Organization "has no existing companyId relationship" and "must never be
given a companyId" — re-verified zero-cost before running: `TENANT_INDEPENDENT`,
directly, no `UNKNOWN`/block needed at all, since `organization` (unlike
`leadCapture`/`factoryAccount`) has no public write path creating ambiguity
about *how* tenant-independence should be handled — just whether it applies.

**Real run result:** `database_agent` failed (`MALFORMED_FUNCTION_CALL`,
consistent with its established reliability profile) but **`backend_agent`
and `frontend_agent` both succeeded (100/100)** — the first real, complete
backend+frontend artifacts for a module other than `leadCapture`.

- Backend: zero mentions of `companyId` anywhere.
- Frontend: the *only* mention is a comment explaining its deliberate
  absence — `body: JSON.stringify({}), // companyId is NOT applicable` —
  citing the constraint text verbatim. Full compliance, not a near-miss.

**A second calibration bug, caught the same way as the first:** the
duplicate-handling artifact contracts (`check_backend_duplicate_error_propagation`,
`check_frontend_duplicate_error_handling` — built for `leadCapture`'s ADR-002)
were wired into `orchestrator.py` unconditionally, and fired `ARTIFACT_FAILURE`
against `organization`, which has no duplicate-policy requirement or decision
at all. Fixed by gating both checks on whether `gate_result.applicable_decisions`
actually contains a `duplicate_policy`-topic decision for this module; returns
`N/A` otherwise. Re-verified against both `leadCapture` (still fires, has
ADR-002) and `organization` (now correctly `N/A`). 128/128 tests pass.

**Conclusion:** third module, cleanest pass yet, no manual ADR required —
the heuristic alone resolved the tenancy question correctly once the PRD
used recognizable language. Construction reliability remains the same known,
independent limitation (`database_agent` again), unaffected by any of this
milestone's fixes, consistent with Milestone 1's conclusion that the two
layers shouldn't be conflated.

## Milestone 3 — project: correct classification on the first try, and a genuine backend naming defect (not a calibration bug)

**Input:** `tests/prd_projects.json` — the workspace-scoped container that will
later hold Factory Runs, correctly sequenced after `organization`. Written
with the tenancy-independence phrasing already learned from Milestone 2's
classification gap, and reusing the same "plain reference field, not a
foreign key" pattern for `organizationSlug` that `organization` itself used
for `ownerEmail` against `factoryAccount` — because `organizations` is
likewise a validated design, not a live table yet.

**Classification: correct immediately, no fix-and-reverify cycle needed
this time.** Zero-LLM check before spending anything real:
`_classify_tenant_model` → `TENANT_INDEPENDENT`, no ADR required — the
lesson from Milestone 2's gap was applied at authoring time instead of
discovered after the fact.

**A previously-built safety mechanism fired for real, for the first time:**
`gate_result.warnings` contains `"PRD references 'organizations' but it was
not found in the DB -- will not be generated."` — `decision_gate` correctly
detected that `organizationSlug` conceptually references a table that
doesn't exist live and refused to invent one or silently treat it as a
formal FK, exactly the behavior this was designed for (see Milestone 2,
Open Question #1). This is the first run where that specific guard actually
triggered rather than being merely reasoned about.

**Real run result:** `database_agent` failed again (`MALFORMED_FUNCTION_CALL`,
same established profile). `frontend_agent` scored 100. **`backend_agent`
scored 80 — the first backend failure in this module series, and a genuine
one, verified by reading the actual generated code, not a reviewer
calibration bug:**

```
@router.post("/one_project", ...)      # generated
def one_project(json: dict):
    return one_projects_sp(json)        # calls the plural-named SP correctly
```

The reviewer's contract requires `POST /one_projects` (plural) — matching
the pattern the same file used for its other two endpoints
(`/projects`, `/all_projects`) and matching the plural module import
(`one_projects_sp`). The model used the natural-English singular
("one project") for just this one route while getting the plural-based
SP call and its sibling endpoints right. This is a real, isolated backend
generation defect — not a false positive like Milestone 2's duplicate-policy
gating bug. Confirmed by direct inspection of `backend_artifacts.route_file`
before writing this down, per this project's standing discipline of not
trusting a FAIL or a PASS without checking the underlying artifact.

**Conclusion:** decision layer — correct on the first attempt, and its
invented-table guard confirmed working under real conditions for the first
time. Construction layer — same known `database_agent` reliability limit,
plus a new, narrower finding: single-endpoint singular/plural naming drift
in `backend_agent`, distinct from (and much smaller than) the missing-table
class of defect. Not fixed here, consistent with this thread's standing
decision to treat construction-layer reliability as a separately-tracked,
not-yet-urgent problem — recorded so it isn't lost.

**Not yet done, by design:** applying any generated artifact to a real
repository. This run used the same hard pr_agent removal pattern as
`run_local_export.py` (not just prompt-based self-gating) — `pr_agent` was
stripped from `root_agent.sub_agents` before execution, so no GitHub call
was structurally possible regardless of review outcome.

## Milestone 4 — pricingPlan: off the authenticated dependency chain, first public *read* endpoint, and two real classifier bugs found by actually reading the artifacts

**Input:** `tests/prd_pricingPlan.json` — not on the Account → Organization →
Projects → Factory Runs → ... dependency chain at all. It's the public
marketing Pricing page's data catalog, from the docx's separate "Commercial
Product Scope" list. Deliberately the first module in this series whose only
public endpoint is a **GET** (`/pricingPlan/public`), not a POST — every prior
public-surface module (`leadCapture`, `factoryAccount`) had a real public
write. Written with the same tenant-independence phrasing organization/project
already learned to use, plus its own open questions (link to
`organization.plan`'s unspecified value-set; whether generating a genuinely
public, unauthenticated page is even in scope for `frontend_agent`'s
established authenticated-page pattern).

**Bug #1, found before spending anything real:** zero-LLM check
(`_classify_tenant_model` called directly) returned `UNKNOWN` — wrong.
`agents/decision_gate/rules.py`'s `has_public_write` flagged the endpoint as
an unauthenticated *write* purely because its path/description contained the
words "public" and "unauthenticated" — it never checked `ep.get("method")` at
all. Every prior module happened to have a real public POST, so this gap
never showed up before. Fixed by requiring the endpoint's method to actually
be `POST`/`PUT`/`PATCH`/`DELETE` (missing `method` still defaults to `POST`,
same as `PRDEndpoint`'s own pydantic default — fails conservatively toward
blocking, not toward silently passing). Regression-checked against
`leadCapture`/`factoryAccount` (still correctly `UNKNOWN` — their POSTs are
real), `organization`/`projects` (unaffected, no public endpoints), `supplier`
(unaffected, no tenancy language). Full suite: 128/128. `pricingPlan` now
resolves `TENANT_INDEPENDENT` directly — no ADR needed, same clean-pass shape
`organization` and `projects` got once their own gaps were closed.

**Real run #1 result (fix #1 only):** gate `APPROVED`. `database_agent`
*succeeded* for the first time in this entire series (every prior module hit
`MALFORMED_FUNCTION_CALL`) — and, read directly from the generated SQL, it
correctly emitted a table and SPs with **zero `companyId`**, honoring the
`TENANT_INDEPENDENT` design faithfully. But review still **FAILED**:

| Layer | Score | Why |
|---|---|---|
| Backend | 100 | — |
| Frontend | 80 | `IonInfiniteScroll` missing despite `has_list_view: true` |
| Database | 0 | 14 auto-errors: missing `companyId`, missing `@pjsonfile`, missing `WHERE companyId` filter, missing transactional `sp_upsert` structure, wrong `ROOT()` naming, etc. |

**Bug #2, root-caused by reading the gate output, not guessed:** `[gate]`
logged `tier=TIER_4_IOT` — wrong; `pricingPlan` is a textbook
`TIER_2_FINANCIAL` module (monetary `priceMonthly`/`priceYearly`).
`_TIER4_SIGNALS` contains the bare substring `"led"` (meant for "LED"
hardware), matched via unanchored `kw in text` containment. Confirmed exactly
which words in the PRD's own prose triggered it: `billed`, `controlled`,
`decoupled` — any word ending "-led" false-positives. This directly explains
the frontend failure too, not a second independent defect:
`agents/decision_gate/rules.py`'s `TIER_4_IOT` branch injects
`"Chart/graph view — no IonList."` as a mandatory frontend constraint, so
`frontend_agent` correctly followed instructions and omitted the list
components reviewer then flagged as missing. One root cause, two visible
symptoms. (`review_fixer` correctly skipped every issue this run — its scope
is 4 narrow regex patterns unrelated to either bug; confirmed by reading
`agents/review_fixer/rules.py`, not a bug.)

Fixed with `_has_any_whole_word()` — same as the existing `_has_any` but
requires `\bkeyword\b`, not substring containment — wired into both
`_TIER4_SIGNALS` checks (the main test and the `azure_only` exception's
negation). Left every other `_has_any` call site (TIER_3 sales/line-items,
TIER_2 monetary words) untouched — no evidence they share this failure mode.
Regression-checked against `pricingPlan` (now `TIER_2_FINANCIAL`), a synthetic
genuine-hardware description (still correctly `TIER_4_IOT`), an Azure-only
false alarm (still `TIER_1_CATALOG`), and a second latent instance of the same
bug class — `"iot"` matching inside `"idiot"` — now also correctly not
triggering. Full suite: 128/128.

**Real run #2 result (both fixes applied):** `tier=TIER_2_FINANCIAL`,
confirmed correct. Frontend **80 → 100** — `IonList` and `IonInfiniteScroll`
both directly confirmed present in the regenerated TSX, not inferred from the
score alone. Backend stayed 100. Database this run: `N/A (missing)`, not 0 —
`database_agent` produced no output at all this run (the same stochastic
`MALFORMED_FUNCTION_CALL`-class reliability limitation documented in
Milestones 1-3, hitting a different module), and reviewer's artifact-presence
invariant (added after Experiment 4) correctly distinguished "never ran" from
"ran and failed checks" rather than conflating them into the same 0.

**A third finding, deeper than either bug fixed this milestone, deliberately
left open:** run #1's database score of 0 wasn't only about tier — read
directly, `agents/reviewer/rules.py`'s `_check_database` /
`_check_backend` / `_check_frontend` all receive `gate_result` as a parameter
but never reference `tenant_model` or `applicable_decisions` anywhere in the
file (confirmed by grep — zero other occurrences). Its `companyId` checks are
unconditional `auto_error`s. This means *no* `TENANT_INDEPENDENT` module can
currently pass review whenever `database_agent` succeeds and correctly omits
`companyId` — exactly what run #1 demonstrated. The decision and generation
layers both handled `tenant_model` correctly this milestone; the review gate
is where the mechanism currently breaks down. Not fixed here — whether
reviewer should skip its `companyId` checks for `TENANT_INDEPENDENT` modules
or flip them to assert `companyId`'s *absence* is a real design choice, not a
narrow bug, and affects every `TENANT_INDEPENDENT` module already in this
series (`factoryAccount`, `organization`, `projects`), not just `pricingPlan`.

**Conclusion:** two independent, real classifier bugs found this milestone —
both by reading actual code paths and actual generated artifacts, not by
assumption — fixed narrowly, and regression-tested at three levels (targeted
synthetic cases, the full existing PRD corpus, and a real end-to-end pipeline
run before/after). Construction-layer reliability (`database_agent`) remains
the same known, separately-tracked limitation as every prior milestone,
unaffected by either fix, consistent with this thread's standing decision not
to conflate decision-layer and construction-layer findings. A third, more
architecturally consequential gap (reviewer's `tenant_model` blindness) was
found in the process and intentionally left for its own milestone rather than
fixed reactively alongside these two.

**Decisions recorded this milestone:** none — `pricingPlan` reached
`TENANT_INDEPENDENT` cleanly via the classifier fix alone, the same clean-pass
shape `organization` and `projects` got once their own respective gaps were
closed. No ADR was necessary.

**Not yet done, by design:** applying any generated artifact to a real
repository (`pr_agent` excluded from both runs, same hard-removal pattern as
every prior milestone). Fixing reviewer's `tenant_model` blindness — scoped
as its own decision, not bundled into this milestone's two narrow bug fixes.

## Milestone 5 — factoryRun: first dependency-chain run after Projects

**Input:** `tests/prd_factoryRun.json` — Factory Run ledger (Project → Run record;
does not execute the pipeline or store artifact blobs).

**Reviewer fix (Milestone 4 follow-up):** `agents/reviewer/rules.py` now honors
`gate_result.tenant_model == TENANT_INDEPENDENT` — requires `companyId` absence
in CREATE TABLE and forbids `sp_all` `WHERE companyId` filters (see
`tests/test_reviewer_tenant_model.py`).

**Real run (local export + full orchestrator, `pr_agent` not applied on failure):**

| Layer | Result |
|---|---|
| Decision gate | ✅ `APPROVED`, `TENANT_INDEPENDENT`, `TIER_1_CATALOG` |
| Backend | ✅ 100 |
| Frontend | ❌ 80 — bare `CustomEvent` typing |
| Database | ❌ 60 — live SQL execution error on SP batch; snake_case PK (`factory_run_id` vs `factoryRunId`); `sp_all` still declares `@companyId` despite tenant-independent gate constraints |

**Artifacts:** `last_state.json`, `local_export/factoryRun/artifacts.json`,
`run_factoryRun.log`.

**Conclusion:** Commercial PRD is in the factory; decision layer classifies
correctly. Construction layer still mixes POS `companyId` patterns into
tenant-independent SQL and column naming — same reliability/theme as Milestones
1–4, now on the Factory Run module.

## Next

1. **Database agent + tenant-independent SQL** — generated `sp_all` must not
   read/filter `companyId` when `gate_result.tenant_model` is
   `TENANT_INDEPENDENT`; column names must match spec camelCase (`factoryRunId`).
2. **Artifacts / Usage / Billing** — next modules on the chain after Factory
   Runs. Carried-forward open questions: commercial-platform role model vs
   `AllowedRole`; slug/uniqueness policies on organization/project.
