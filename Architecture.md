# KRIBU Demo Architecture

**Status:** Iterations 0-5 are implemented and verified; Iteration 6 parsing and provenance is next

**Primary orchestration:** LangGraph

**Deployment for demo:** Local Docker Compose with external Gemini free-tier inference

## 1. Architecture principles

1. Authorization precedes retrieval; inaccessible content never reaches a model.
2. Deterministic code handles policy, arithmetic, validation, and side effects.
3. Models interpret and synthesize evidence but do not become a source of truth.
4. Every business fact retains immutable source-version provenance.
5. Domain stories are versioned skills over common platform components.
6. Interfaces isolate replaceable infrastructure and client-specific schemas.
7. Begin as a modular monolith plus workers; split services only when measured needs justify it.

## 2. High-level flow

```mermaid
flowchart LR
    U[User] --> S[KRIBU Studio\nNext.js]
    S --> API[FastAPI Control Plane]
    API --> G[KRIBU Guard\nKeycloak + OPA + ACL/RLS]
    G -->|allowed context| E[KRIBU Engine\nLangGraph]
    E --> B[KRIBU Brain\nIngestion + Retrieval + Memory]
    B --> DB[(PostgreSQL + pgvector)]
    B --> OBJ[(Versioned object store)]
    E --> L[Gemini via ModelProvider]
    E --> A[Artifacts and approvals]
    A --> S
    API --> AUD[(Audit events)]
    G -. denies .-> S
```

### Query-to-response sequence

1. Studio submits a query with the user's OIDC access token.
2. FastAPI validates issuer, audience, signature, expiry, tenant, and session.
3. Guard resolves trusted user attributes and asks OPA whether the action is allowed.
4. Engine creates a run and LangGraph checkpoint, then selects an authorized skill.
5. Retrieval builds mandatory SQL filters from tenant and ACL grants before search.
6. Brain performs full-text and vector searches only within that authorized candidate set.
7. Engine extracts typed facts, runs deterministic calculations, and compares evidence.
8. Citation validation removes or qualifies claims without sufficient support.
9. Guard applies output policy and verifies every cited source is still accessible.
10. Studio streams findings, limitations, and evidence links; artifacts are saved as drafts.
11. Any external action becomes an approval request and cannot execute in the demo.
12. The audit log receives the complete decision trail without storing secrets.

## 3. Component boundaries

| Component | Owns | Must not own |
|---|---|---|
| KRIBU Studio | User interaction, progress display, evidence navigation, approval UI | Authorization decisions or direct database access |
| API control plane | Request validation, use-case services, transactions, stable API contracts | Model reasoning in route handlers |
| KRIBU Guard | Authentication context, RBAC/ABAC, ACL projection, policy decisions, approval rules | Semantic retrieval or probabilistic permission grants |
| KRIBU Brain | Ingestion, normalized content, provenance, indexing, authorized retrieval, facts/entities | Deciding user access without Guard inputs |
| KRIBU Engine | LangGraph state, skill execution, tools, analysis, citations, interrupts | Bypassing services with arbitrary SQL or executing unapproved actions |
| Skill packs | Domain schemas, prompts, extraction and report rules, golden examples | Infrastructure, identity, or generic retrieval implementations |
| Connector adapters | Future discovery/fetch/ACL mapping/action APIs | Credentials in code or action without approval token |
| Audit/evaluation | Append-only events, run traces, golden-dataset results | Editing business records |

## 4. KRIBU Guard

### Decision model

OPA receives a normalized, non-LLM input:

```json
{
  "subject": {"tenant_id": "t1", "subject_id": "mike-id", "roles": ["employee"], "department": "engineering"},
  "action": "resource.read",
  "resource": {"id": "record-id", "tenant_id": "t1", "resource_type": "employee_record", "classification": "restricted_hr", "department": "human-resources", "owner_subject_id": "roger-id", "grants": [{"principal_type": "role", "principal_id": "hr_manager", "action": "resource.read"}]},
  "environment": {"purpose": "demo_resource_read"}
}
```

Policy returns allow/deny, reason codes, obligations, and the policy version. SQL row-level security and application filters enforce the same tenant boundary as defense in depth.

For a query such as "What is Mr Albert's salary?", Mike's role and department do not satisfy the `restricted_hr` policy. The request is denied before chunks are searched. Vector similarity is never used as authorization. An optional lightweight local classifier may detect sensitive intent and force denial or review, but cannot override a deterministic denial or create permission.

### Generic-industry adaptation

- Canonical attributes: tenant, subject, action, resource type, classification, owner, department, project, jurisdiction, purpose, and time.
- Client adapters map source-specific roles, groups, labels, and ACLs into this canonical model.
- Policy bundles are versioned per tenant and domain, not hard-coded around employee names or one database schema.
- Missing mappings deny access and enter an administrative review queue.

### Implemented Guard slice (Iterations 4-5)

OPA `1.21.2` runs on a private Compose network shared only with the API; it has no host port. `OpaClient` sends typed canonical attributes to `data.kribu.authz.decision` and rejects missing/malformed results, timeouts, and unexpected policy versions. API readiness checks the loaded `guard-v2` policy version (bumped in step across `authz.rego`, settings, `.env.example` and Compose). The Rego policy recognizes `internal` and `restricted_hr`; every read needs a matching ACL grant, and `restricted_hr` also needs the `hr_manager` role. An administrator or auditor has no implicit content access. Each action is valid only for its declared purposes (`resource.read`: `demo_resource_read`, `document_read`; `document.create` and `document.version.create`: `document_upload`). Uploads are allowed for administrators on any mapped classification, HR managers on `restricted_hr`, and any user on `internal` documents of their own database department; a subject holding `auditor` never uploads. Upload permission never grants reading, and adding a version additionally requires read access to the existing document.

Every protected operation calls `app/policy/authorization.py` `authorize()`: one OPA decision and one audit row carrying the caller's action, failing closed on policy or audit outage. The protected `GET /v1/demo/resources/{resource_id}` path uses three short tenant transactions (profile + descriptor + grants; the audit write; content on allow) and holds no connection while OPA answers. Inactive or unprovisioned identities are audited as `identity_not_provisioned` before the `403`. The profile's database department is used, not the token's potentially stale department. Unknown resource labels deny. Missing or inaccessible resources share a safe `404`; policy or audit failure gives `503` without releasing content. Even an absent resource makes a policy call, so a policy outage does not distinguish its existence through response status.

`resource_descriptors` and `resource_acl_grants` are the reusable metadata boundary for future documents. `demo_resource_content` is temporary synthetic proof data. `authorization_audit_events` is tenant-scoped; the runtime role may insert/select but cannot update/delete. Audit input holds identifiers and policy metadata, never token, query text, or content. Natural-language paraphrase resistance is completed when Brain and Engine route every resolved resource through this Guard and apply authorization inside search.

## 5. KRIBU Brain

### Ingestion pipeline

```mermaid
flowchart LR
    UP[Upload / future connector] --> Q[Quarantine and validate]
    Q --> H[Hash and version]
    H --> P[Docling / deterministic parser]
    P --> N[Normalize structure]
    N --> ACL[Map metadata and ACL]
    ACL --> C[Provenance-aware chunks]
    C --> I[Full-text + vector index]
    N --> F[Facts and entities]
    I --> R[Authorized hybrid retrieval]
    F --> R
```

### Implemented upload lifecycle (Iteration 5)

```text
UploadGuard (ASGI)   no/invalid bearer -> 401 | body > 25 MiB (+64 KiB) -> 413
  -> validate metadata + explicit read grants (no implicit uploader access)
  -> hash + sniff bytes (stdlib: PDF, DOCX, XLSX, CSV, TXT, MD)  -> 415 / 422
  -> Idempotency-Key lookup (fingerprint includes the file SHA-256) -> replay | 422
  -> authorize(document.create | document.version.create)  (audited)
  -> create: duplicate only among the caller's own documents with the same access -> 200 duplicate_of
  -> LocalFileObjectStore.put  tenants/{tenant}/sha256/{hh}/{hex}  (fsync + replace)
  -> one transaction: descriptor + grants + document + version + upload_request
     version: UPDATE latest_version_number (row lock); same bytes as latest -> 200
```

A document is a Guard resource: its `resource_descriptors` row and grants are the ACL anchor and every version inherits it. `documents` holds BRN-06 metadata (`domain`, `project`, `document_date`) and the version counter; `document_versions` are append-only for the runtime role, which may update only `documents.latest_version_number` (a trigger allows only +1). Restrictive RLS policies bind new descriptors and grants to the acting subject, and stored upload responses are visible only to their sender. Duplicate detection never consults documents the caller did not create, so neither responses, timing, nor audit rows reveal hidden documents; a re-upload with a different classification, department, or grant set becomes a new document. Storage keys and paths never leave the API. Readiness probes the store. Published migrations remain immutable; `0004_upgrade_compatibility` upgrades existing Iteration 4 databases, tightens runtime grants, and adds tenant-safe version references without a volume reset. Parsing, quarantine, preview and downloads arrive with Iteration 6.

Original files are immutable. A `DocumentVersion` owns normalized blocks; each `Chunk` points to a page/section/table/sheet/row/cell locator. Embeddings are derived and replaceable. Facts never replace citations to their original source.

### Retrieval

1. Compile tenant and ACL constraints into SQL.
2. Retrieve lexical and semantic candidates inside the allowed set.
3. Merge ranks using reciprocal-rank fusion.
4. Optionally rerank locally after authorization.
5. Enforce diversity and evidence coverage.
6. Return `EvidenceRef` objects, not untracked strings.

## 6. KRIBU Engine

```mermaid
flowchart TD
    START([Request]) --> CTX[Validate tenant and user context]
    CTX --> INTENT[Classify intent and select skill]
    INTENT --> AUTH{Skill authorized?}
    AUTH -- No --> DENY[Return safe denial]
    AUTH -- Yes --> PLAN[Create evidence plan]
    PLAN --> RET[Authorized retrieval subgraph]
    RET --> ENOUGH{Enough evidence?}
    ENOUGH -- No --> GAP[Report evidence gap]
    ENOUGH -- Yes --> EXTRACT[Typed extraction]
    EXTRACT --> CALC[Deterministic calculations]
    CALC --> ANALYZE[Cross-source analysis]
    ANALYZE --> VERIFY[Citation and policy validation]
    VERIFY --> VALID{Valid and grounded?}
    VALID -- No --> REPAIR[Bounded repair or qualify]
    REPAIR --> VERIFY
    VALID -- Yes --> OUTPUT[Compose response and artifacts]
    OUTPUT --> SIDE{Side effect requested?}
    SIDE -- No --> SAVE[Persist, audit, stream]
    SIDE -- Yes --> APPROVAL[Interrupt for human approval]
    APPROVAL --> SAVE
    GAP --> SAVE
    DENY --> SAVE
    SAVE --> END([Complete])
```

### State and tools

- `RunState`: request, tenant context, selected skill/version, evidence plan, evidence refs, extracted facts, findings, artifacts, approval state, errors, and retry counters.
- Nodes receive narrow typed inputs and return explicit state updates.
- Tools call application services; nodes do not issue arbitrary SQL or filesystem operations.
- PostgreSQL checkpoints make interrupts, retries, and process restarts durable.
- Repair loops have hard attempt limits and route to a qualified answer rather than looping indefinitely.

## 7. Technology stack

All demo services are self-hosted and usable without a paid account.

| Area | Selection | Notes |
|---|---|---|
| Web | Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query | Self-hosted; REST and SSE client |
| API | Python, FastAPI, Pydantic, SQLAlchemy, Alembic | Modular monolith with typed contracts |
| Workflow | LangGraph OSS | Durable graphs, checkpoints, streaming, interrupts |
| Model inference | Google AI Studio Gemini free tier behind `ModelProvider` | Demo default; synthetic data only; model and provider remain configurable |
| Fallback inference | Ollama adapter (optional) | Not required for the demo; useful for offline/private deployments later |
| Embeddings/reranking | Sentence Transformers with BGE-family open models | Local, configurable, multilingual-capable |
| Parsing | Docling; openpyxl for exact spreadsheet provenance | RapidOCR/Tesseract when OCR is required |
| Database/search | PostgreSQL + pgvector | Relational data, full-text search, vectors, RLS |
| Object storage | Local filesystem adapter for demo | S3-compatible adapter added when deployment requires it |
| Identity | Keycloak | Self-hosted OIDC, demo users/groups/roles |
| Policy | Open Policy Agent (OPA) | Versioned RBAC/ABAC policy-as-code |
| Jobs | Celery + RabbitMQ | Ingestion and independent background work; not LangGraph state |
| Observability | Structured logs + OpenTelemetry | Langfuse FOSS is an optional local Compose profile |
| Testing | pytest, Vitest only where useful, Playwright smoke tests | Security, retrieval, citations, graphs, and three journeys |
| Tooling | uv, pnpm, Ruff, mypy, ESLint, Prettier | Versions pinned after the scaffold spike |
| Runtime | Docker Compose | API/web/database local; Gemini is the only external inference dependency |

References: [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [OPA](https://www.openpolicyagent.org/docs), [Docling formats](https://docling-project.github.io/docling/usage/supported_formats/), [pgvector](https://github.com/pgvector/pgvector), [Keycloak](https://www.keycloak.org/), [Next.js self-hosting](https://nextjs.org/docs/app/guides/self-hosting), and [Gemini API billing/data terms](https://ai.google.dev/gemini-api/docs/billing/).

### Gemini demo boundary

The demo uses Gemini through the official `google-genai` SDK and a `ModelProvider` adapter. The API key is read only by the backend, never exposed to the browser, and never committed. Requests contain synthetic demo documents only. Google documents that unpaid Gemini API/AI Studio content may be used to improve products and may be reviewed by humans; therefore real salary, HR, customer, or client-confidential data is prohibited on this provider. Production use requires an approved paid/private data-processing arrangement or a self-hosted provider.

The provider adapter must implement structured output, bounded retries for quota responses, timeout handling, model/version logging, and a clear `provider_unavailable` error. LangGraph, Guard, Brain, citations, and deterministic calculations must not depend on Gemini-specific APIs.

### Identity and tenant boundary

Keycloak `26.8.0` runs locally with a dedicated PostgreSQL store and imports the versioned `kribu-demo` realm. Access tokens use the browser-visible issuer while the containerized API reads signing keys from Keycloak's internal JWKS endpoint. FastAPI accepts only RS256 tokens with the expected issuer, `kribu-api` audience, expiry, subject, tenant UUID, and realm roles.

The API derives `CurrentUser` exclusively from verified claims. Every tenant-scoped SQLAlchemy transaction sets `app.tenant_id` and `app.user_id` locally before querying. The runtime connects as the non-superuser, non-`BYPASSRLS` `kribu_app` role; Alembic runs separately with the database owner. PostgreSQL RLS is enabled and forced on tenant-owned tables, so a missing tenant context returns no rows and cross-tenant writes fail.

## 8. Monorepo structure

```text
Kribu-Demo/
|-- apps/
|   `-- web/                         # Next.js Studio and admin UI
|-- services/
|   |-- api/
|   |   |-- app/
|   |   |   |-- api/                # HTTP/SSE routes and dependencies
|   |   |   |-- core/               # config, errors, logging, transactions
|   |   |   |-- ai/                 # model-provider contracts and adapters
|   |   |   |-- identity/           # OIDC context and tenant resolution
|   |   |   |-- policy/             # OPA client and authorization service
|   |   |   |-- documents/          # metadata, versions, upload lifecycle
|   |   |   |-- brain/              # provenance, facts, entities, retrieval
|   |   |   |-- engine/             # graph, state, nodes, tools, checkpoints
|   |   |   |-- skills/             # registry and three domain skill packs
|   |   |   |-- approvals/          # interrupts and decisions
|   |   |   |-- artifacts/          # generated outputs and downloads
|   |   |   `-- audit/              # append-only application events
|   |   |-- migrations/
|   |   `-- tests/                   # focused unit/integration/security tests
|   `-- worker/                      # ingestion and indexing Celery tasks
|-- packages/
|   |-- ui/                          # shared React primitives and tokens
|   `-- api-client/                  # generated TypeScript API client
|-- policies/
|   |-- rego/                        # OPA policy modules
|   `-- tests/                       # policy decision tables
|-- data/
|   `-- demo/
|       |-- ngo-project/
|       |-- hr/
|       |-- complaints/
|       `-- golden/                  # expected facts and answers
|-- infra/
|   |-- compose/
|   |-- keycloak/                    # exported demo realm
|   `-- observability/
|-- scripts/                         # repeatable bootstrap/seed commands
|-- Docs/                            # source requirements and diagrams
|-- PRD.md
|-- Architecture.md
|-- rules.md
|-- phases.md
|-- design.md
`-- memory.md
```

## 9. Core data contracts

- `Tenant`, `UserProfile`, `RoleAssignment`, `PolicyBundle`
- `Source`, `Document`, `DocumentVersion`, `NormalizedBlock`, `Chunk`
- `ACLDescriptor`, `AuthorizationDecision`
- `Entity`, `Fact`, `Relationship`, each with evidence references
- `EvidenceRef(document_version_id, locator, excerpt_hash, score)`
- `SkillDefinition(version, schemas, permissions, side_effect_level)`
- `Run`, `RunCheckpoint`, `Finding`, `Artifact`
- `ApprovalRequest`, `ApprovalDecision`, `ConnectorAction`
- `AuditEvent(actor, action, resource, decision, correlation_id, timestamp)`

Every tenant-owned table carries `tenant_id`. Source-derived rows carry `document_version_id`; deleting an active source marks it unavailable and triggers index cleanup rather than silently erasing audit history.

## 10. API surface

- `POST /v1/documents/uploads`, `POST /v1/documents/{id}/versions`, `GET /v1/documents/{id}`
- `POST /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events` (SSE)
- `GET /v1/runs/{id}/findings`, `GET /v1/evidence/{id}`
- `GET /v1/artifacts/{id}`
- `GET /v1/approvals`, `POST /v1/approvals/{id}/decision`
- `GET /v1/skills`, administration endpoints for demo metadata/policies
- `GET /v1/audit-events`
- `GET /v1/identity/me` returns the authenticated, provisioned demo identity and trusted tenant context.

Errors use a stable problem-details envelope with a safe message, machine code, correlation ID, and retryability. Internal prompts, stack traces, secrets, and inaccessible resource details are never returned.

## 11. Evolution after demo approval

- Add client-specific source adapters through the `Connector` interface after discovery.
- Replace local filesystem storage with an object-store adapter when deployment needs it.
- Replace Gemini free-tier access with an approved paid/private model provider or self-hosted model before any real client data is connected.
- Benchmark alternate providers without changing graph or skill contracts.
- Add approval-backed external actions using narrow OAuth scopes and idempotency keys.
- Add dedicated tenant deployment, HA, backups, and infrastructure-as-code only for the chosen environment.
- Introduce a separate graph database only if measured relationship queries exceed PostgreSQL's practical boundary.
