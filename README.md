# POS GMO AI Factory

## Vision

Build an autonomous software factory capable of generating production-ready modules for POS GMO.

The system must generate:

* Frontend code
* Backend code
* SQL Server tables
* Stored Procedures
* Documentation
* Tests
* Pull Requests

while strictly following the existing POS GMO architecture.

---

# System Architecture

## Frontend

Technology Stack:

* Ionic React
* TypeScript
* Vite
* Capacitor
* Context API
* CSS

Folder Structure:

```text
src/
├── api/
├── components/
├── pages/
├── contexts/
├── hooks/
├── utils/
├── types/
```

Generation Targets:

```text
src/api/{module}Api.ts
src/pages/{Module}Page.tsx
src/pages/{Module}Page.css
```

UI Conventions:

* IonPage
* IonHeader
* IonToolbar
* IonContent

Patterns:

* CRUD
* Search
* Loading State
* Toast Notifications
* Modal Forms

---

# Backend

Technology Stack:

* FastAPI
* Python
* Pydantic
* SQL Server

Folder Structure:

```text
backend/
├── models/
├── schemas/
├── routes/
├── services/
├── database/
```

Generation Targets:

```text
models/{module}.py
schemas/{module}.py
routes/{module}.py
```

Requirements:

* Full docstrings
* Type hints
* OpenAPI support
* Pydantic validation
* Production-ready code

---

# Database

Technology Stack:

* SQL Server

Artifacts:

```text
tables
stored procedures
indexes
foreign keys
constraints
```

Conventions:

* Existing POS GMO naming standards
* Existing CRUD SP patterns
* JSON payload processing
* Reuse existing table conventions

Never invent a new database architecture.

---

# Knowledge Repositories

## Architecture Repository

Repository:

https://github.com/montanogilberto/ArchitecturePOSGMO

Knowledge Files:

```text
architecture.json

frontend_knowledge.json
frontend_modules.json
frontend_components.json
frontend_routes.json
frontend_api_contracts.json

backend_knowledge.json
backend_models.json
backend_routes.json
backend_schemas.json

sql_tables.json
sql_relationships.json
sql_stored_procedures.json

agent_rules.json
```

These files are the source of truth.

Agents must always retrieve knowledge before generating code.

---

# MCP Layer

MCP is the retrieval layer.

The following tools must exist:

## Frontend

get_frontend_module_examples()

get_frontend_patterns()

get_component_patterns()

get_route_patterns()

## Backend

get_backend_module_examples()

get_route_patterns()

get_model_patterns()

get_schema_patterns()

## SQL

get_table_patterns()

get_stored_procedure_patterns()

get_relationship_patterns()

---

# Agent Architecture

## Architect Agent

Responsibilities:

* Read PRD
* Read Architecture Knowledge
* Generate Specification JSON

Output:

```json
{
  "module": "suppliers",
  "fields": [],
  "relationships": [],
  "frontend": {},
  "backend": {},
  "database": {}
}
```

Architect Agent never writes code.

---

## Database Agent

Responsibilities:

Generate:

* tables
* indexes
* foreign keys
* stored procedures

Must:

* reuse existing patterns
* follow POS GMO conventions

Output:

```sql
CREATE TABLE ...
```

```sql
CREATE PROCEDURE ...
```

---

## Backend Agent

Responsibilities:

Generate:

```text
model
schema
route
service
```

Requirements:

* Pydantic
* FastAPI
* OpenAPI
* Documentation

---

## Frontend Agent

Responsibilities:

Generate:

```text
api
tsx
css
```

Requirements:

* Ionic React
* TypeScript
* Existing POS GMO design system

---

## Reviewer Agent

Responsibilities:

Validate:

* Architecture compliance
* Naming conventions
* Security
* Performance
* Type safety

Output:

```json
{
  "score": 95,
  "issues": []
}
```

---

# Generation Workflow

```text
PRD
 |
 V
Architect Agent
 |
 V
Specification JSON
 |
 +----------------+
 |                |
 V                V
Database Agent    Backend Agent
 |
 +----------------+
 |
 V
Frontend Agent
 |
 V
Reviewer Agent
 |
 V
Pull Request
```

---

# PRD Standard

Every feature request must be transformed into JSON.

Example:

```json
{
  "module": "suppliers",
  "description": "supplier management",
  "fields": [
    {
      "name": "supplierName",
      "type": "string",
      "required": true
    },
    {
      "name": "phone",
      "type": "string"
    },
    {
      "name": "email",
      "type": "string"
    }
  ]
}
```

Agents consume JSON.

Agents never consume free-form requirements directly.

---

# Rules

1. Never invent architecture.
2. Always reuse POS GMO patterns.
3. Prefer consistency over creativity.
4. Follow SOLID.
5. Follow Clean Architecture.
6. Generate production-ready code.
7. Generate documentation.
8. Generate tests when possible.
9. Reuse existing modules as templates.
10. Always consult MCP knowledge before generation.

---

# Long-Term Goal

Transform POS GMO into a fully autonomous software factory capable of generating complete business modules with minimal human intervention while maintaining architectural consistency across:

* Frontend
* Backend
* Database
* Documentation
* Testing
* Deployment
