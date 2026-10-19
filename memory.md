# KRIBU Project Memory

This is the current implementation handoff. Update it in every material implementation commit; keep it factual and short. Git history remains the detailed record.

## Current status

- **Lifecycle:** Iterations 0-4 are committed and pushed (Iteration 4 is `c38d543`). A post-Iteration 4 hardening slice from the engineering review is in progress before Iteration 5.
- **Active area:** Hardening group 1 of 4 (test harness and CI) is owner-approved and committed as `Harden test harness and CI`; its GitHub Actions results are pending. The full remedy plan is in the engineering-review plan (D1-D22, tasks T1-T11).
- **Application code:** Keycloak identity, RLS, OPA RBAC/ABAC, protected synthetic resource access, and authorization audit are committed. Group 1 changes tests, migrations, seed, compose, and CI only.
- **Selected stories:** NGO Project, HR Employee History, Client Complaint Patterns.
- **Data:** Synthetic demo packs must be created; no client data sources are available.
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
- Iteration 4 was committed and pushed as `c38d543` with pinned OPA `1.21.2`, `guard-v1` Rego policy, canonical subject/resource/action inputs, ACL metadata, synthetic proof content, and tenant-scoped append-only runtime audit.
- An engineering review of Iterations 1-4 found 18 issues; the owner approved 22 remedies in four commit groups (safety net, errors/logging, Guard refactor, docs/tests).

## Current decisions

- Modular monorepo: Next.js Studio, FastAPI control plane, worker, PostgreSQL/pgvector, Keycloak, and OPA.
- Three major product components: Guard, Brain, and Engine; supporting components remain explicit modules.
- LangGraph OSS with PostgreSQL checkpoints owns reasoning workflow state.
- Pydantic owns typed contracts; deterministic code owns policy, math, validation, and side effects.
- Authorization uses RBAC + ABAC + document ACLs + RLS. Vector search and LLM reasoning do not grant access.
- Brain uses provenance-aware Docling/openpyxl extraction and authorized hybrid PostgreSQL retrieval.
- Gemini free-tier inference through the official Google SDK is the demo default. It is backend-only, configurable, quota-aware, and restricted to synthetic data.
- `ModelProvider` remains the boundary; Ollama is optional future fallback for offline/private deployments.
- Local filesystem is the demo object store behind an adapter; hosted object storage is deferred.
- All proposed external actions remain drafts behind human approval during the demo.
- Testing stays focused on security, retrieval, citations, graph behavior, API integration, goldens, and four browser journeys.
- No implementation commit or push occurs until the owner reviews the working-tree changes and explicitly approves it.
- Migrations are schema-only; synthetic demo rows come from `scripts/seed_demo.py` (compose `seed` service, owner role). The runtime `kribu_app` role is read-only on authorization data and append-only on audit; each future write feature grants only what it needs in its own migration.
- Security behavior is pinned by an opt-in integration suite (`pnpm test:integration`) against real PostgreSQL and OPA; CI runs the gate, policy tests, and integration tests.

## Superseded source decisions

- Earlier documentation naming PydanticAI as the orchestrator is superseded by LangGraph plus Pydantic contracts.
- Earlier documentation naming a paid OpenAI model or local Ollama as demo default is superseded by Gemini free-tier inference.
- Earlier scope covering all five stories is narrowed to NGO, HR, and Client Servicing.

## Current file/area being worked on

- `services/api/tests/` (hermetic `conftest.py`, shared `tokens.py`, `integration/`), `services/api/scripts/seed_demo.py`, migrations 0001/0002 (schema-only, read-only grants), `compose.yaml` (`seed` service, fixed `kribu_app` role), `compose.integration.yaml`, `.github/workflows/ci.yml`.

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
- Both migrations applied successfully on the existing volume and a fresh temporary database; Alembic reported no schema drift. The temporary verification database was removed afterward.
- Hardening group 1: `pnpm check` passes (32 unit tests, 40 integration tests skipped by default); unit tests pass with `.env` removed; `pnpm test:integration` passes 40/40 against real PostgreSQL and OPA on the pre-refactor code; `pnpm test:policy` passes 12/12; the rebuilt stack seeds 18 rows and `verify_guard` passes end to end through Keycloak.
- A native Windows PostgreSQL service also listens on host port 5432 and shadows the Docker database for host processes; host-run tools use the loopback overlay ports `127.0.0.1:15432` (PostgreSQL) and `127.0.0.1:18181` (OPA).
- Live Guard verifier confirms Mike salary denial, Helen HR access, Priya programs access, Evan isolation, ignored caller-supplied role/tenant parameters, persisted allow/deny audits, zero resource rows without tenant context, and no runtime audit-update privilege.
- Stopping OPA made API readiness return `503` and a protected read return `503` without content; OPA was restored afterward.
- OPA is isolated on an internal Compose network shared only with the API; its REST API is not published to the host.

## Known open questions

- Exact development machine CPU model and operating-system version.
- Whether an offline model fallback is required for the live demo; Gemini itself requires internet access.
- Target live-response latency.

## Next step

Confirm all three GitHub Actions jobs pass for `Harden test harness and CI` (CI is unverified until then). Then implement group 2 (`Unify API errors and logging`), group 3 (`Extract Guard authorization step`), and group 4 (`Refresh project docs and edge-case tests`) before Iteration 5 document upload.

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
