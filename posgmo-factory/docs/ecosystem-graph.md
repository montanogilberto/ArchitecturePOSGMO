# Ecosystem Graph

## Purpose

The Factory generates code across four related repositories — this repo
(the Factory itself), `smartloans_backend`, `POSVending` (frontend), and
`LoanAgents_SmartLoans` (domain agents) — but until now had no way to answer
"what else depends on this?" before generating a change. RAG (the MCP
knowledge server) answers *what does this pattern/schema look like*; nothing
answered *what breaks if I change it*.

The Ecosystem Graph is that second thing: a code-level dependency graph,
derived from real source and live database metadata, that a Factory agent
(or a human) can query before touching a table, a stored procedure, a route,
or a frontend API call.

It is **not** a replacement for the MCP knowledge server, and not a
replacement for `LoanAgents_SmartLoans/retrieval/`'s hybrid search. Those
answer "what does this look like" (RAG / pattern retrieval) and "what's the
live business data for this client" (runtime data graph). This module
answers "what calls what" (static code graph) — see `ecosystem_graph/__init__.py`'s
docstring for the three-way distinction.

## Architecture

Four extraction layers, each independently real and independently testable —
no layer guesses where a reliable source exists:

```
frontend src/api/*.ts  --(regex, literal fetch() paths only)-->  route (METHOD /path)
                                                                       |
                                                    (ast parse of routes_/ + modules/)
                                                                       v
                                                            stored procedure name
                                                                       |
                                              (live query: sys.sql_expression_dependencies)
                                                                       v
                                                                 database table
```

| Layer | File | Method | Why not something simpler |
|---|---|---|---|
| Frontend calls | `ecosystem_graph/frontend_calls.py` | Line-scanning regex over `export const ... fetch(...)` | Python has no TS AST; a full TS toolchain would be infrastructure the value doesn't justify yet. Dynamically-built paths (`` `${BASE}/${module}` ``) are reported with `path=None`, never guessed. |
| Backend routes → SP | `ecosystem_graph/backend_routes.py` | Python `ast` parse of `routes_/*.py` (route → delegate function) and `modules/*.py` (function → `EXEC` calls), joined by a bounded BFS through private-helper indirection | Regex over the whole file can't reliably scope "which EXEC belongs to which function" the way a parse tree can. |
| SP → table | `ecosystem_graph/sql_dependencies.py` | Live query against `sys.sql_expression_dependencies` on the actual SQL Server | Text-parsing `.sql` files drifts from what's actually deployed (a real, previously-observed failure mode in this codebase). |
| Combine + traverse | `ecosystem_graph/graph.py` | Joins the three edge lists; `what_breaks_if_changed()` does the reverse-lookup traversal | — |

## Graph model

### Node types (current)

Only what's actually extracted today — see **Limitations** for the gap
between this and the full 22-type model a mature ecosystem graph would need:

- `frontend_call` — one exported function in a `src/api/*.ts` file (identifier: `"{file}:{function}"`)
- `backend_route` — one `METHOD /path` pair
- `stored_procedure` — one SP name
- `table` — one SQL Server table name

### Edge types (current)

- `calls` — frontend_call → backend_route (`frontend_to_route`)
- `executes` — backend_route → stored_procedure (`route_to_sp`)
- `reads`/`writes` (undifferentiated today) — stored_procedure → table (`sp_to_table`)

### Scope

`MODULES_IN_SCOPE` in `graph.py` — deliberately narrow, grown module-by-module,
each addition spot-checked against real output before being trusted:

```python
MODULES_IN_SCOPE = {
    "clients": ["clientsApi.ts"],
    "income": ["incomeApi.ts"],
    "expenses": ["expensesApi.ts"],
    "rewards": ["rewardsApi.ts"],
}
```

Extending coverage to the rest of the ~270 backend routes is real, valuable
future work. It should not be bulk-generated — each module's edges should be
spot-checked the same way clients/income/expenses/rewards were.

## Provenance

Every edge carries where it came from:

- `frontend_to_route` / `route_to_sp` edges carry `source_file`.
- `sp_to_table` edges are DB-verified — their "evidence" is live DMV metadata,
  which is stronger than a file+line citation (a file can be stale; the DMV
  reflects what's actually deployed).

**Remaining gap:** no uniform `{repository, file, line}` evidence object
exists across all three layers — `source_file` is a bare filename, not a
repo+path+line triple. Combined with `EcosystemGraph.sources` (below), a
caller can currently reconstruct "which repo, which commit, which filename"
but not the exact line.

## Confidence model — implemented

Every edge dict returned by all three extraction layers now carries an
explicit `confidence` key:

- **VERIFIED** — `frontend_calls.py` for a literal, resolved `fetch()` path;
  `backend_routes.py`'s `resolve_route_to_sp()` when the delegate chain
  reaches at least one real `EXEC`; `sql_dependencies.py` always (a DMV
  query only ever returns dependencies that really exist).
- **UNKNOWN** — a dynamically-built frontend path (`path=None`); a route
  whose delegate chain resolves to zero SPs in scope (`stored_procedures=[]`).
  Both were already honest gaps before this field existed; now they're
  labeled, not just implied by an empty value.
- **INFERRED** — still has no representation. Nothing in this module
  produces a "probably true, not directly verified" edge, by design; adding
  one would need a genuinely new extraction strategy, not just a new label.

One real limitation this surfaced while adding the confidence field (see
`test_known_gap_dynamic_path_with_literal_separator_is_silently_dropped` in
`tests/test_ecosystem_graph_frontend_calls.py`): a `fetch()` call shaped like
`` `${API_BASE_URL}/${var}` `` (a literal separator between the base URL and
the next `${...}`) matches **neither** `_FETCH_LITERAL_RE` nor
`_FETCH_DYNAMIC_RE` — it's silently dropped from the edge list entirely,
not even reported as `UNKNOWN`. Confirmed against a real file
(`posRewardsApi.ts`'s first `fetch()` call). Not fixed here — regex changes
to `frontend_calls.py` are their own deliberate change, not a side effect of
adding a confidence field — but now pinned by a test so a future fix is
visible, not a silent behavior shift.

## Repository versioning — implemented

`build_graph()` now stamps every graph it produces:

```python
@dataclass
class EcosystemGraph:
    frontend_to_route: list[dict]
    route_to_sp: list[dict]
    sp_to_table: list[dict]
    sources: dict          # {"backend": {"path", "commit", "branch"}, "frontend": {...}}
    scanner_version: str   # SCANNER_VERSION constant in graph.py
    scanned_at: str         # UTC ISO-8601, set at build time
```

`_git_info()` runs `git rev-parse HEAD` / `git rev-parse --abbrev-ref HEAD`
against each repo path — best-effort: a non-git path or missing `git`
returns `{"commit": None, "branch": None}` rather than raising, so a graph
can still be built (just without version-awareness for that one source).

A graph built via `EcosystemGraph(...)` directly (as the pure-unit
traversal tests do, bypassing `build_graph()`) gets empty/default
values (`sources={}`, `scanned_at=""`) rather than missing attributes —
a caller can uniformly check "is this graph's provenance known" without a
`KeyError`.

**Remaining gap:** nothing yet *compares* a graph's stamped commit against
the repo's current `HEAD` to flag staleness — the data needed to build that
check now exists, but the check itself doesn't.

## Relationship with RAG

No conflict, because there's nothing to reconcile — see Purpose above and
`ecosystem_graph/__init__.py`'s docstring, which already draws this
distinction unprompted:

| | This module | MCP knowledge server | `LoanAgents_SmartLoans/retrieval/` |
|---|---|---|---|
| Answers | "what calls/depends on this" | "what does this pattern look like" | "what's the live business data for this client" |
| Source | real source files + live DB metadata | static JSON/CSV snapshot files | live backend OpenAPI + Gemini embeddings |
| Kind | static code graph | pattern/knowledge lookup | runtime data graph |

## Future impact analysis

`what_breaks_if_changed(graph, node_kind, identifier)` already implements
the reverse-lookup traversal for `table`, `stored_procedure`, and `route`
inputs, within `MODULES_IN_SCOPE`. Example, run for real against this
session's verified `clients` module:

```
what_breaks_if_changed(graph, "table", "clients")
  directly_affects:     stored procedure sp_clients, stored procedure sp_clients_all
  transitively_affects: route POST /clients, route GET /all_clients,
                        frontend call clientsApi.ts:createOrUpdateClient,
                        frontend call clientsApi.ts:getAllClients
```

Reaching further hops — a `Module`↔`Module` layer, or an `Agent`/`Tool`
layer reaching into `LoanAgents_SmartLoans` and this Factory's own agents —
is new extraction work, not new architecture. See Limitations.

## Limitations

- **Coverage: 4 of ~270+ backend routes**, and **0 of 2 repos** — no
  extraction layer exists yet for `LoanAgents_SmartLoans` (19+ agents, tools,
  prompts) or for this Factory's own agents. `Agent`/`Tool`/`Prompt` node
  types don't exist in the graph today.
- **No `Module`↔`Module` relationship** — `find_related_modules()`-style
  queries aren't answerable; `MODULES_IN_SCOPE` is a flat dict, not a graph.
- **`frontend_calls.py` only resolves literal fetch() paths**, and even among
  dynamic ones, only the "adjacent `${...}${...}`" shape is reported as an
  honest `UNKNOWN` — a literal-separator shape (`` `${BASE}/${var}` ``) is
  silently dropped from the edge list entirely (see Confidence model above;
  confirmed against real source, now pinned by a test, not yet fixed).
- **No staleness check** — a graph knows the commit it was built from
  (`sources`), but nothing compares that against the repo's current `HEAD`
  to warn "this graph is out of date."
- **Only a reverse traversal exists** (`what_breaks_if_changed`) — there is
  no forward `find_dependencies()` yet.
- **`test_ecosystem_graph_sql_dependencies.py` depends on live SQL Server
  credentials** being present in the environment; it skips cleanly rather
  than failing when they aren't, but that means CI coverage of the SP→table
  layer is conditional on `LOCAL_DB_*` being configured wherever tests run.

## Current implementation status

`ecosystem_graph/` and its sibling `decision_registry.py` exist as real,
tested code. Test files: `test_ecosystem_graph_frontend_calls.py`,
`test_ecosystem_graph_backend_routes.py`, `test_ecosystem_graph_traversal.py`,
`test_ecosystem_graph_sql_dependencies.py`, `test_ecosystem_graph_versioning.py`
— 19 tests, all passing against real source and a live DB connection as of
this write-up (full factory suite: 124 passed). Confidence labeling and
repository/commit stamping (steps 1–2 below) are both implemented. **Not yet
wired into any agent's tool list** — no MCP tool exposes
`what_breaks_if_changed` yet, though `mcp_server/server.py` has other,
unrelated uncommitted changes in flight — see git status before assuming
what's merged.

## Next implementation step

In order, each gated on the previous one actually landing (small increments,
per this repo's own stated engineering principles):

1. ~~Tests for the existing 4-module scope~~ — **done**.
2. ~~Repository/commit stamping + explicit per-edge `confidence` field~~ —
   **done**. Remaining: an actual staleness check comparing `sources` against
   each repo's live `HEAD`.
3. A fourth extraction layer for `Agent`/`Tool` nodes — `LoanAgents_SmartLoans`
   first (smaller, cleaner repo — 19 agents, 2 tool files), this Factory's
   own agents second.
4. Widen `MODULES_IN_SCOPE` past the current 4 modules, one at a time,
   spot-checked against real output each time — not bulk-generated.
5. Wire `what_breaks_if_changed` into `mcp_server/server.py` as a callable
   tool, once (3) lands — exposing it earlier would let an agent query an
   impact analysis with no agent/tool layer to traverse into.
