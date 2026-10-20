# KRIBU Demo

KRIBU is a governed, evidence-backed organizational intelligence platform. It ingests company documents, retrieves only information the signed-in user may access, and runs durable LangGraph workflows that produce cited answers, reports, and approval-gated actions.

## Demo scope

The first demo implements three reusable vertical slices using synthetic data:

1. NGO Project — detect repeated delivery delays and explain supported causes.
2. HR — reconstruct an employee's service, salary, and benefit history.
3. Client Servicing — find recurring complaint patterns and service gaps.

The demo runs locally except for Gemini free-tier inference. Only built-in or synthetic demo data may be sent to Gemini; client data connectors and paid services are outside the demo scope.

## Planning documents

- [Product requirements](PRD.md)
- [Architecture](Architecture.md)
- [Engineering rules](rules.md)
- [Delivery phases](phases.md)
- [Product design](design.md)
- [Working memory](memory.md)
- [Source documentation](Docs/)

## Local development

Prerequisites:

- Node.js 24-26 and pnpm 12
- Python 3.11 and uv
- Docker Desktop with Docker Compose

Install the locked dependencies:

```powershell
Copy-Item .env.example .env
pnpm install --frozen-lockfile
uv sync --package kribu-api
```

Start the complete local foundation:

```powershell
docker compose up --build
```

The Studio runs at `http://localhost:3000`, the API at `http://localhost:8000`, Keycloak at `http://localhost:8180`, and API documentation at `http://localhost:8000/docs` in development. Compose also runs OPA internally, bootstraps the restricted API database role, applies Alembic migrations, runs the idempotent synthetic seed (`scripts/seed_demo.py`) as the schema owner, and imports the synthetic Keycloak realm. Historical migrations retain their original demo fixtures; forward migrations tighten grants without requiring existing volumes to be deleted.

Add a Google AI Studio key to your uncommitted `.env` as `KRIBU_GEMINI_API_KEY`. Verify structured output, streaming, usage metadata, and function selection with the script's built-in synthetic prompts:

```powershell
Set-Location services/api
uv run python -m scripts.verify_gemini --confirm-synthetic
Set-Location ../..
```

The command refuses placeholder/missing credentials and production mode. It declares a demo tool but does not execute it.

Verify OIDC tokens, both seeded tenant identities, anonymous denial, and live PostgreSQL RLS:

```powershell
Set-Location services/api
uv run python -m scripts.verify_identity --confirm-synthetic
Set-Location ../..
```

The local demo usernames and replaceable development passwords are documented in `.env.example`. The `kribu-verifier` password flow exists only for this verification command; Studio will use authorization code with PKCE in a later iteration.

Verify the Guard's synthetic records through Keycloak, API, OPA, RLS, and audit storage:

```powershell
Set-Location services/api
uv run python -m scripts.verify_guard --confirm-synthetic
Set-Location ../..
docker compose run --rm -v ./policies/tests:/tests opa test --fail-on-empty /policies /tests
```

The protected API is `GET /v1/demo/resources/{resource_id}`. Seeded IDs are in `scripts/verify_guard.py`. Mike is denied the synthetic salary record, Helen can read it, and tenant-crossing reads return the same safe `404` as unavailable records. OPA has no host port; only the API makes policy decisions. The record content and salary amount are fictional.

Verify the complete synthetic document lifecycle through Keycloak, OPA, PostgreSQL RLS, audit storage, and the object-store adapter:

```powershell
Set-Location services/api
uv run python -m scripts.verify_documents --confirm-synthetic
Set-Location ../..
```

Iteration 6 adds Redis-backed, single-concurrency Celery parsing. PostgreSQL is authoritative: upload/version creation atomically writes a queued ingestion job and outbox row; the worker republishes queued work after a Redis outage, and duplicate messages cannot publish duplicate extractions. The worker parses PDF (CPU-only native Docling parser plus exact `pypdf` pages), DOCX, XLSX, CSV, TXT, and Markdown without LLMs or OCR. Successful versions publish normalized blocks and immutable locators in one transaction; malformed, encrypted, unsafe, or limit-exceeding inputs are quarantined and never previewable. The default limits are 120 seconds, 250 PDF pages, and 100,000 content units; all are configurable.

The protected endpoints are `POST /v1/documents/uploads`, `POST /v1/documents/{id}/versions`, `GET /v1/documents/{id}`, `GET /v1/documents/{id}/versions/{version_id}/preview`, and `GET /v1/documents/{id}/versions/{version_id}/download`. Preview returns `202` while queued/processing and safe `409` when quarantined; inaccessible content remains `404`.

Verify the asynchronous parsing lifecycle (safe generated content only):

```powershell
Set-Location services/api
uv run python -m scripts.verify_document_parsing --confirm-synthetic
Set-Location ../..
```

The repeatable source packs for NGO, HR, and client servicing are under `services/api/demo_data/`. Run `services/api/scripts/load_demo_documents.py --confirm-synthetic` after Compose is healthy; it uploads each source with its ACL and waits for a non-empty authorized preview.

Iteration 7 indexes every successfully parsed version with deterministic structure-aware chunks, exact source references, PostgreSQL full-text search, and 768-dimensional `gemini-embedding-2` vectors. PostgreSQL index jobs/outbox rows make Celery delivery retryable; a complete generation becomes searchable atomically. Search evaluates the current document ACLs through Guard first, then runs both ranking branches inside the allowed document set. Only the latest version is eligible, and a latest version whose index is not ready never falls back to stale evidence.

Load the synthetic packs, verify the live retrieval boundary, and evaluate the 12 positive plus 6 authorization-negative golden queries:

```powershell
Set-Location services/api
uv run python -m scripts.load_demo_documents --confirm-synthetic
uv run python -m scripts.verify_retrieval --confirm-synthetic
uv run python -m scripts.evaluate_retrieval --confirm-synthetic
Set-Location ../..
```

The protected API is `POST /v1/retrieval/search`. It returns ranked, citation-ready evidence marked as untrusted source material; it does not generate an answer. ACL revocation takes effect without re-embedding. Gemini embedding failure, OPA failure, or required audit failure returns `503`; an authorized search with no evidence returns an empty `200` response. Gemini free-tier embedding remains synthetic-only because unpaid inputs may be used by Google to improve its products.

For faster application development, run PostgreSQL in Docker and the applications on the host:

```powershell
docker compose up -d postgres db-bootstrap migrate seed keycloak-postgres keycloak opa
uv run --package kribu-api uvicorn app.main:app --app-dir services/api --reload
pnpm dev:web
```

Run the focused scaffold checks:

```powershell
pnpm check
pnpm test:policy
pnpm build:web
docker compose config --quiet
```

Run the integration suite (real PostgreSQL RLS and grants, real OPA, test-signed tokens). It recreates a dedicated `kribu_test` database on the Compose PostgreSQL and never touches `kribu`. Compose OPA has no host port, so start a throwaway OPA for the tests:

```powershell
docker run -d --rm --name kribu-opa-test -p 127.0.0.1:8181:8181 -v ./policies/rego:/policies:ro openpolicyagent/opa:1.21.2 run --server --addr=0.0.0.0:8181 /policies
pnpm test:integration
docker stop kribu-opa-test
```

Overrides: `KRIBU_TEST_OWNER_DATABASE_URL` (default `postgresql://kribu:kribu_dev_only@localhost:5432/kribu`), `KRIBU_TEST_APP_DB_PASSWORD` and `KRIBU_TEST_OPA_URL`. If another PostgreSQL already listens on host port 5432, set `POSTGRES_PORT` for Compose and point `KRIBU_TEST_OWNER_DATABASE_URL` at that port. CI (`.github/workflows/ci.yml`) runs the checks, policy tests and integration suite on every push.

## Current status

Iterations 0-7 are implemented and verified locally; Iteration 7 remains uncommitted pending owner review. KRIBU Brain now provides authorization-first hybrid retrieval with durable indexing, exact provenance, live ACL evaluation, PostgreSQL FTS/pgvector ranking, RRF, diversity limits, safe retrieval audits, and a measured synthetic golden set. Gemini answer generation and LangGraph orchestration begin in Iteration 8. OCR, malware scanning, and blob garbage collection remain deferred.
