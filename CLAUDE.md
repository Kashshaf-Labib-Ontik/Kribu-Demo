# KRIBU Demo

Governed, evidence-backed org-intelligence platform (local, free/OSS only, synthetic data only).
Three demo stories: NGO project delays, HR employee history, client complaint patterns.
Product components: **Guard** (authz), **Brain** (ingest + retrieval), **Engine** (LangGraph workflows).

## Built today vs planned

Built so far (Iteration 1 scaffold):
- `apps/web`: Next.js Studio shell, API status card (`lib/api-health.ts`)
- `services/api`: FastAPI app factory, CORS, `X-Correlation-ID` middleware, `/v1/health/live` + `/v1/health/ready`
- `compose.yaml`: postgres (pgvector) + api + web; `infra/compose/postgres/init/001_extensions.sql`

**Not built yet:** Keycloak, OPA, Celery/RabbitMQ, Ollama, Docling, LangGraph, Alembic migrations,
`packages/`, `policies/`, `data/demo/`, `services/worker/`. Don't search for them. The target layout is
in `Architecture.md` §8. Iteration roadmap is in `phases.md` §3.

## Stack (pinned)

| Area | Tooling |
|---|---|
| Web | Next.js 16.4, React 19.3, TypeScript 6 (strict), Tailwind 4, ESLint 9, Prettier |
| API | Python 3.11 only, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 async + asyncpg, uvicorn |
| DB | PostgreSQL 18 + pgvector 0.8.7 (`pgvector/pgvector:0.8.7-pg18-bookworm`) |
| Py tooling | uv workspace (root `pyproject.toml`, member `services/api`), Ruff (line 100), mypy strict + pydantic plugin, pytest + pytest-asyncio + httpx |
| JS tooling | pnpm 12 workspace, Node 24-26. Web package name: `@kribu/web` |

## Commands (run from repo root, PowerShell on Windows)

```powershell
pnpm install --frozen-lockfile; uv sync --package kribu-api   # install
docker compose up --build                                       # full stack: web :3000, api :8000, docs :8000/docs
docker compose -f compose.yaml -f compose.integration.yaml up -d postgres db-bootstrap migrate seed opa  # backing services on loopback ports, then run apps on host:
uv run --package kribu-api uvicorn app.main:app --app-dir services/api --reload
pnpm dev:web
pnpm check            # web lint + typecheck, api pytest + ruff + mypy (the gate)
pnpm test:api | lint:api | format:api | typecheck:api | lint:web | typecheck:web | build:web
docker compose config --quiet
```

## Code map

- `services/api/app/main.py`: `create_app()`, lifespan creates `app.state.database_engine`
- `services/api/app/core/config.py`: `Settings` (env prefix `KRIBU_`, reads `.env` or `../../.env`), `get_settings()` cached
- `services/api/app/api/router.py` → `routes/*.py`; mounted under `/v1`
- `services/api/app/schemas/`: Pydantic response models
- `services/api/tests/`: pytest (root pytest config sets `pythonpath = services/api`)
- `apps/web/app/`: App Router (`layout.tsx`, `page.tsx`, `globals.css`)
- Env vars: see `.env.example`. Web server-side uses `INTERNAL_API_BASE_URL`, browser uses `NEXT_PUBLIC_API_BASE_URL`

## Conventions (short form; full rules in `rules.md`)

- Routes stay thin: authenticate, validate, delegate, map errors. Business logic goes in services, never in routes, React components or graph nodes.
- Errors: RFC 9457 problem details with `code` and `correlation_id` (see `routes/health.py` readiness). No stack traces, SQL or paths in responses.
- Authz: deny by default. Tenant isolation in app queries **and** Postgres RLS. ACL filter inside the retrieval query. LLMs never grant access.
- Typed everything: no `Any`, use Pydantic at boundaries. `Decimal` for money, UTC in storage, ISO 8601 at APIs.
- DB changes only through Alembic migrations (once Alembic is added).
- Pin every dependency and image. No `latest`. Prefer stdlib over new deps.
- Studio talks to the API only, never directly to DB/OPA/Keycloak/Ollama.
- Tests are risk-based (security, retrieval, citations, graph behavior, API integration), not coverage-percentage driven.

## Git and workflow rules (owner-enforced)

- Never commit or push until the owner reviews the working tree and explicitly approves.
- Commit messages: short imperative, e.g. `Add document ingestion pipeline`. **Do not mention AI, Claude, Codex or co-authors**, so omit `Co-Authored-By` trailers.
- Update `memory.md` (current state, decisions, next step) in every material implementation commit.
- Working branch: `dev-v1.0.x`; PRs target `main`.

## Reference docs (read only when the task needs them)

- `PRD.md`: requirements and acceptance criteria per story
- `Architecture.md`: flows, Guard/Brain/Engine design, data contracts (§9), planned API surface (§10)
- `phases.md`: iterations and synthetic data plan
- `design.md`: UI tokens, typography, screens, status language
- `memory.md`: current handoff state and open questions
- `Docs/`: source SRS, diagrams, PDFs. Large; avoid unless asked.
