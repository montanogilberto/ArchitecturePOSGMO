# GMO Agentic Application Roadmap

**Status:** canonical roadmap as of 2026-09-30. Supersedes
`docs/factory-knowledge-roadmap.md` (whose five phases are now treated as
completed groundwork — see [Relationship to earlier roadmaps](#relationship-to-earlier-roadmaps)).
`docs/commercial-app-milestones.md` remains the evidence log for individual
Factory runs.

## North Star

Build an agentic GMO ecosystem where applications understand goals, reason
over business context, create plans, execute actions through governed tools,
observe results, detect problems, and continuously improve — with the
Factory acting as the engineering system that creates and evolves those
capabilities.

The Factory therefore has two responsibilities:

1. **Build and evolve the applications** (POSVending, smartloans_backend,
   LoanAgents_SmartLoans, and later Laundry/Arcade/Commercial).
2. **Make the applications increasingly agentic.**

The goal is not to replace deterministic software:

> **Deterministic infrastructure + agentic reasoning above it.**
> Agents reason and coordinate. Tools perform controlled actions.
> Applications stay deterministic where determinism is appropriate.
> The human owns and approves important decisions.

## Principles every phase must hold to

1. **Prove before advancing.** A phase is done when its exit criteria are met
   against real repositories and real data — not when the code exists. Same
   discipline as `commercial-app-milestones.md`: read the actual output,
   don't chase a lucky pass, document what isn't proven.
2. **Vertical slices over horizontal layers.** Each capability is proven on
   one real feature end-to-end (plan → build → deploy → observe) before it is
   generalized. Inventory is the first slice.
3. **Agents never get database freedom.** Every action goes through a
   registered tool that calls an API → stored procedure. No agent writes SQL
   against production. (Extends Core Rule #4 to agents.)
4. **Every tool has an autonomy level** (below), and money-moving tools
   never exceed `EXECUTE_WITH_APPROVAL`.
5. **Tenant isolation is enforced by the tool, not trusted from the agent.**
   `companyId` comes from the authenticated session, never from LLM output.
6. **Everything is observable.** Every agent decision, tool call and
   proposal is reconstructable through `workflowId`/`correlationId` and the
   four log tables (see CLAUDE.md → Observability).
7. **Reasoning is measured.** No agent capability is called "done" without
   an evaluation set of fixed scenarios with expected decisions.
8. **MCP/Graph is the authoritative source of facts; RAG retrieves
   evidence.** (Carried over from the previous roadmap.)

## Target architecture

```
                 HUMAN / BUSINESS GOAL / INTENT
                              │
                              ▼
              ┌───────────────────────────────┐
              │          AGENTIC APP          │
              │ Understand → Reason → Plan →  │
              │ Decide → Act → Observe → Learn│
              └───────────────┬───────────────┘
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
      Knowledge            Tools              State / Memory
      (RAG + MCP)    (Tool Gateway → API → SP)  (session, experience)
           └──────────────────┼──────────────────┘
                              ▼
          Applications: POS · SmartLoans · Laundry · Arcade · Rewards
                              │
                              ▼
          Observability (workflowLogs · auditLogs · applicationLogs · integrationLogs)
                              │
                              ▼
          Events / Anomalies / Incidents
                              │
                              ▼
          Factory: plan → build → verify → PR → deploy → observe
```

### Agentic context

```
Knowledge   (what GMO knows: products, customers, rules, APIs, architecture)
+ Experience (what happened before: decisions, workflows, failures, corrections)
+ State      (what is happening now: cash register, inventory, orders, loans, tickets)
+ Intent     (what the business wants: sell more, reduce overdue loans, avoid stock-outs)
= Agentic Context
```

## Capability model

| Capability | Deterministic (today) | Agentic (target) |
|---|---|---|
| Understand request | Fixed UI / form | Understand intent |
| Find information | Fixed query | Retrieve relevant context |
| Decision | if/else | Reason over evidence |
| Workflow | Hardcoded sequence | Generated execution plan |
| Action | Fixed endpoint | Select the appropriate governed tool |
| Errors | Return error | Diagnose and recover |
| Monitoring | Logs | Observe + interpret |
| Improvement | Developer changes | Agent proposes improvement |
| User support | FAQ | Context-aware support agent |
| Business operations | Manual / cron | Proactive recommendations |
| Development | Hand-coded | Factory plans and generates changes |

## Maturity model

| Level | Application behavior |
|---|---|
| L0 | Manual |
| L1 | Deterministic |
| L2 | Context-aware |
| L3 | Agent-assisted (agent proposes, human executes/approves) |
| L4 | Reasoning (agent explains situations from evidence and plans) |
| L5 | Proactive (application initiates workflows) |
| L6 | Self-improving (production feedback drives Factory changes) |

### Current assessment (2026-09-30)

| Application | Level | Evidence |
|---|---|---|
| POSVending | **L3** in support chat, L1 elsewhere | `pos_*_support` agents propose writes via `tools/pending_actions.py`; cashier confirms; backend executes |
| SmartLoans | **L2–L3** | risk / analysis / negotiation / lender / borrower agents assist; collections and reminders are deterministic APScheduler jobs (`smartloans_backend/main.py`) |
| Laundry (`menuLaundy`) | **L1** | no agents |
| Arcade / Rewards | **L1–L2** | `pos_rewards_support` only |
| Factory | **L3 in sandbox** | plans/decides well (decision gate, ADRs, RAG); 0 factory PRs merged into product repos; only open PR is `feat/factoryRunUsage-module` |

## Tool autonomy levels

Every tool registered for an agent declares one level. The level is enforced
by the tool gateway, not by the prompt.

| Level | Meaning | Examples |
|---|---|---|
| `READ` | Agent may call freely | `get_stock`, `get_monthly_income`, `get_customer_history` |
| `PROPOSE` | Agent drafts; a human must confirm in the UI before the backend executes | `create_client`, `inventory_adjust`, `create_expense` (today's `pending_actions` pattern) |
| `EXECUTE_WITH_APPROVAL` | Executes only after an explicit, logged approval by an authorized role | `send_whatsapp_campaign`, `create_purchase_order`, **all money movement** (SPEI, Stripe, disbursement, `walletTransactions`) |
| `AUTO` | Agent may execute without a human, within declared limits | `create_ticket`, `send_internal_notification`, `log_recommendation` |

Promotion of a tool to a higher level requires an ADR in `decision_registry/`.
Money-moving tools are capped at `EXECUTE_WITH_APPROVAL` permanently.

## Canonical Factory lifecycle

```
GOAL        What are we trying to accomplish?
DISCOVER    What already exists? (live schema, ecosystem graph, repos)
UNDERSTAND  What does the system currently do?
PLAN        What capabilities are required / missing? → Factory Plan
REASON      What architecture and implementation make sense? (decision gate, ADRs)
EXECUTE     Generate and modify the required repositories
VERIFY      Tests + schema + contracts + cross-repo integration
DEPLOY      Move changes into real applications (human-approved)
OBSERVE     Monitor actual behavior through the log tables
REASON      Analyze real-world results
RECOVER     Fix problems
LEARN       Capture experience (factory_experience index, ADRs)
IMPROVE     Update system and applications  ↺
```

## The Factory Plan

The Factory's primary output becomes a **Factory Plan**, not a set of files.
Files are produced by executing the plan. The schema starts minimal and grows
only from what real runs need (Principle 2).

```json
{
  "planId": "plan-2026-10-inventory",
  "goal": "Enable inventory management in POS",
  "business_objective": "Cashiers and owners always know stock and avoid stock-outs",
  "affected_products": ["POS"],
  "existing": {
    "database": ["inventoryStock", "inventoryMovements", "sp_inventory_adjust"],
    "backend": [],
    "frontend": [],
    "agents": []
  },
  "required_capabilities": [
    "inventory_stock_read",
    "inventory_adjustment",
    "inventory_movements_history",
    "inventory_low_stock_detection",
    "pos_inventory_support_agent"
  ],
  "repositories": ["smartloans_backend", "POSVending", "LoanAgents_SmartLoans"],
  "dependencies": ["products", "companies", "users"],
  "risks": ["concurrent adjustments", "negative stock", "tenant leakage"],
  "decisions_required": [],
  "tasks": [
    {"id": "T1", "repo": "smartloans_backend", "layer": "backend", "action": "create modules/inventory.py + routes_/inventory.py over sp_inventory_adjust", "dependsOn": []},
    {"id": "T2", "repo": "POSVending", "layer": "frontend", "action": "create inventoryApi.ts + inventory page in the products domain folder", "dependsOn": ["T1"]},
    {"id": "T3", "repo": "LoanAgents_SmartLoans", "layer": "agent", "action": "register get_stock (READ) + inventory_adjust (PROPOSE) tools; create pos_inventory_support agent", "dependsOn": ["T1"]}
  ],
  "validation": ["pytest", "vitest", "contract check backend↔frontend↔agent tool", "live SP smoke test in sandbox"],
  "observability": ["log_audit on every adjustment", "workflow_step for adjust flow", "timed_integration on agent calls"],
  "deployment": ["PRs on 3 repos", "human review", "SQL already live — no DDL"],
  "rollback": ["revert PRs; no schema change"],
  "success_criteria": ["merged in all 3 repos", "deployed", "≤ N human edits to generated code", "agent eval set passes"]
}
```

## Phases

Each phase lists: **goal**, **what already exists**, **deliverables**, and
**exit criteria**. Phases 1 and 2 run together on the inventory slice.

### Phase 1 — Automatic Planning

**Goal:** the Factory turns a business goal into a complete, executable
Factory Plan.

**Already exists:** PRD Builder (old Phase 4), schema analyst (live DB),
decision gate + ADR registry, ecosystem graph (`ecosystem_graph/`),
experience/architecture/implementation RAG.

**Deliverables:**
- `goal` input model and `FactoryPlan` Pydantic schema (minimal, as above)
- Capability model: map of existing capabilities per product/repo
- Repository mapping (which repo owns which layer) — including LoanAgents_SmartLoans
- Dependency, risk and missing-capability analysis
- Task generation with `dependsOn` ordering
- Validation, deployment and rollback sections

**Exit criteria:** the inventory goal produces a plan whose `existing`
section is correct against the live DB and repos, and whose tasks are
executed in Phase 2 without being rewritten by hand.

### Phase 2 — Reliable Multi-Repository Execution

**Goal:** the Factory actually executes its plan across GMO and the output
is merged.

**Already exists:** generation pipeline (database/backend/frontend agents,
fixer, reviewer, `pr_gate`), PR agent with `patch_app_tsx`, `pos` and
`commercial` repo targets, first simultaneous 3-layer pass (Milestone 7).

**Known gaps:**
- LoanAgents_SmartLoans is not a target (`orchestrator.py` routing knows only `pos`/`commercial`)
- Frontend generator assumes flat `src/pages/{Module}Page.tsx`; POS uses domain folders (`pages/finance/Expenses/…`)
- Database stage is the least reliable (malformed calls, live SQL errors)
- Zero factory PRs merged into product repos; large uncommitted factory changes

**Deliverables:**
- Third repo target: `agents` → LoanAgents_SmartLoans (agent + tool + prompt + contract conventions)
- Real folder conventions per repo (read from the repo, not assumed)
- "Existing layer" mode: skip generation for layers already live (inventory DB)
- Cross-repo contract validation (backend route ↔ frontend client ↔ agent tool)
- Coordinated PRs across up to three repos, linked by `planId`

**Exit criteria:** inventory merged and deployed in all three repos, with
the number of human edits to generated code recorded in
`commercial-app-milestones.md`.

### Phase 3 — Agentic Application Foundation

**Goal:** give GMO applications the shared primitives for reasoning — by
**extracting and generalizing what LoanAgents_SmartLoans already has**, not
building from scratch.

**Already exists:**
| Primitive | Where |
|---|---|
| Tool gateway | `LoanAgents_SmartLoans/tools/backend_api.py` (API → SP only) |
| Human approval | `tools/pending_actions.py` + `smartloans_backend/modules/posSupportChat.py` |
| Tool contracts | `retrieval/contracts.py` |
| RAG | `retrieval/` (hybrid, rerank, query expansion, graph) |
| Audit trail | four observability tables |
| Multi-agent | `agents/orchestrator` + 21 specialist agents |

**Deliverables:**
- Tool registry: one declaration per tool (name, endpoint, schema, autonomy level, roles, tenant enforcement)
- Gateway enforcement of autonomy levels and `companyId` from session
- Memory: bounded sessions (TTL + turn cap — fixes TICKET-002 open item #2), durable experience store, current-state snapshot tools
- Structured plans and execution state for multi-step agent workflows (`workflowId`)
- Agent observability: every proposal/approval/tool call logged
- Evaluation harness: per-agent scenario sets with expected decisions
- Factory can generate a new agent + tools from a plan (used in Phase 2 T3)

**Exit criteria:** all existing `pos_*_support` agents run on the shared
registry with declared autonomy levels; eval sets exist and pass for each.

### Phase 4 — Reasoning Applications

**Goal:** applications reason about business situations, not just retrieve
data.

Target pattern — instead of "There are 12 pending orders":

> "There are 12 pending orders. Seven have exceeded normal processing time.
> Three belong to repeat customers. Two have pickup scheduled today. I
> recommend prioritizing those two and notifying the affected customers."

**Deliverables:** for POS (inventory, cash register, income/expenses),
SmartLoans (portfolio, collections), Laundry (orders, turnaround), Arcade and
Rewards — each agent implements Observe → Understand → Reason → Plan → Act →
Verify → Explain, citing the tool evidence it used.

**Exit criteria:** per application, at least one reasoning agent whose eval
set covers explanation quality and correct tool evidence; Laundry reaches L3+.

### Phase 5 — Proactive Applications

**Goal:** applications initiate useful workflows instead of waiting.

**Already exists:** deterministic proactive triggers — APScheduler jobs in
`smartloans_backend/main.py` (daily charges, onboarding/registration/offer/
bank-account reminders, payment-intent expiry, funding escalation).

**Deliverables:** insert reasoning between existing triggers and actions:

```
Event / schedule → Detection → Reasoning → Recommendation → Approval or AUTO action
```

Initial detectors: inventory low-stock / unusual consumption, inactive
customers (Laundry retention), payment-behavior change (SmartLoans),
operational anomalies, maintenance need (IoT). Recommendations are stored,
shown in-app/push, and their acceptance rate is tracked.

**Exit criteria:** at least three detectors live; recommendation acceptance
rate measured; no `EXECUTE_WITH_APPROVAL` action executed without approval.

### Phase 6 — Self-Improving Factory

**Goal:** production feedback drives Factory changes; TICKET-001/002 become
automatic.

```
Application → Event → Observability → Anomaly → Incident Agent →
Root-cause analysis → Factory Plan → Code change → Tests → PR →
Human review → Deploy → Observe
```

**Already exists:** observability layer (partially instrumented — registration/
OCR, support chat after TICKET-002); ticket template (`tickets/TICKET-00*.md`).

**Deliverables:** instrument loans/Stripe/SPEI/support integrations; anomaly
detection over `applicationLogs`/`integrationLogs`; incident agent that groups
incidents and traces the cross-repo call chain via the ecosystem graph;
auto-generated tickets (detect + document first), then auto-generated fix
plans and PRs.

**Exit criteria:** one real production incident detected, documented,
diagnosed and fixed through a Factory-opened PR with no human tracing.

### Phase 7 — Autonomous Agentic Software Factory

**Goal:** the closed loop runs continuously.

```
BUSINESS GOAL → FACTORY → PLAN → REASON → BUILD → TEST → DEPLOY →
APPLICATION → OBSERVE → REASON → IMPROVE ↺
```

The human remains owner and approver of important decisions; the Factory
handles increasing amounts of planning, implementation, verification and
operational learning.

**Exit criteria:** a business goal entered once results in planned, built,
reviewed, deployed and observed changes across products, with humans acting
only at approval points.

## First vertical slice: Inventory

Inventory exercises Phases 1–5 on one feature.

| Layer | Current state |
|---|---|
| Database | ✅ `inventoryStock`, `inventoryMovements`, `sp_inventory_adjust` live |
| Backend | ❌ no `modules/inventory.py` / `routes_/inventory.py` |
| Frontend | ❌ no `inventoryApi.ts` / page |
| Agent | ❌ no `pos_inventory_support` |
| PRD / Plan | ❌ none |

1. **Phase 1:** goal "Enable inventory management" → Factory Plan.
2. **Phase 2:** backend module + routes, frontend client + page, PRs on 3 repos.
3. **Phase 3:** `get_stock` (`READ`), `inventory_adjust` (`PROPOSE`) in the tool registry.
4. **Phase 4:** `pos_inventory_support` explains what is low and why.
5. **Phase 5:** scheduled low-stock detector → reasoning → reorder recommendation for approval.

## Relationship to earlier roadmaps

`docs/factory-knowledge-roadmap.md` (Phases 1–5: Experience RAG,
Architecture RAG, Implementation RAG, Agentic PRD Builder, Full Factory
Agent — all marked DONE 2026-09-21) is **superseded**. Its work is the
groundwork this roadmap builds on: those RAG layers and the PRD builder feed
Phase 1 (Planning) here. Its phase numbers must not be confused with the
phases above; refer to them as "Knowledge phases K1–K5" from now on.

`docs/commercial-app-milestones.md` continues as the per-run evidence log;
new milestones should reference the roadmap phase they advance.
