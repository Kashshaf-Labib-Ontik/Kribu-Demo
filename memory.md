# KRIBU Project Memory

This is the current implementation handoff. Update it in every material implementation commit; keep it factual and short. Git history remains the detailed record.

## Current status

- **Lifecycle:** Iteration 3 implemented and live-verified; working tree is uncommitted pending owner review.
- **Active area:** Keycloak identity, trusted request context, tenant schema, and PostgreSQL RLS.
- **Application code:** Iteration 2 is committed and pushed; the identity and tenant boundary now works locally and is awaiting review.
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
- Iteration 3 adds a pinned Keycloak realm, strict OIDC validation, tenant-scoped sessions, Alembic migrations, a restricted runtime database role, and forced PostgreSQL RLS.

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

## Superseded source decisions

- Earlier documentation naming PydanticAI as the orchestrator is superseded by LangGraph plus Pydantic contracts.
- Earlier documentation naming a paid OpenAI model or local Ollama as demo default is superseded by Gemini free-tier inference.
- Earlier scope covering all five stories is narrowed to NGO, HR, and Client Servicing.

## Current file/area being worked on

- `services/api/app/identity`: token validation, trusted identity contracts, and tenant session context.
- `services/api/migrations`: tenant/user schema, synthetic profiles, and RLS policies.
- `infra/keycloak` and `compose.yaml`: local identity service and repeatable realm import.

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

## Known open questions

- Exact development machine CPU model and operating-system version.
- Whether an offline model fallback is required for the live demo; Gemini itself requires internet access.
- Target live-response latency.

## Next step

Present Iteration 3 for owner review and commit only after explicit approval. Iteration 4 then introduces OPA RBAC/ABAC policy decisions and audit records.

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
