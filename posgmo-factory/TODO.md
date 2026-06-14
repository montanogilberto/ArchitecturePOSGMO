# TODO - Fix BASE_URL context KeyError in ADK prompt injection

- [x] Diagnose failing key from logs and locate placeholder usage (`{BASE_URL}`).
- [x] Patch `orchestrator.py` session state seeding to include `BASE_URL` placeholder.
- [ ] Harden prompt templates (if needed) to avoid unintended context substitution for literal braces.
- [ ] Add/adjust regression test for required seeded context keys.
- [ ] Run targeted tests and verify no KeyError for `BASE_URL`.
- [ ] Mark TODO complete.
