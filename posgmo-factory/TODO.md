# Refactor TODO - agents package restructuring

- [x] Inventory all agent modules and current imports/usages.
- [ ] Create package folders for each agent with `agent.py`, `prompt.py`, `rules.py`.
- [ ] Move `INSTRUCTION` into each `prompt.py`.
- [ ] Keep runtime behavior unchanged by wiring each new `agent.py` to use moved prompt.
- [ ] Add `rules.py` in each package for readability structure.
- [ ] Update orchestrator imports in `agents/agent.py`.
- [ ] Update any tests/import references impacted by path changes.
- [ ] Run importAction: Generate and run tests for the selected code validation.
- [ ] Mark TODO complete.
