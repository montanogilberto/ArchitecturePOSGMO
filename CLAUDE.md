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

## Business Domains

| Domain | Backend modules |
|---|---|
| POS & Cash Operations | `cashRegister`, `tickets`, `income`, `expenses` |
| Marketplace Aggregator | `unifiedProducts`, `productMatches`, `marketplaceOrders`, `opportunities`, `sellListings` |
| IoT & Automation | `IOT`, `vending`, `laundry`, `waterTanks` |
| ERP / HR | `employees`, `contractors`, `departaments`, `projects`, `employeeProjectAssignments` |
| P2P Lending Core | `loans`, `loanOffers`, `loanProposals`, `loanChat`, `creditScore` |
| Stripe Payments, Wallets & Automated Collection | `stripe_payments`, `automatedPayments`, `walletBalance`, `onboardingReminders`, `disbursement` (legacy/dormant) |
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

Note: `Database/sql_tables.json` exists on disk but is **not read by any MCP tool** (`structure_database.csv` is canonical instead) — do not rely on it being current; `Backend/backend_modules.json.json` referenced in earlier versions of this table does not exist as a file.
