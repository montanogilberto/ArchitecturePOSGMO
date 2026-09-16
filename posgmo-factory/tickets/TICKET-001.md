# TICKET-001 — pos_income_support_agent reports "no income data" despite real recorded income

**Status:** Fixed locally, **not committed/pushed/deployed**
**Detected:** 2026-09-15 — manually (UI test → console log → traced by hand). This ticket is the
v1 template for the future pipeline described below: for now, evidence gets written here as a
markdown file instead of a Jira issue; no automated observability trigger exists yet.
**Repos touched by this investigation:** POSVending (frontend, symptom), LoanAgents_SmartLoans
(root cause + fix), smartloans_backend (data source, confirmed correct)
**Repos checked, not implicated:** Agent_POSGMO / posgmo-factory (no generated code in this path)

## Symptom

`PosSupportChatPage`, topic=income, `companyId=1`. Cashier asks "ingresos de hoy" twice in one
conversation:

1. Reply 1: *"Lo siento, no puedo responder en este momento. Intenta de nuevo más tarde."*
2. Reply 2: *"No tengo datos de ingresos para mostrarte en este momento."*

At the same moment, the Dashboard (same `companyId=1`) shows real data: **Ventas Hoy $1,360.00,
5 operaciones.**

## Evidence

- **Browser console** (pasted by user): `posSupportChatApi.ts` `start_conversation` →
  `conversationId: 2` → repeated `list_messages` polling (2.5s "agent typing" cadence, expected
  behavior, not itself a bug) → `send_message` → `messageId: 33`.
- **Screenshots** (pasted by user): the chat bubble sequence above, and the Dashboard showing
  `$1,360.00` / 5 operaciones for the same company at the same time.
- **Live backend call** (curl, run during triage):
  ```
  POST https://smartloansbackend.azurewebsites.net/monthly_income
  {"income":[{"companyId":1}]}
  → {"income": [ ...65 individual transaction rows for companyId=1... ]}
  ```
  Confirms `/monthly_income` returns every transaction for the month, **not** a pre-aggregated
  summary row.
- **Call chain traced** (ecosystem-graph-shaped, done by hand — no automated trigger yet):
  ```
  POSVending: PosSupportChatPage.tsx
    -> src/api/posSupportChatApi.ts (send_message)
    -> LoanAgents_SmartLoans: POST /support/pos-income
    -> agents/pos_income_support/agent.py (pos_income_support_agent)
    -> tools/backend_api.py :: get_monthly_income(company_id)
    -> smartloans_backend: POST /monthly_income
    -> modules/income.py :: monthly_income_sp
    -> EXEC [dbo].[sp_income_monthly]
  ```
- **Fix formula independently verified before writing any code**: filtering the 65 raw rows to
  today's date in Hermosillo local time (UTC-7, no DST — same conversion as
  `POSVending/src/utils/format.ts::toHermosilloDate`) gives **5 rows, $1,360.00** — an exact match
  to the Dashboard screenshot.

## Root cause

`LoanAgents_SmartLoans/tools/backend_api.py::get_monthly_income()` assumed `/monthly_income`
returns one pre-aggregated row and did `income[0]`. It actually returns every transaction row for
the month, so `income[0]` was one arbitrary transaction (dated Sept 1st), not a total. The agent's
own instruction ("never state a peso amount you did not get from the tool call — don't guess") made
it correctly distrust that single row and report no data. **The bug was in the tool's contract
assumption, not in the backend, and not in the LLM's reasoning.**

## Fix

- `LoanAgents_SmartLoans/tools/backend_api.py::get_monthly_income` — aggregates the raw rows into
  `{companyId, monthlyTotal, monthlyCount, todayTotal, todayCount}` client-side (same pattern
  `get_expense_total` already used for expenses), with `today` computed in Hermosillo local time.
- `LoanAgents_SmartLoans/agents/pos_income_support/prompt.py` — updated to reference the new field
  names (`todayTotal`/`todayCount` for "hoy", `monthlyTotal`/`monthlyCount` for "este mes").
- New test: `LoanAgents_SmartLoans/tests/test_pos_income_support_agent.py` — includes a live
  regression test (`test_get_monthly_income_returns_an_aggregate_not_one_raw_row`) asserting the
  return shape is an aggregate, never a raw transaction row.

## Verification

- `pytest tests/` in `LoanAgents_SmartLoans`: **20/21 pass**. The 1 failure
  (`test_root_agent_is_negotiation_agent`) is a pre-existing, unrelated stale test (documented
  separately in this session's discovery report) — not caused by this fix.
- The new live test independently reconfirms the aggregate against the real backend, not a mock.

## Why this ticket exists (context for the future pipeline)

This bug was found the slow way: a human tested the UI, saw the wrong answer, pasted a console log
and two screenshots into this session, and the trace above was done by hand across three repos.
The goal going forward is to trigger this same trace automatically from the observability layer
(`applicationLogs`/`integrationLogs`) instead of a human noticing — see this session's discussion
of "detect + document" as the safe v1 slice (auto-fix deferred until observability coverage widens
past registration/OCR, and until the Factory has a way to verify a proposed fix before proposing
it). This file's shape (symptom → evidence → call chain → root cause → fix → verification) is the
template that pipeline should produce automatically once built.
