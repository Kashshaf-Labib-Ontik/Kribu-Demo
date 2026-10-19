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

The Studio runs at `http://localhost:3000`, the API at `http://localhost:8000`, Keycloak at `http://localhost:8180`, and API documentation at `http://localhost:8000/docs` in development. Compose bootstraps the restricted API database role, applies Alembic migrations, and imports the synthetic Keycloak realm.

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

For faster application development, run PostgreSQL in Docker and the applications on the host:

```powershell
docker compose up -d postgres db-bootstrap migrate keycloak-postgres keycloak
uv run --package kribu-api uvicorn app.main:app --app-dir services/api --reload
pnpm dev:web
```

Run the focused scaffold checks:

```powershell
pnpm check
pnpm build:web
docker compose config --quiet
```

## Current status

Iteration 2 is committed and live-verified. Iteration 3 is implemented and live-verified in the uncommitted working tree: local Keycloak identity, strict JWT validation, trusted request context, Alembic-managed tenant tables, and PostgreSQL RLS. It is awaiting owner review.
