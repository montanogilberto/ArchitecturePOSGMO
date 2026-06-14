# TODO - Fix `_fix_updated_at_isnull` regex crash (variable-length lookbehind)

- [x] Diagnose traceback and identify invalid regex in `agents/fixer/rules.py` (`(?<!\bCONVERT\b.*)`).
- [x] Patch `_fix_updated_at_isnull` to remove unsupported lookbehind and preserve behavior.
- [x] Run targeted tests and sanity-check fixer flow.
- [x] Mark TODO complete.
