# KRIBU Project Memory

This is the current implementation handoff. Update it in every material implementation commit; keep it factual and short. Git history remains the detailed record.

## Current status

- **Lifecycle:** Iterations 0-7 are implemented and verified locally. Iteration 7 adds authorization-first hybrid retrieval over immutable Iteration 6 provenance.
- **Active area:** Iteration 7 owner review; changes remain uncommitted.
- **Application code:** Keycloak identity, RLS, OPA RBAC/ABAC, protected synthetic resource access, and append-only authorization audit are committed.
- **Selected stories:** NGO Project, HR Employee History, Client Complaint Patterns.
- **Data:** Built-in synthetic identities, Guard resources, and upload fixtures are available; no client data sources are connected.
- **Cost constraint:** Demo uses free/open-source infrastructure and Gemini free-tier inference for synthetic data; no paid billing is enabled.
- **Reference hardware:** 16 GB total system RAM with integrated Intel UHD graphics using shared memory; do not require local LLM inference.

## Completed

- Existing SRS, demo stories, architecture diagrams, and LangGraph design were reviewed.
- Git repository was initialized on branch `main`.
- GitHub remote was configured as `https://github.com/Kashshaf-Labib-Ontik/Kribu-Demo.git`.
- Root README and the six living collaboration documents were prepared.
- The architecture decision was aligned to LangGraph rather than PydanticAI for durable product growth.
- Iteration 1 was committed and pushed on `dev-v1.0.x`.
- The Gemini decision and standalone web-container fix were committed and pushed.
- Iteration 2 was committed and pushed as `4d43182` with a typed `ModelProvider`, Gemini adapter, synthetic-only enforcement, structured output, streaming, function selection, metadata, and live verification.
- Iteration 3 was committed and pushed as `62a3c5c` with a pinned Keycloak realm, strict OIDC validation, tenant-scoped sessions, Alembic migrations, a restricted runtime database role, and forced PostgreSQL RLS.
- Iteration 4 was committed as `c38d543` with pinned OPA `1.21.2`, `guard-v1` Rego policy, canonical subject/resource/action inputs, ACL metadata, synthetic proof content, and tenant-scoped append-only runtime audit.
- Hardening Group 1 (`3ced2fb`): hermetic test settings; idempotent `scripts/seed_demo.py` and a Compose `seed` service; runtime least-privilege grants; audit `request_id`; integration suite (`pnpm test:integration`, real PostgreSQL + OPA); `pnpm test:policy`; GitHub Actions CI. Published migrations `0001` and `0002` remain immutable; migration `0004_upgrade_compatibility` carries the forward schema and grant corrections.
- Hardening Group 2 (`a260fe2`): `AppError` + RFC 9457 `application/problem+json` for every error (422 never echoes input); pure ASGI request context (validated `X-Correlation-ID`, server `X-Request-ID`, logged 500 problem, CORS wraps it); correlated stdlib logging; required `database_url` (`SecretStr`) and a startup guard refusing superuser/BYPASSRLS/table-owner roles; JWKS outage returns 503 `identity_provider_unavailable`; one `tenant_transaction()`; audit rows carry `request_id`; fixed CORS origins (pydantic's trailing `/` never matched a browser `Origin`).
- Hardening Group 3 (`387bc81`): reusable `app/policy/authorization.py` `authorize()` (one OPA decision, one audit row with the caller's action, fails closed; missing resources deny as `resource_unavailable`); the protected read uses three short tenant transactions and holds no connection during the OPA call; inactive or unprovisioned identities are audited (`identity_not_provisioned`) before the 403. Rego `guard-v1` allowed only `resource.read`.
- Iteration 5: `app/documents/` (models, contracts, errors, stdlib type validation, `LocalFileObjectStore`, ASGI `UploadGuardMiddleware`, service), routes `POST /v1/documents/uploads`, `POST /v1/documents/{id}/versions`, `GET /v1/documents/{id}`, migrations `0003_documents` and `0004_upgrade_compatibility`, Rego `guard-v2` upload rules, Compose `kribu_document_store` volume, readiness store probe, `python-multipart`, and live document verification. Adding a version requires read access as well as the upload rule; own-document duplicates must also match classification, department and grant set; restrictive RLS binds new descriptors/grants to the acting subject; upload replays are private to their sender; the version counter can only advance by one; corrupt OOXML, XLM macro sheets and control characters are rejected. Short temporary object-store names keep atomic writes within Windows path limits.
- Iteration 6: `app/ingestion/` adds a Celery dispatcher and parser worker. Redis `7.4.2` is broker-only, AOF-backed, `noeviction`, memory-capped, and paired with one worker (`--concurrency=1`). Each upload/version transaction creates an RLS-protected ingestion job and Postgres outbox row. The worker receives only a job UUID, resolves trusted context from PostgreSQL, and atomically publishes one extraction plus all normalized blocks or quarantines the version. `0005_document_provenance` and `0006_outbox_returning` are forward-only migration compatibility additions. `app/documents/parsing.py` supports CPU-only PDF (`docling-parse` + page locators), DOCX, XLSX, CSV, TXT, and Markdown; defaults are 120 seconds, 250 PDF pages, and 100,000 units. Preview/download are Guard-protected; preview is `202` while pending, `409` when quarantined, and `404` when unavailable/inaccessible.
- Iteration 7 (uncommitted; owner review pending): `app/brain/` adds deterministic structure-aware chunking, `EmbeddingProvider`, durable index jobs/outbox delivery, immutable generations, active heads, authorization-first hybrid retrieval, RRF/diversity, exact evidence contracts, and append-only retrieval audits. Migration `0007_authorized_hybrid_retrieval` adds forced-RLS FTS and pgvector storage without rewriting history. `POST /v1/retrieval/search` evaluates current OPA ACLs before query embedding and restricts both ranking branches to allowed latest-version active indexes. The synthetic-only model contract is Gemini `gemini-embedding-2`, 768 unit-normalized dimensions, `question-answering-v1`, and `structure-v1`.

## Current decisions

- Modular monorepo: Next.js Studio, FastAPI control plane, worker, PostgreSQL/pgvector, Keycloak, and OPA.
- Three major product components: Guard, Brain, and Engine; supporting components remain explicit modules.
- LangGraph OSS with PostgreSQL checkpoints owns reasoning workflow state.
- Pydantic owns typed contracts; deterministic code owns policy, math, validation, and side effects.
- Authorization uses RBAC + ABAC + document ACLs + RLS. Vector search and LLM reasoning do not grant access.
- Brain uses provenance-aware CPU-only parsing plus PostgreSQL FTS/pgvector hybrid retrieval. Gemini Embedding 2 is the synthetic-demo embedding provider; generation metadata keeps it replaceable.
- Gemini free-tier inference through the official Google SDK is the demo default. It is backend-only, configurable, quota-aware, and restricted to synthetic data.
- `ModelProvider` remains the boundary; Ollama is optional future fallback for offline/private deployments.
- Local filesystem is the demo object store behind an adapter; hosted object storage is deferred.
- All proposed external actions remain drafts behind human approval during the demo.
- Testing stays focused on security, retrieval, citations, graph behavior, API integration, goldens, and four browser journeys.
- Implementation commits and pushes require explicit owner approval; Iteration 7 remains uncommitted pending review.

## Superseded source decisions

- Earlier documentation naming PydanticAI as the orchestrator is superseded by LangGraph plus Pydantic contracts.
- Earlier documentation naming a paid OpenAI model or local Ollama as demo default is superseded by Gemini free-tier inference.
- Earlier scope covering all five stories is narrowed to NGO, HR, and Client Servicing.

## Current file/area being worked on

- `services/api/app/brain`: Iteration 7 indexing, embedding, retrieval, and evidence contracts are complete locally pending review.
- `services/api/migrations`: published history is preserved; existing volumes upgrade forward through `0007_authorized_hybrid_retrieval`.
- `policies/`: `guard-v2` protects reads, document creation, version creation, and the `authorized_retrieval` purpose.

## Verification performed

- Confirmed the selected stories against `Docs/KRIBU_Five_Demo_Stories.md`.
- Confirmed the component/dataflow and LangGraph direction against `Docs/Diagram_PLAN.md` and the architecture pack.
- Confirmed the repository had no previous Git metadata before initialization.
- Web production build, TypeScript, ESLint, API Ruff, and API mypy checks pass.
- Three focused API health/correlation/readiness tests pass; the current FastAPI test client emits one upstream deprecation warning.
- Host-level smoke test passes: liveness `200`, web `200` with API available, and readiness safely returns `503` while PostgreSQL is absent.
- JavaScript and Python frozen lockfile checks pass; Docker Compose configuration validates.
- Docker Desktop is running; PostgreSQL, API, and standalone Next.js web containers are healthy.
- Official Google Gen AI SDK documentation confirms `gemini-3.8-flash` supports structured output, streaming, and function calling.
- Local adapter checks cover synthetic-only enforcement, missing/placeholder and production rejection, typed output metadata, streaming completion, and non-executing tool selection.
- Ruff and mypy pass; 21 focused API/provider/identity tests pass with one upstream TestClient deprecation warning; Compose configuration validates.
- The rebuilt API returns readiness `200`; the web, API, application database, Keycloak, and Keycloak database containers are healthy.
- Live Gemini verification passed with synthetic prompts for structured output, streaming, and non-executing tool selection on `gemini-3.8-flash`.
- Keycloak `26.8.0` starts healthy on local port `8180` with its dedicated PostgreSQL store and imports the synthetic realm.
- The restricted `kribu_app` database role is created idempotently and Alembic applies the initial tenant migration.
- Live OIDC verification succeeds for Mike and the second-tenant user; anonymous access returns `401`.
- Live RLS verification returns zero tenants without context, exactly one matching tenant per context, and blocks a cross-tenant insert.
- Iteration 4 OPA policy tests pass (12/12); Ruff, mypy, and 32 API tests pass with one upstream TestClient warning.
- Fresh migration, full downgrade/rebuild, and the published `0002` to `0004` upgrade path pass against isolated PostgreSQL. The existing demo volume upgraded to `0004_upgrade_compatibility` without deletion and now contains the audit `request_id` column.
- Live Guard verifier confirms Mike salary denial, Helen HR access, Priya programs access, Evan isolation, ignored caller-supplied role/tenant parameters, persisted allow/deny audits, zero resource rows without tenant context, and no runtime audit-update privilege.
- Stopping OPA made API readiness return `503` and a protected read return `503` without content; OPA was restored afterward.
- OPA is isolated on an internal Compose network shared only with the API; its REST API is not published to the host.
- Final Iteration 5 gate: 144 unit tests pass (69 integration-marked tests skipped in the unit command), all 68 PostgreSQL/OPA integration tests pass, and all 35 Rego tests pass. Ruff lint/format, mypy, ESLint, TypeScript, frozen lock, Compose validation, and the production web build pass.
- Live identity/RLS, Guard, document lifecycle, and Gemini verifiers pass. Document verification proves anonymous denial, Helen upload/read, Mike and second-tenant denial, create/version idempotency, same-as-latest handling, and exactly versions 1-2. All long-running Compose services are healthy.
- Iteration 6 focused parser tests pass for PDF, DOCX, XLSX, CSV, TXT/Markdown exact locators, malformed OOXML, and extraction limits. The live parsing verifier passed a unique synthetic upload, idempotent replay, versioning, Redis/outbox dispatch, normalized four-block preview, original-byte download, and cross-tenant `404`. The three-story loader then uploaded and preview-verified all seven NGO, HR, and client-servicing source files through the single worker. Existing Docker volumes upgraded from `0004` through `0006` without deletion; API, Redis, and the one-slot worker are healthy.
- Final Iteration 7 gates pass: 157 non-integration tests, all 91 PostgreSQL/OPA integration tests, all 36 Rego tests, Ruff lint/format, mypy, ESLint, TypeScript, frozen lock, Compose validation, diff checks, and the production web build. Integration coverage includes fresh and `0004 -> head` migrations, RLS/grants, authorization before ranking, exact provenance, narrowing filters, no stale-version fallback, provider `503`, duplicate index publication, and rejection of caller-supplied authorization fields.
- The existing volume upgraded through `0007`; after the uncommitted embedding contract was finalized, only recoverable derived index/audit tables were rebuilt from preserved extractions. The worker completed 13 index jobs with 13 active generations; all stored vector norms are 1.0 and all generations use `question-answering-v1`. Live retrieval returned three NGO and two HR evidence items with zero Mike-salary or cross-tenant leakage. The 12-positive/6-negative golden set achieved Recall@5 1.0, MRR 0.875, and zero authorization violations.
- The standalone Gemini generation verifier received a safe retryable provider `503` on three final reruns; its earlier live verification passed, and all Iteration 7 live Gemini embedding/index/query calls returned successfully.

## Known open questions

- Exact development machine CPU model and operating-system version.
- Whether an offline model fallback is required for the live demo; Gemini itself requires internet access.
- Target live-response latency.

## Next step

After owner review, commit Iteration 7 as `Implement authorized hybrid retrieval`. Then begin Iteration 8: typed LangGraph state, PostgreSQL checkpoints, bounded retrieve-analyze-verify execution, SSE progress, and Gemini answer generation grounded only in the new untrusted evidence contract. OCR, malware scanning, and blob garbage collection remain deferred.

## Update template

```text
Date:
Iteration / commit:
Status:
Implemented:
Files/area active now:
Decisions or changes:
Verification:
Known issues:
Next step:
```
