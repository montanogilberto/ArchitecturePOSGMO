# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

All commands run from `posgmo-factory/`:

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the full factory pipeline against a PRD file
python orchestrator.py tests/prd_supplier.json

# Re-run from a specific agent (skips earlier stages)
python run_partial.py --from database --state last_state.json
python run_partial.py --from frontend --state last_state.json
python run_partial.py --from reviewer --state last_state.json

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
- `GITHUB_BACKEND_REPO_NAME` — backend GitHub repo name
- `LOCAL_DB_SERVER`, `LOCAL_DB_NAME`, `LOCAL_DB_USER`, `LOCAL_DB_PASSWORD` — for Schema Analyst Agent (live SQL Server)

## Factory Architecture

The factory is a **Google ADK** multi-agent pipeline. The pipeline assembly lives in `agents/agent.py` and is imported by the orchestrator as `root_agent`.

### Full Pipeline (in order)

```
PRDInput JSON
  │
  ▼
prd_parser_agent         — extracts {module}/{plural}/{Module} into session state
  ▼
schema_analyst_agent     — queries LIVE SQL Server → schema_analysis (tables, FKs, conflicts)
  ▼
architect_agent          — reads PRD + schema → emits SpecificationJSON → session["specification"]
  ▼
decision_gate_agent      — PURE PYTHON, no LLM — classifies tier + constraints → session["gate_result"]
  ▼
generation_stage         — PARALLEL:
  ├── database_agent     → session["database_artifacts"]
  ├── backend_agent      → session["backend_artifacts"]
  └── design_consistency_agent → session["design_brief"] (fetches real pages from GitHub)
  ▼
fixer_agent              — PURE PYTHON, no LLM — deterministic SQL/Python/TS fixers
  ▼
frontend_agent           → session["frontend_artifacts"]
  ▼
reviewer_agent           — PURE PYTHON, no LLM — deterministic scoring (0-100, must pass ≥ 90)
  ▼
pr_agent                 → pushes files to GitHub + opens PRs on both repos
```

### Session State Keys

Each agent reads its inputs and writes its output via ADK session state:

| Key | Written by | Read by |
|---|---|---|
| `prd_context` | prd_parser_agent | — |
| `schema_analysis` | schema_analyst_agent | architect_agent, decision_gate_agent |
| `specification` | architect_agent | decision_gate_agent, database_agent, backend_agent, frontend_agent, reviewer_agent |
| `gate_result` | decision_gate_agent | database_agent, backend_agent, frontend_agent, reviewer_agent |
| `database_artifacts` | database_agent | fixer_agent, reviewer_agent, pr_agent |
| `backend_artifacts` | backend_agent | fixer_agent, frontend_agent, reviewer_agent, pr_agent |
| `design_brief` | design_consistency_agent | frontend_agent |
| `frontend_artifacts` | frontend_agent | reviewer_agent, pr_agent |
| `review_result` | reviewer_agent | pr_agent |
| `pr_result` | pr_agent | — |

### Pure-Python Agents (no LLM)

Three agents run deterministic Python logic with zero LLM calls. They use `BaseAgent` directly:

- **`decision_gate_agent`** — classifies module tier (`TIER_1_CATALOG` → `TIER_4_IOT`), detects backend pattern (`CRUD_ONLY` vs `CRUD_AND_CONNECTOR`), emits `mandatory_constraints`. Hard-blocks if FK targets don't exist in the live DB.
- **`fixer_agent`** — post-generation regex fixers: DATETIME2→DATETIME, injects missing `@pjsonfile` on `sp_all`, removes `round()` from Python returns, fixes TypeScript `catch (err: any)` violations.
- **`reviewer_agent`** — scores database/backend/frontend artifacts 0-100. Auto-errors (`-20 pts`) for critical violations like missing `companyId`, cross-company data leaks, DATETIME2 in non-IOT modules. Pipeline only proceeds if all scores ≥ 90.

## MCP Server

`mcp_server/server.py` exposes the architecture knowledge files as MCP tools. All LLM agents call these tools before generating code. The server runs as a subprocess via `McpToolset(StdioServerParameters(...))` in `agents/mcp_tools.py`.

Key tools: `get_frontend_patterns()`, `get_backend_patterns()`, `get_db_schema()`, `get_sp_patterns()`, `get_generation_rules()`, `get_table_columns(table_name)`, `get_relationships_for_table(table_name)`.

## PRD Schema

`prd_schema.py` is the Pydantic gate that validates input before the pipeline starts. Key enforcement:
- `companyId` must NEVER appear in PRD fields (injected automatically by all SPs)
- `module` must be camelCase, lowercase first letter
- `fk_table` and `fk_column` must both be set or both omitted
- `SpecificationJSON` enforces exact file naming conventions on output

## PR Agent

`agents/pr_agent.py` handles the final step:
1. Creates feature branches on both frontend and backend GitHub repos (`feat/{module}-module`)
2. Pushes all generated files via GitHub Contents API
3. Patches `App.tsx` to register the new route and menu item (`patch_app_tsx`)
4. Opens PRs on both repos with generation scores in the body

`save_sql_locally()` also writes `generated/{module}/sp_{module}.sql` locally for manual DB execution.

## Partial Re-runs

`run_partial.py` lets you resume from any agent after fixing an issue, using the `last_state.json` saved by `orchestrator.py`:

```bash
python run_partial.py --from database --state last_state.json
```

Available `--from` values: `prd_parser | schema_analyst | architect | gate | generation | frontend | reviewer | pr`

## Module Tier System

The `decision_gate_agent` classifies every PRD into a tier that affects SQL types, constraints, and frontend patterns:

| Tier | Trigger | Key constraint |
|---|---|---|
| `TIER_1_CATALOG` | Simple master data | Standard CRUD |
| `TIER_2_FINANCIAL` | Monetary decimal columns | `DECIMAL(10,2)` for money, no rounding in Python |
| `TIER_3_TRANSACTIONAL` | Sales domain + line items + financial FK | Two tables (header + detail), single SP transaction |
| `TIER_4_IOT` | Hardware/sensor keywords | `DATETIME2(3)`, no soft-delete, chart view |

## Business Intake API (website → Factory)

`agents/business_intake/` + `business_intake_api.py` — lets the GMO Ecosystem app send a business need (text, optional website URL, or an audio note) and get an evidence-grounded analysis back. **Read-only**: no PRD is written, no construction runs, no database is touched.

**What GMO already has comes from `../Product/GMO_MODULES.md`** (modules, agents, and how each is wired), parsed and keyword-matched in plain Python (`modules.py`). Keep that file current; it is re-read automatically when it changes.

```
text (+ website URL)                     audio note
  │                                        ▼
  │                              intake_understanding_agent — LLM, audio only (transcribe)
  ▼                                        │
answer cache (same text + url + language + GMO_MODULES.md version → 0 model calls)
  ▼
website.py            — read the owner's site (public http/https only, SSRF-guarded, text only)
gather_business_evidence — PURE PYTHON: GMO_MODULES.md matches + index, schema columns/FKs, draft PRDs
  ▼
intake_analyst_agent  — the ONE model call: REUSE / EXTEND / INVESTIGATE / CREATE / NOT_APPLICABLE per capability,
                        workflow (verified/inferred/unknown), ≤3 high-impact questions, factoryDecision
```

The analyst follows the product owner's Business Intake specification (see `agents/business_intake/prompt.py`): catalog entries are candidates, never proof; evidence.py verifies each candidate's wiring against Backend/*.json, the schema snapshot and ecosystem_graph and assigns an `evidenceLevel`; the full route/SP/table inventory is included so hidden implementations can be found. `prdRequests` are cleared in code unless `factoryDecision == "READY_FOR_PRD"`.

```bash
uvicorn business_intake_api:app --port 8090      # POST /intake/analyze, GET /health
pytest tests/test_business_intake.py -v          # live test skipped without GEMINI_API_KEY
```

Env: `INTAKE_ALLOWED_ORIGINS` (website origins, comma-separated), `INTAKE_RATE_LIMIT_PER_HOUR` (default 20 per IP; cached answers don't count), `FACTORY_INTAKE_MODEL` (default gemini-2.5-flash). `factory_experience` search is off by default (it costs an embedding call). Each `prdRequests` line is meant to be fed to `factory_agent.py` by a person, deliberately.

## Website commercial core (`site_commercial/`)

Mounted by `business_intake_api.py` under `/site`: visit counter, per-visitor AI token allowance (enforced on `/intake/analyze` with HTTP 402), lead capture (mini registration + contact form, fields from `tests/prd_leadCapture.json`) and lead follow-up admin (`X-Admin-Key` = `SITE_ADMIN_KEY`). Interim SQLite store in `SITE_DATA_DIR` until the leadCapture module exists in the GMO backend. Tests: `tests/test_site_commercial.py`.
