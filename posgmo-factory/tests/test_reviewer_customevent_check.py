"""
Reviewer's bare-CustomEvent check — a real false positive found while
getting factoryRunUsage through construction, not a hypothetical one.

`re.search(r'\\bCustomEvent\\b(?!\\s*<)', page_content)` matched the FIRST
occurrence of the word "CustomEvent" in the file -- which is always the
import line (`import { ..., CustomEvent } from 'react'`, the established,
correct convention every frontend page follows, since a bare type name in
an import list is never followed by `<...>`). re.search only needs one
match, so a page where every real usage is correctly typed
(CustomEvent<void>, CustomEvent<InputInputEventDetail>, etc.) still failed
this check on the import line alone. Confirmed against factoryRunUsage's
real generated page: 4 occurrences, 3 genuinely typed usages, 0 bare ones
-- and it failed review every iteration until fixed.

Only the CHECK is tested here (via the real captured content, not a
synthetic fixture) -- the fix itself (requiring a preceding `:` so only
type-annotation position counts, not import-list position) is the whole
point of these two tests.
"""
import json

from agents.reviewer.rules import _check_frontend

_MINIMAL_SPEC = {"module": "factoryRunUsage", "frontend": {"has_list_view": True}, "prd_hints": {}}
_MINIMAL_GATE = {"tier": "TIER_2_FINANCIAL"}


def _customevent_issues(page_content: str) -> list[str]:
    fe = {"page_file": {"content": page_content}, "api_file": {"content": ""}, "css_file": {"content": ""}}
    issues = _check_frontend(fe, _MINIMAL_SPEC, _MINIMAL_GATE)
    return [i.message for i in issues if "CustomEvent" in i.message]


def test_real_factoryrunusage_page_has_no_false_positive():
    """The actual real-world case this fix exists for."""
    d = json.load(open("local_export/factoryRunUsage/artifacts.json"))
    raw = d.get("frontend_artifacts", "{}")
    body = raw.strip()
    if body.startswith("```"):
        body = "\n".join(l for l in body.splitlines() if not l.strip().startswith("```")).strip()
    fe = json.loads(body)
    page_content = fe.get("page_file", {}).get("content", "")
    assert "CustomEvent" in page_content, "fixture assumption: real page must mention CustomEvent at all"

    issues = _customevent_issues(page_content)
    assert issues == [], f"expected no CustomEvent issues on correctly-typed real content, got: {issues}"


def test_import_line_alone_is_not_a_bare_usage():
    page = "import { IonPage, CustomEvent, CheckboxChangeEventDetail } from 'react';\nconst x = 1;\n"
    assert _customevent_issues(page) == []


def test_genuinely_bare_usage_is_still_caught():
    """The fix must narrow the false positive, not disable the check
    entirely -- a real bare CustomEvent in type-annotation position must
    still be flagged."""
    page = (
        "import { CustomEvent } from 'react';\n"
        "const handleChange = (e: CustomEvent) => { console.log(e); };\n"
    )
    issues = _customevent_issues(page)
    assert any("Bare CustomEvent" in msg for msg in issues)


def test_correctly_typed_usage_is_not_flagged():
    page = (
        "import { CustomEvent, CheckboxChangeEventDetail } from 'react';\n"
        "const handleChange = (e: CustomEvent<CheckboxChangeEventDetail>) => { console.log(e); };\n"
    )
    assert _customevent_issues(page) == []
