# Requirement Trace — leadCapture

Deterministic post-hoc verification: traces 5 named requirements through PRD -> Decision -> Database -> Backend -> Frontend -> Tests, run against already-generated artifacts. Not fed into any agent.

## Experiment 1
| Req | PRD | DECISION | DATABASE | BACKEND | FRONTEND | TESTS |
|---|---|---|---|---|---|---|
| REQ-001 | PASS | PASS | N/A | PASS | N/A | N/A |
| REQ-002 | UNKNOWN | FAIL | FAIL | FAIL | FAIL | N/A |
| REQ-003 | PASS | FAIL | PASS | N/A | N/A | N/A |
| REQ-004 | PASS | N/A | N/A | PASS | PASS | N/A |
| REQ-005 | PASS | UNKNOWN | PASS | FAIL | FAIL | N/A |

### REQ-001 — Public lead creation must be unauthenticated.
- **prd**: PASS — backend.endpoints[].description names it unauthenticated: /leadCapture/public
- **decision**: PASS — prd_hints.backend_endpoints forwarded the unauthenticated requirement verbatim
- **database**: N/A — Auth is not a database-layer concern
- **backend**: PASS — No auth dependency found on the public route
- **frontend**: N/A — Not checked at this layer
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-002 — Public callers must not control tenant identity (companyId).
- **prd**: UNKNOWN — PRD does not address tenant identity for public submission
- **decision**: FAIL — decision_gate.mandatory_constraints.database universally requires companyId with no per-module override -- this is a hardcoded rule (agents/decision_gate/rules.py:_build_mandatory_constraints), not a decision derived from this module's tenancy model.
- **database**: FAIL — companyId is INT NOT NULL with no default -- every INSERT, including public ones, must supply it
- **backend**: FAIL — Public function references companyId at all -- it is being read from, defaulted from, or validated against the anonymous caller's own payload
- **frontend**: FAIL — Public payload type/interface includes companyId as a caller-supplied field
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-003 — Lead does not have an existing companyId relationship (no FK to companies).
- **prd**: PASS — companyName field description states no existing companyId relationship
- **decision**: FAIL — decision_gate.mandatory_constraints.database universally requires companyId with no per-module override -- this is a hardcoded rule (agents/decision_gate/rules.py:_build_mandatory_constraints), not a decision derived from this module's tenancy model.
- **database**: PASS — No FK to companies -- companyId is present but not architecturally hard-linked
- **backend**: N/A — Structural DB-schema question
- **frontend**: N/A — Structural DB-schema question
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-004 — Public payload cannot set status or assignment.
- **prd**: PASS — Public endpoint description explicitly forbids status/assignedTo
- **decision**: N/A — decision_gate has no field-level allow-list concept
- **database**: N/A — DB layer doesn't distinguish caller origin
- **backend**: PASS — status is server-hardcoded and assignedTo is never read from the public payload
- **frontend**: PASS — Public payload type excludes status and assignedTo
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-005 — Duplicate handling must follow the selected policy.
- **prd**: PASS — Raised explicitly as an open design question
- **decision**: UNKNOWN — No decision-record artifact exists anywhere in this pipeline for open design questions -- specification carries no field for it. Whatever the Database Agent decides is never captured as an explicit, checkable decision upstream of it.
- **database**: PASS — A concrete, enforced duplicate policy exists: unique (companyId, email) + explicit reject
- **backend**: FAIL — Backend returns the SP's raw 200 response regardless of its embedded error/duplicate flag
- **frontend**: FAIL — Frontend only checks res.ok -- a duplicate rejection (HTTP 200 with an embedded error) would read as success
- **tests**: N/A — No test-generation stage exists in this pipeline


## Experiment 2
| Req | PRD | DECISION | DATABASE | BACKEND | FRONTEND | TESTS |
|---|---|---|---|---|---|---|
| REQ-001 | PASS | PASS | N/A | PASS | N/A | N/A |
| REQ-002 | UNKNOWN | FAIL | FAIL | FAIL | FAIL | N/A |
| REQ-003 | PASS | FAIL | FAIL | N/A | N/A | N/A |
| REQ-004 | PASS | N/A | N/A | PASS | UNKNOWN | N/A |
| REQ-005 | PASS | UNKNOWN | PASS | FAIL | FAIL | N/A |

### REQ-001 — Public lead creation must be unauthenticated.
- **prd**: PASS — backend.endpoints[].description names it unauthenticated: /leadCapture/public
- **decision**: PASS — prd_hints.backend_endpoints forwarded the unauthenticated requirement verbatim
- **database**: N/A — Auth is not a database-layer concern
- **backend**: PASS — No auth dependency found on the public route
- **frontend**: N/A — Not checked at this layer
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-002 — Public callers must not control tenant identity (companyId).
- **prd**: UNKNOWN — PRD does not address tenant identity for public submission
- **decision**: FAIL — decision_gate.mandatory_constraints.database universally requires companyId with no per-module override -- this is a hardcoded rule (agents/decision_gate/rules.py:_build_mandatory_constraints), not a decision derived from this module's tenancy model.
- **database**: FAIL — companyId is INT NOT NULL with no default -- every INSERT, including public ones, must supply it
- **backend**: FAIL — Public function references companyId at all -- it is being read from, defaulted from, or validated against the anonymous caller's own payload
- **frontend**: FAIL — Public payload type/interface includes companyId as a caller-supplied field
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-003 — Lead does not have an existing companyId relationship (no FK to companies).
- **prd**: PASS — companyName field description states no existing companyId relationship
- **decision**: FAIL — decision_gate.mandatory_constraints.database universally requires companyId with no per-module override -- this is a hardcoded rule (agents/decision_gate/rules.py:_build_mandatory_constraints), not a decision derived from this module's tenancy model.
- **database**: FAIL — An explicit FK to dbo.companies was added, hardening the tenancy assumption the PRD says doesn't apply
- **backend**: N/A — Structural DB-schema question
- **frontend**: N/A — Structural DB-schema question
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-004 — Public payload cannot set status or assignment.
- **prd**: PASS — Public endpoint description explicitly forbids status/assignedTo
- **decision**: N/A — decision_gate has no field-level allow-list concept
- **database**: N/A — DB layer doesn't distinguish caller origin
- **backend**: PASS — status is server-hardcoded and assignedTo is never read from the public payload
- **frontend**: UNKNOWN — Could not isolate the public payload type
- **tests**: N/A — No test-generation stage exists in this pipeline

### REQ-005 — Duplicate handling must follow the selected policy.
- **prd**: PASS — Raised explicitly as an open design question
- **decision**: UNKNOWN — No decision-record artifact exists anywhere in this pipeline for open design questions -- specification carries no field for it. Whatever the Database Agent decides is never captured as an explicit, checkable decision upstream of it.
- **database**: PASS — A concrete, enforced duplicate policy exists: unique (companyId, email) + explicit reject
- **backend**: FAIL — Backend returns the SP's raw 200 response regardless of its embedded error/duplicate flag
- **frontend**: FAIL — Frontend only checks res.ok -- a duplicate rejection (HTTP 200 with an embedded error) would read as success
- **tests**: N/A — No test-generation stage exists in this pipeline

