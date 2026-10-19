# KRIBU Demo Delivery Phases

## 1. Delivery model

Build in short vertical iterations. Each iteration ends with a runnable behavior, focused verification, an updated `memory.md`, and a concise commit. Do not implement all infrastructure before proving one end-to-end path.

### Estimate

- **One experienced full-stack/AI developer:** approximately 8-10 weeks full-time.
- **Two developers with clear web/platform ownership:** approximately 5-7 weeks.
- Add 1-2 weeks if Gemini quota limits, API reliability, or document parsing needs extensive tuning.

This is a planning range, not a deadline. It assumes synthetic data, three stories, no live connectors, and prompt evaluation rather than model training.

## 2. Phase plan

| Phase | Typical duration | Outcome | Exit gate |
|---|---:|---|---|
| 0. Alignment and repository | 1-2 days | Living requirements, architecture, rules, design, delivery plan | Scope and open decisions reviewed |
| 1. Technical spike and scaffold | 3-5 days | Monorepo, Compose, web/API, PostgreSQL/pgvector, Gemini configuration | One typed model call and health flow work locally |
| 2. Guard foundation | 4-6 days | Keycloak, tenant context, OPA RBAC/ABAC, RLS, audit decisions | Unauthorized salary and cross-tenant tests deny before retrieval |
| 3. Brain foundation | 7-10 days | Upload, versioning, parsing, provenance, indexing, authorized hybrid search | A cited page/cell can be retrieved and previewed safely |
| 4. Engine vertical slice | 6-8 days | Durable LangGraph, SSE, checkpoints, typed extraction, citations | NGO golden query works end to end |
| 5. Three domain skills | 7-10 days | NGO, HR, and complaint workflows/artifacts | Each story passes its golden evaluation |
| 6. Approvals and product UX | 4-6 days | Draft artifacts, approval interrupt, evidence UI, audit timeline | Approval/reject/resume and three user journeys work |
| 7. Hardening and demo release | 4-6 days | Failure handling, security checks, seed/reset, runbook | Fresh-machine rehearsal and acceptance checklist pass |

## 3. Small implementation iterations

The commit messages below are targets and may be adjusted to match the actual slice.

### Iteration 0 - Planning baseline

- Initialize Git, set `main`, add the GitHub remote, and create the living documents.
- Confirm the three selected stories and free/open-source constraint.
- **Commit:** `Define project delivery baseline`

### Iteration 1 - Developer scaffold

- Create `apps/web`, `services/api`, shared tooling, `.env.example`, and Docker Compose.
- Add web/API/PostgreSQL health checks and repeatable bootstrap commands.
- **Commit:** `Scaffold local development stack`

### Iteration 2 - Gemini provider and structured-output spike

- Configure the official Gemini SDK through a backend-only `ModelProvider` adapter.
- Verify structured Pydantic output, bounded retries, streaming where supported, and one tool/function call using synthetic prompts.
- Record model, quota response, latency, token usage, and failure behavior; keep the model configurable.
- Add a hard synthetic-data policy and prevent accidental use of a missing/production credential.
- **Commit:** `Integrate Gemini demo provider`

### Iteration 3 - Identity and tenant boundary

- Seed Keycloak realm/users/roles and validate OIDC tokens in FastAPI.
- Add tenant-owned base tables, request context, and PostgreSQL RLS.
- **Commit:** `Establish tenant identity boundary`

### Iteration 4 - RBAC and ABAC policy

- Add OPA policies, canonical attributes, decision logging, and policy tests.
- Prove Roger Albert's synthetic salary record is inaccessible to Mike through the protected API, even if callers supply forged tenant/role parameters. Full natural-language paraphrase tests follow authorized retrieval and Engine integration.
- **Commit:** `Enforce RBAC and ABAC policies`

### Iteration 5 - Document upload and versioning

- Add safe upload, hashing, metadata/ACL assignment, original storage, status, and duplicate behavior.
- **Commit:** `Add document upload lifecycle`

### Iteration 6 - Parsing and provenance

- Parse selected document types with Docling/openpyxl and preserve page/cell locators.
- Add failure quarantine and normalized document preview.
- **Commit:** `Preserve document extraction provenance`

### Iteration 7 - Authorized hybrid retrieval

- Generate local embeddings, add PostgreSQL full-text/vector indexes, RRF, and evidence contracts.
- Apply tenant/ACL predicates before candidates reach ranking or models.
- **Commit:** `Implement authorized hybrid retrieval`

### Iteration 8 - LangGraph runtime

- Add typed state, PostgreSQL checkpointing, SSE progress, bounded retries, and a basic retrieve-analyze-verify graph.
- **Commit:** `Add durable LangGraph execution`

### Iteration 9 - NGO vertical slice

- Build the first complete skill and synthetic evidence/golden answer.
- Generate cited findings and a management briefing draft.
- **Commit:** `Implement NGO project analysis skill`

### Iteration 10 - HR vertical slice

- Build service-history timeline, deterministic salary changes, benefits checks, and missing-record detection.
- Verify HR-only access and safe denial for other roles.
- **Commit:** `Implement employee history skill`

### Iteration 11 - Complaint vertical slice

- Build complaint normalization, supported grouping, recurrence counts, service-gap analysis, and insight artifact.
- **Commit:** `Implement complaint insight skill`

### Iteration 12 - Approval and audit journey

- Add artifact versioning, approval interrupt/edit/reject/resume, and run audit timeline.
- Keep all proposed external actions as non-executing demo drafts.
- **Commit:** `Add approval and audit workflow`

### Iteration 13 - Studio completion

- Complete query workspace, progress, findings, evidence drawer, document preview, artifacts, approvals, admin seed controls, accessibility, and responsive states.
- **Commit:** `Complete governed analysis experience`

### Iteration 14 - Demo release

- Add seed/reset scripts, focused security/regression checks, error states, backup/export of demo configuration, and presenter runbook.
- Rehearse all three stories from a clean environment.
- **Commit:** `Prepare first demo release`

## 4. Synthetic data plan

Create expected facts before tuning prompts.

- **NGO:** six periods, two repeated delays, ongoing expenditure, two documented blockers, one unsupported suspected cause, and one conflicting report.
- **HR:** appointment, several salary revisions, policy changes, one missing revision letter, and one inconsistent effective date.
- **Complaints:** several channels, repeated issue language with variation, resolution/reopen events, service stages, and a few unrelated outliers.
- Assign each file a classification and ACL so every story includes at least one permitted and one restricted retrieval case.
- Store golden facts and evidence locators in machine-readable files; do not derive goldens from model output.

## 5. Learning path before and during kickoff

1. Git, Docker Compose, Python/FastAPI/Pydantic, PostgreSQL/SQLAlchemy, and TypeScript/Next.js.
2. OIDC/JWT, Keycloak, RBAC, ABAC, OPA/Rego, RLS, and document ACLs.
3. Embeddings, chunking, hybrid retrieval, reranking, provenance, and prompt injection.
4. LangGraph state, nodes, tools, checkpoints, interrupts, streaming, retries, and idempotency.
5. Docling/openpyxl extraction, Gemini structured outputs, provider adapters, and prompt-injection controls.
6. OpenTelemetry, golden datasets, retrieval/citation evaluation, and demo operations.

Use a small working exercise for each topic rather than completing long courses before writing any code.

## 6. Primary technical risks

| Risk | Effect | Mitigation / early proof |
|---|---|---|
| Gemini quota, outage, or policy change | Demo interruption or unavailable inference | Bound retries, show provider status, cache/replay synthetic fixtures, keep provider adapter and optional Ollama fallback |
| Document layouts lose provenance | Incorrect citations | Build representative PDFs/XLSX early; keep immutable locators; preview exact evidence |
| Authorization is applied after search | Sensitive leakage | Policy and SQL/RLS gates before retrieval; mandatory negative tests |
| Generic schemas become domain-specific | Difficult client onboarding | Canonical metadata plus versioned client mapping/adapters; no hard-coded names |
| Agent graph becomes unpredictable | Long, costly, irreproducible runs | Explicit nodes, schemas, bounded loops, deterministic calculations, checkpoints |
| Synthetic demo overfits prompts | Demo does not generalize | Include paraphrases, conflicts, missing evidence, and outliers in goldens |
| Too many self-hosted services overwhelm setup | Slow development | Core Compose profile first; optional observability profile; modular monolith |
| OCR/model downloads fail during presentation | Demo outage | Pre-fetch approved weights, offline smoke rehearsal, deterministic reset script |

## 7. Demo release definition

- Clean startup and seed from documented commands.
- Three role-appropriate stories complete successfully.
- Evidence links open exact source locations.
- Unauthorized HR data remains unavailable through query, search, preview, artifact, and citation paths.
- All findings distinguish evidence, calculation, inference, conflict, and missing information.
- Approval decisions pause/resume durably and all actions stay drafts.
- Focused security, graph, retrieval, citation, API, and browser smoke checks pass.
- Repository is free of secrets, real client data, model weights, volumes, and accidental generated files.
- Presenter runbook includes expected duration, reset procedure, and fallback screenshots/artifacts.

## 8. Current delivery gate

Iterations 0-3 are owner-reviewed, committed, and pushed on `dev-v1.0.x`. Iteration 4 is implemented and live-verified in the working tree, pending owner review. It adds OPA-backed RBAC/ABAC, reusable resource ACL metadata, a protected synthetic read, and audit records. Iteration 5 begins document upload after the reviewed Guard slice is accepted. No implementation commit or push occurs without explicit owner approval.
