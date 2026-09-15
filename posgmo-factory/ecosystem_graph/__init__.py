"""
GMO Ecosystem Graph — code-level dependency graph across the four real
repositories (frontend POSVending, backend smartloans_backend, agents
LoanAgents_SmartLoans, and this factory), answering the question runtime
retrieval can't: "what breaks if I change this?"

Distinct from LoanAgents_SmartLoans/retrieval/graph.py, which is a
RUNTIME DATA graph (client -> reward_transactions -> income, resolved by
calling live backend endpoints, for an agent answering a cashier's
question about a specific client). This is a STATIC CODE graph (frontend
API call -> backend route -> module function -> stored procedure -> SQL
table, resolved by parsing real source files and querying live DB
metadata, for the factory answering "what does this contract change
affect"). Same "Edge" vocabulary and "verify against the real thing, not
an indexed guess" discipline, different layer.

Four extraction layers, each independently real and testable — no
regex-guessing where a reliable source exists:
    - sql_dependencies.py — live SQL Server sys.sql_expression_dependencies
      (NOT text-parsing SQL files, which can drift from what's actually
      deployed; this queries the same production DB verified throughout
      this session).
    - backend_routes.py — Python `ast` parsing (not regex) of
      smartloans_backend's routes_/*.py and modules/*.py, real function
      call graphs, not string matching.
    - frontend_calls.py — regex parsing of POSVending's src/api/*.ts
      fetch() calls (ast isn't available for TS here; literal paths only
      — a dynamically-built endpoint path is reported as unresolved, not
      guessed).
    - graph.py — combines the three into one edge list + a
      what_breaks_if_changed() traversal (reverse-edge lookup).

Scope discipline: this starts covering ONLY the modules already
deeply verified elsewhere this session (clients, income, expenses,
rewards) — not all ~270 backend routes at once. Extend it the same way
retrieval/graph.py in LoanAgents_SmartLoans is extended: add a module to
MODULES_IN_SCOPE only once its edges have been spot-checked against real
output, not preemptively for coverage's sake.
"""
