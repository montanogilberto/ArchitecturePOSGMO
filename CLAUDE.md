# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

All commands run from `posgmo-factory/`:

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the full factory pipeline against a PRD file
python orchestrator.py tests/prd_supplier.json

# Start the MCP knowledge server (stdio transport)
python -m mcp_server.server

# Start MCP server with HTTP transport
MCP_TRANSPORT=http python -m mcp_server.server

# Run all tests
pytest

# Run a single test file
pytest tests/test_prd_schema.py -v
```

**Required env vars** (`.env` in `posgmo-factory/`):
- `GOOGLE_API_KEY` — Gemini API key for ADK agents
- `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` — for PR agent
- Any Azure / Twilio credentials the target backend modules use

## Factory Code Architecture (`posgmo-factory/`)

The factory itself is a **Google ADK** multi-agent pipeline written in Python:

- `orchestrator.py` — CLI entry point; creates an ADK `Runner` with `InMemorySessionService`, validates the PRD via `PRDInput`, builds session state (template variable map), and streams the pipeline.
- `prd_schema.py` — Pydantic models for PRD input (`PRDInput`) and Architect output (`SpecificationJSON`). `companyId` is always injected by SPs and must never appear in PRD fields.
- `agents/agent.py` — Assembles `root_agent` as a `SequentialAgent` over the six sub-agents in pipeline order.
- `agents/*.py` — One file per agent; each agent reads knowledge via MCP tools before generating artifacts and writes its output to ADK session state for the next agent.
- `mcp_server/server.py` — `FastMCP` server that exposes architecture knowledge files as callable tools. Resolves paths relative to the repo root (`KNOWLEDGE_ROOT = Path(__file__).parent.parent.parent`).

**Session state keys written by agents** (consumed by downstream agents):
- `spec` — `SpecificationJSON` dict from Architect Agent
- `sql_output` — SQL DDL + SPs from Database Agent
- `backend_output` — Python model/schema/route files from Backend Agent
- `frontend_output` — TS/TSX/CSS files from Frontend Agent
- `review_output` — Score JSON from Reviewer Agent

**Monkey-patch note:** `orchestrator.py` patches `google.genai._api_client.BaseApiClient.async_request` to redirect `gemini-2.0-flash` calls to `gemini-2.5-flash`. Do not remove this unless the ADK default model is updated.

## What This Repo Is

This is the **POS GMO AI Factory** — an autonomous software factory that generates production-ready modules (frontend, backend, SQL, stored procedures, docs, tests, PRs) for the POS GMO platform while strictly following its existing architecture. The repo contains JSON/CSV knowledge files that agents must read before generating any code.

**Architecture repository (source of truth):** https://github.com/montanogilberto/ArchitecturePOSGMO

## Tech Stack

**Frontend:** Ionic React + TypeScript, Vite bundler, Capacitor (mobile), deployed to Azure Static Web Apps.  
**Backend:** FastAPI (Python), deployed to Azure App Service at `https://smartloadsbackend.azurewebsites.net`.  
**Database:** SQL Server (Azure), accessed exclusively through stored procedures in `sql_logic/*.sql`.  
**Testing:** Vitest (unit), Cypress (e2e).  
**External integrations:** Azure Computer Vision, Azure Blob Storage, Twilio (WhatsApp/SMS), MercadoLibre OAuth, eBay OAuth.

## Backend Architecture

Three-layer pipeline:

1. **Ingress** — `main.py` + `routes_/*.py`: CORS, payload normalization, route registration.
2. **Business Logic** — `modules/*.py`: third-party API calls (Azure, Twilio, MercadoLibre, eBay), JSON serialization.
3. **Persistence** — stored procedures in `sql_logic/*.sql`: all DB mutations go through SPs; routes never issue raw SQL.

**Authentication:**
- User sessions: `sp_login` (DB-backed hash verification via `/login`).
- Worker-to-worker: shared secret via `security/worker_key.py` (`Depends(require_worker_key)`).
- MercadoLibre: PKCE OAuth flow, callback at `/mercadolibre/oauth/callback`.
- eBay: OAuth client-credentials / auth-code flow via `modules/ebay_auth.py`.

## Frontend Architecture

New modules follow this file pattern:
```
src/api/{module}Api.ts          # fetch-based API client with TypeScript interfaces
src/pages/{Module}Page.tsx      # IonPage → IonHeader/IonToolbar/IonContent shell
src/pages/{Module}Page.css
```

Route guard uses roles: `Admin`, `Manager`, `Cashier`. Public routes: `/login` only.

**UI rules (established 2026-08, loans-folder migration — see `Frontend/frontend_ui_patterns.json.json` for examples):**
1. **Ionic components for every interactive element** — never raw `<button>/<input>/<select>/<label>/<img>` or clickable `<div>`; use `IonButton/IonInput/IonSelect/IonCheckbox/IonChip/IonAvatar/IonCard button/IonItem button` (native ripple, keyboards, a11y). Structural `div/p/span` for custom layout is fine.
2. **No inline styles** — every page owns its `.css`; dynamic values via class variants + CSS custom properties. Shadow components styled with `--background`/`--color` + `::part()`.
3. **Spinner on every async action** — button-level `IonSpinner` + disabled while awaiting (reference: LoanChatPage, LoanPaymentPage).
4. **Refetch on view re-enter** — Ionic keeps pages mounted; data pages must reload in `useIonViewWillEnter`, not only on mount.
5. **`APP_ENV` flag** (`src/utils/appEnv.ts`) — dev builds show a DEV badge in the Header and register devices with `appEnv` for `env_*` Hub tags.

## Business Domains

| Domain | Backend modules |
|---|---|
| POS & Cash Operations | `cashRegister`, `tickets`, `income`, `expenses` |
| Marketplace Aggregator | `unifiedProducts`, `productMatches`, `marketplaceOrders`, `opportunities`, `sellListings` |
| IoT & Automation | `IOT`, `vending`, `laundry`, `waterTanks` |
| ERP / HR | `employees`, `contractors`, `departaments`, `projects`, `employeeProjectAssignments` |
| P2P Lending Core | `loans`, `loanOffers`, `loanProposals`, `loanChat`, `creditScore` |
| Stripe Payments, Wallets & Automated Collection | `stripe_payments`, `automatedPayments`, `walletBalance`, `onboardingReminders`, `disbursement` (legacy/dormant) |
| SPEI Banking Rail (primary money-out) | `bankAccounts`, `transfers`, `stpProvider`, `walletTransactions` |
| Push Notifications & Client Comms | `pushNotifications`, `azure_notifications`, `ticket_notifications`, `contact_email` |
| KYC, Biometric Verification & Legal Recovery | `clientFaceRecognitions`, `document_intelligence`, `signatureMatching`, `geocoding`, `digitalContracts`, `legalCases` |

## AI Features

- **OCR pipeline:** `modules/scannertext.py` → Azure ComputerVisionClient → GPT normalization.
- **Symptom diagnosis:** `modules/api_gpt.py`, endpoint `/symptoms` — structures natural-language symptom input into markdown diagnostic tables.
- **ID document extraction:** `modules/document_intelligence.py`, endpoint `/ocr` → Azure AI Document Intelligence (prebuilt ID model). Tesseract.js on the frontend (`src/utils/idOcr.ts`) is a client-side fallback, not backend-orchestrated.
- **Face liveness verification:** runs entirely client-side via `@vladmandic/face-api` (`src/utils/faceLiveness.ts`, `src/components/FaceLivenessCapture.tsx`) — 4-direction challenge + blink detection. Azure Face API / Face-Liveness-With-Verify was previously used and has been fully removed from the backend; do not reintroduce it.
- **Signature matching:** `modules/signatureMatching.py` — OpenCV (cv2) contour comparison between the ID's signature crop and the contract-acceptance signature capture.

## Database Conventions

- All tables are in the `dbo` schema on SQL Server.
- Multi-tenant isolation is via `companyId` on most domain tables.
- `cashRegisterSessions` / `cashRegisterMovements` track POS session lifecycle.
- `income` + `incomeDetails` + `incomeDetailOptions` form the sales receipt hierarchy.
- `unifiedProducts` is the master catalog; `productMatches` links marketplace listings to it.
- `tickets` stores receipt blobs (Azure Blob) and tracks WhatsApp/SMS delivery status.

## Payments & Money Rails (2026-08)

Two rails, direction-dependent:

- **Money IN (deposits, cuota card payments): Stripe only.** A CLABE cannot be charged (SPEI is push-only), so until STP virtual CLABEs exist all deposits are card charges (Payment Element, card + OXXO).
- **Money OUT (loan disbursement, lender withdrawal): SPEI first, Stripe Connect Transfer second.** `/payments/disburse` debits the `walletTransactions` ledger, sends to the verified CLABE (mock STP until contract), auto-reverses on failure; handlers fall back to Stripe when SPEI isn't eligible.

**Rules the factory must preserve:**
- Wallet top-ups credit the **real net**: `confirm_payment_intent` reads the charge's `balance_transaction` (fee/net); the published MX formula (3.6% + $3 MXN + IVA 16%) is preview/fallback only. The client sees paid/fee/net on the amount step, card summary, receipt, success push and comprobante email.
- `POST /stripe/payment-intents/confirm` accepts `savePaymentMethod` → persists the card used via `sp_savedPaymentMethods` (same table `/automated-payments/saved-method` reads). Standalone card-saving uses the SetupIntent flow (`/automated-payments/setup-intent` → `save-method`).
- Every succeeded charge sends a **comprobante email** (folio = `stripeTransactions.transactionId`, Stripe reference, montos, comisión) via `modules.users._send_email` in a daemon thread — best-effort, never blocks the response.
- Frontend: the Stripe Payment Element must stay **mounted during `stripe.confirmPayment()`** — switching UI steps before the charge unmounts it and throws IntegrationError (frozen "Procesando…"). Show the processing screen only after the charge succeeds.
- Pending PRD: `transactionNotification` (per-channel money-movement confirmation record, `pending→sent→confirmed` via webhook) — `posgmo-factory/tests/prd_transactionNotifications.json`.

## Push Notifications

Azure Notification Hub. Installations are tagged `user_{userId}` — **never clientId** (the backend maps clientId→userId; wrong id yields empty tags with a silent "success") — plus `env_{appEnv}` (`dev`/`prod` device flag from `src/utils/appEnv.ts`, sent by `/registerDevice`).

- Sends always fire regardless of app state. FCM payloads target Android channel `push_notifications` (the app creates it at startup — importance 5; unknown channels drop silently) and carry `data.navigationRoute` for tap deep-links.
- iOS foreground display via `capacitor.config` → `PushNotifications.presentationOptions: ['badge','sound','alert']`; Android foreground mirrors the push through `LocalNotifications` (id must be int32, not `Date.now()`).
- `NotificationDeliveries` backs the per-user in-app inbox (`/myNotifications`); the system push and the inbox are parallel channels.

## Observability

Observability is a first-class layer, not ad-hoc logging. Goal: **every user action is reconstructable** for debugging, audit, regulatory compliance, fraud investigation, support and analytics. Hand-written infra (an intentional exception to the factory pipeline — the PRD model doesn't cover middleware).

**Correlation:** `workflowId` (one per business process — registration, loan application, payment; created at the start, reused by every step) + `correlationId` (one per HTTP request, links request → response → downstream integration calls). Identity comes from client-asserted `X-User-Id`/`X-Company-Id`/`X-Client-Id` headers — fine for observability, **never** for authorization.

**Four log tables** (`dbo`, already exist — do NOT regenerate; see `smartloans_backend/sql/sp_observability.sql`):
- `workflowLogs` — business process steps under one workflowId.
- `auditLogs` — who changed what (old → new); durable path.
- `applicationLogs` — technical + SECURITY events; one row auto-emitted per request.
- `integrationLogs` — external service calls (Stripe, Azure Face, Blob, Notification Hub, email/SMS, Document Intelligence).

**Backend framework** (`smartloans_backend/observability/`): `ObservabilityMiddleware` traces every request automatically; business code uses `log_workflow_step` / `workflow_step()` ctx mgr / `log_audit` / `log_application` / `log_integration` / `timed_integration()`. A background writer batches best-effort logs; audit + SECURITY are written synchronously. All log bodies are **redacted + size-capped** (passwords, tokens, OTP, CURP, base64 images → `***`).

**Frontend** propagates the trace: a global `window.fetch` interceptor (`src/utils/observability.ts`) stamps the `X-Correlation-Id`/`X-Workflow-Id`/identity/version headers on backend calls; `ObservabilityContext` manages `startWorkflow`/`endWorkflow`.

## Agent Architecture

The generation pipeline is: **PRD → Architect Agent → Specification JSON → Database Agent + Backend Agent → Frontend Agent → Reviewer Agent → Pull Request**

| Agent | Responsibility | Output |
|---|---|---|
| **Architect** | Reads PRD + knowledge files, produces spec. Never writes code. | Specification JSON (`module`, `fields`, `relationships`, `frontend`, `backend`, `database`) |
| **Database** | Generates tables, indexes, FKs, stored procedures following POS GMO patterns | `.sql` |
| **Backend** | Generates Pydantic models, schemas, FastAPI routes with full docstrings + type hints | `models/`, `schemas/`, `routes/` |
| **Frontend** | Generates API client, page TSX, CSS following Ionic design system | `src/api/`, `src/pages/` |
| **Reviewer** | Validates architecture compliance, naming, security, type safety | Score JSON with issues list |

**Every feature request must be expressed as a PRD JSON before agents consume it:**
```json
{ "module": "suppliers", "description": "...", "fields": [{ "name": "supplierName", "type": "string", "required": true }] }
```

## Core Rules

1. Never invent architecture — always reuse POS GMO patterns.
2. Always read MCP knowledge files before generating code.
3. Prefer consistency over creativity; follow SOLID and Clean Architecture.
4. Never issue raw SQL from routes — all DB mutations go through stored procedures.
5. Never invent a new database architecture.
6. Every generated module must be observable (see **Observability**): instrument business logic via the `observability` package — `timed_integration()` around external-service calls, `log_audit(...)` on data mutations, and `workflow_step(...)` for multi-step flows. Never write secrets, PII, or base64 into the log tables (the redactor enforces this — don't bypass it). Do NOT regenerate the four log tables or their SPs.

## Frontend Folder Structure

```text
src/
├── api/          # {module}Api.ts — fetch-based clients with TypeScript interfaces
├── components/
├── pages/        # {Module}Page.tsx + {Module}Page.css
├── contexts/
├── hooks/
├── utils/
└── types/
```

## Backend Folder Structure

The actual smartloans_backend layout (this supersedes the aspirational `models/schemas/routes/services/database` layout described in the original factory README — that structure was never adopted; the real repo has used the layout below since inception):

```text
smartloans_backend/
├── main.py           # FastAPI app assembly, router registration, APScheduler startup jobs
├── databases.py      # connection() + SafeCursor (pymssql/FreeTDS wrapper, see Database Conventions)
├── modules/          # {module}.py — business logic: third-party API calls, JSON (de)serialization,
│                      # calls into sql_logic/*.sql stored procedures via @pjsonfile
├── routes_/          # {module}.py — FastAPI APIRouter definitions (ingress only, no business logic)
├── sql/              # {module}.sql or sp_{module}.sql — DDL + stored procedures (see Core Rules #4)
└── security/          # worker_key.py and other auth/shared-secret helpers
```

New modules follow: `sql/sp_{module}.sql` → `modules/{module}.py` (imports `databases.connection`, calls `EXEC [dbo].[sp_{module}] @pjsonfile = %s`) → `routes_/{module}.py` (thin `APIRouter`, no raw SQL, delegates to the module function) → registered in `main.py`.

## Architecture Files Reference

| File | Contents |
|---|---|
| `Backend/backend_architecture.json.json` | Three-layer pipeline definitions |
| `Backend/backend_routes.json.json` | All FastAPI route paths and file mappings |
| `Backend/backend_models.json.json` | Pydantic request/response models |
| `Backend/backend_schemas.json.json` | Schema validation rules |
| `Backend/backend_stored_procedures.json.json` | SP catalog |
| `Backend/backend_authentication.json.json` | Auth flows |
| `Backend/backend_ai_features.json.json` | Azure AI / GPT integrations |
| `Backend/backend_business_domains.json.json` | Domain groupings |
| `Backend/backend_prompts.json.json` | GPT prompt templates |
| `Backend/backend_database.json.json` | SQL Server connection config + connection-resilience notes (not yet exposed via an MCP tool — read directly if needed) |
| `Frontend/frontend_knowledge.json` | Architecture, modules, API/page patterns |
| `Frontend/frontend_routes.json.json` | Page routes and role guards |
| `Frontend/frontend_components.json.json` | Shared component catalog |
| `Frontend/frontend_modules.json.json` | Module-level feature breakdown |
| `Frontend/frontend_ui_patterns.json.json` | UI conventions |
| `Frontend/frontend_api_contracts.json.json` | Request/response contracts |
| `Database/structure_database.csv` + `Database/sql_relationships.json` | **Live source of truth for DB schema** — read together by the `get_database_schema` MCP tool (format: schema,table,column,type,length,nullable,pk,fk) |
| `Database/ER_Diagram.csv` | Entity relationships |
| `smartloans_backend/sql/sp_observability.sql` + `smartloans_backend/observability/` | Observability layer — the four log tables, insert/batch SPs, and the backend middleware/logger package (see **Observability**) |

Note: `Database/sql_tables.json` exists on disk but is **not read by any MCP tool** (`structure_database.csv` is canonical instead) — do not rely on it being current; `Backend/backend_modules.json.json` referenced in earlier versions of this table does not exist as a file.
