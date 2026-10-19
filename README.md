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

The Studio runs at `http://localhost:3000`, the API at `http://localhost:8000`, Keycloak at `http://localhost:8180`, and API documentation at `http://localhost:8000/docs` in development. Compose also runs OPA internally, bootstraps the restricted API database role, applies Alembic migrations, seeds the synthetic demo tenants and records (`scripts/seed_demo.py`), and imports the synthetic Keycloak realm.

Migrations are schema-only and the runtime `kribu_app` role is read-only on authorization data (append-only on audit). A database created before this change still has the old grants and seed rows from earlier migrations; recreate it once:

```powershell
docker compose down
docker volume rm kribu_kribu_postgres_data
docker compose up --build
```

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
pnpm test:policy
```

The protected API is `GET /v1/demo/resources/{resource_id}`. Seeded IDs are in `scripts/seed_demo.py`. Mike is denied the synthetic salary record, Helen can read it, and tenant-crossing reads return the same safe `404` as unavailable records. OPA has no host port; only the API makes policy decisions. The record content and salary amount are fictional.

For faster application development, run the backing services in Docker and the applications on the host. The `compose.integration.yaml` overlay publishes PostgreSQL and OPA on loopback-only ports (`127.0.0.1:15432`, `127.0.0.1:18181`) so host processes can reach them without clashing with a locally installed PostgreSQL:

```powershell
docker compose -f compose.yaml -f compose.integration.yaml up -d postgres db-bootstrap migrate seed keycloak-postgres keycloak opa
uv run --package kribu-api uvicorn app.main:app --app-dir services/api --reload
pnpm dev:web
```

Run the checks (CI runs the same three groups on every push and pull request):

```powershell
pnpm check              # web lint + types, API ruff + mypy + unit tests
pnpm test:policy        # OPA policy tests
pnpm build:web
docker compose config --quiet
```

### Integration tests

The integration suite runs the real API in-process against PostgreSQL (RLS, grants, audit) and OPA. Each run creates and drops its own `kribu_integration` database, applies migrations, and seeds demo data; tokens are signed locally, so Keycloak is not needed.

```powershell
docker compose -f compose.yaml -f compose.integration.yaml up -d postgres db-bootstrap opa
pnpm test:integration
```

Override the endpoints with `KRIBU_TEST_OWNER_DATABASE_URL`, `KRIBU_TEST_APP_DB_PASSWORD`, and `KRIBU_TEST_OPA_URL` when they differ from the compose defaults.

## Current status

Iterations 0-3 are committed and pushed on `dev-v1.0.x`. Iteration 4 is implemented and live-verified in the working tree, pending owner review. It adds OPA-backed RBAC/ABAC, resource ACL metadata, a protected synthetic read path, and append-only runtime audit records. Document ingestion and natural-language query enforcement are later iterations.
