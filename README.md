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

The Studio runs at `http://localhost:3000`, the API at `http://localhost:8000`, Keycloak at `http://localhost:8180`, and API documentation at `http://localhost:8000/docs` in development. Compose also runs OPA internally, bootstraps the restricted API database role, applies schema-only Alembic migrations, seeds the synthetic demo rows (`scripts/seed_demo.py`, idempotent, run as the schema owner), and imports the synthetic Keycloak realm.

Migrations no longer insert demo rows and the runtime role is read-only on authorization data. A database created before this change still holds the old rows and grants, so recreate the local volumes once: `docker compose down -v` (synthetic data only), then `docker compose up --build`.

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

Iterations 0-4 and the pre-Iteration 5 hardening (test harness and CI, unified API errors and logging, the reusable Guard `authorize()` step) are committed on `dev-v1.0.x`. Iteration 5 document upload and versioning is implemented and verified in the working tree, pending owner review: `POST /v1/documents/uploads`, `POST /v1/documents/{id}/versions`, and `GET /v1/documents/{id}`. Parsing, retrieval and natural-language query enforcement are later iterations.
