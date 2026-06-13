"""
Frontend Agent — UI rules constants.
Machine-readable version of the rules embedded in INSTRUCTION.
"""

# UTC-7 Hermosillo timezone offset helper (always included in generated TSX)
UTC7_HELPER = """
const toHermosillo = (utc: string | undefined): string => {
  if (!utc) return '';
  const d = new Date(utc.includes('Z') ? utc : utc + 'Z');
  return new Date(d.getTime() - 7 * 60 * 60 * 1000).toLocaleString();
};
"""

# Custom Header import block (replaces IonHeader in all pages)
HEADER_IMPORT = "import Header from '../components/Header';"
POPOVER_IMPORTS = (
    "import AlertPopover from '../components/PopOver/AlertPopover';\n"
    "import MailPopover from '../components/PopOver/MailPopover';"
)

# API body shape: all endpoints are POST, payload wrapped under plural key
API_BODY_SHAPE = "{plural}: [{ ...fields }]"

# Response unwrap: SP wraps array under ROOT key
RESPONSE_UNWRAP = "data.{plural} ?? []"

# Catch block pattern — TypeScript forbids typed catch parameters
CATCH_PATTERN = "} catch (err) { setError((err as Error).message ?? 'Error desconocido'); }"

# Forbidden patterns
FORBIDDEN = [
    "catch (err: any)",           # TypeScript error
    "JSON.parse(await res.json())",  # double-parse crash
    "import { IonHeader",         # use custom Header instead
    "axios",                      # plain fetch() only
]

# IonInfiniteScroll exact event type
INFINITE_SCROLL_EVENT_TYPE = "CustomEvent<void>"

# Menu sections for App.tsx placement
MENU_SECTIONS = {
    "catalog":        "Catálogo",
    "admin":          "Administración",
    "messages":       "Mensajes",
    "iot":            "IOT",
    "system":         "Sistema",
}