"""
review_fixer rebuilds a router shell whose View import doesn't match the layout.
Found 2026-11-07 (prd_voiceCall): the shell had `import { VoiceCallView } from
'./VoiceCall/VoiceCallView'` (named), the reviewer requires the default import
POSVending uses, review_fixer had no rule for it -> 3/3 iterations failed -> no PR.
"""
import re

from agents.review_fixer.rules import _ensure_default_view_export, _shell_from_layout
from frontend_layout import layout


def test_shell_is_rebuilt_from_the_layout_import_lines():
    shell = _shell_from_layout("src/pages/messaging/VoiceCallPage.tsx")
    lines = layout("voiceCall", "messaging")
    assert lines["shell_view_import"] in shell and lines["shell_css_import"] in shell
    assert re.search(r"import\s+VoiceCallView\s+from\s+'\./VoiceCall/VoiceCallView'", shell)
    assert "export default VoiceCallPage;" in shell
    assert not re.search(r"\buse(State|Effect)\s*\(|\bfetch\s*\(", shell)


def test_unknown_page_path_yields_nothing():
    assert _shell_from_layout("src/whatever.tsx") == ""


def test_view_gets_a_default_export_only_when_missing():
    named = "export const VoiceCallView: React.FC = () => null;"
    assert _ensure_default_view_export(named, "src/pages/messaging/VoiceCallPage.tsx").endswith(
        "export default VoiceCallView;\n")
    already = "const VoiceCallView = () => null;\nexport default VoiceCallView;\n"
    assert _ensure_default_view_export(already, "src/pages/messaging/VoiceCallPage.tsx") == already
