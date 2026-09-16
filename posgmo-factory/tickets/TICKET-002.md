# TICKET-002 — POS Support Chat silently swallows agent-service failures (no observability)

**Status:** Partially fixed (observability gap closed) — **underlying cause of the failure itself
is still unknown**, not committed/pushed/deployed
**Detected:** 2026-09-15 — manually (native logcat + in-app screenshot pasted by user)
**Repos touched:** POSVending (frontend, symptom), smartloans_backend (root cause of *this*
ticket — a silent catch), LoanAgents_SmartLoans (checked, cleared — see below)

## Symptom

`PosSupportChatPage`, topic=clients. Conversation started 10:19am, worked correctly through
several turns (including a real client creation at 10:20am: *"Listo, cliente creado
correctamente."*). Then, at **3:45pm — a ~5.5 hour gap** — the same conversation, same topic, a
new message ("crea un cliente fulanito de tal celular 6621 23 4565") got:

> *"Lo siento, no puedo responder en este momento. Intenta de nuevo más tarde."*

## Evidence

- **Screenshot** (pasted by user) of the chat bubble sequence above, with timestamps.
- **This exact string is not agent output** — grepped every agent prompt in
  `LoanAgents_SmartLoans`, no match. Traced it to
  `smartloans_backend/modules/posSupportChat.py:243`, the fallback text in a bare
  `except Exception as e:` around the call to the agent service (`_generate_agent_reply`,
  line ~152-176). The real exception `e` was only ever `print()`ed
  (`modules/posSupportChat.py:242`) — container stdout, not queryable, not in
  `integrationLogs`. **The real cause was unrecoverable after the fact.**
- **Reproduced the same message with a fresh ADK session** (locally, against the real
  `pos_clients_support_agent`): it answers correctly, asking for the missing `clientType`
  field — no error, no refusal. This rules out the message content itself as the cause and
  points at something specific to the long-lived, reused session
  (`_get_or_create_pos_session` keys the ADK session by `conversationId`, with **no expiry or
  size bound** — only a process restart or an explicit "clear history" resets it, per
  `tools/pending_actions.py`'s own docstring in `LoanAgents_SmartLoans`).
- `_generate_agent_reply`'s `httpx.AsyncClient(timeout=20.0)` is a candidate factor: a cold
  `loanagents-smartloans.azurewebsites.net` instance (or a long, accumulated conversation
  taking longer inside Gemini/ADK) could exceed 20s. Not confirmed — this is exactly the kind
  of thing durable integration logging would have settled immediately instead of requiring
  hand-reproduction.

## Root cause of *this ticket*

`smartloans_backend/modules/posSupportChat.py::_generate_agent_reply`'s call to the agent
service had no observability instrumentation — its own `except Exception as e:` block
(`posSupportChat_sp`, line 241-243) only `print()`s the exception and returns a generic
message, with nothing written to `integrationLogs`. This matches a gap already known from this
session's earlier discovery: **loans/Stripe/SPEI/support-chat integration calls emit nothing to
the observability tables** — only registration/OCR are instrumented.

**The underlying cause of the ORIGINAL failure (why that specific call actually failed) is
still unknown** — this ticket fixes the *diagnosability* gap, not (yet) the failure itself.

## Fix (this ticket)

- `smartloans_backend/modules/posSupportChat.py::_generate_agent_reply` — wrapped the outbound
  call in `observability.integrations.timed_integration("loanagents_smartloans",
  f"support_{topic}", request=...)`, the same pattern already used by every other external-
  service call in this codebase (Stripe, Apple/Google IAP, etc.). On success this now writes
  latency + response into `integrationLogs`; on failure it writes status=FAILED with the full
  exception traceback, then re-raises into the existing `except` block unchanged (the
  user-facing fallback message and behavior are identical on the happy path and the failure
  path — this is additive logging only, verified via `python -m py_compile`, not run live
  end-to-end to avoid writing test data into shared conversation/session state).

## Still open — not fixed by this ticket

1. **Why the original call actually failed** — timeout, cold start, or something about the
   accumulated session — unknown. The next occurrence will have a real
   `integrationLogs.exception` value to read instead of requiring reproduction by hand.
2. **Unbounded ADK session growth** — `_get_or_create_pos_session` (LoanAgents_SmartLoans)
   never expires or bounds a conversation's session state. A long-lived support chat could
   accumulate hours/days of turns with no cleanup. Worth a TTL or turn-count cap — not
   attempted here, needs its own investigation.
3. **20s timeout may be too short** for a cold agent-service instance — worth revisiting once
   (1) gives real latency numbers to decide from, instead of guessing a new value now.

## Verification

- `python -m py_compile modules/posSupportChat.py` — passes.
- The wrapped call uses the exact same `with timed_integration(...) as span:` shape already
  proven correct at 5+ other call sites in this file's own codebase (`modules/arcadeStore.py`).
- Not run live end-to-end (see Fix section) — deliberate, to avoid writing test conversations
  into shared state for a change that's structurally identical to existing, working call sites.
