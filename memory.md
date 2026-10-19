# KRIBU Project Memory

This is the current implementation handoff. Update it in every material implementation commit; keep it factual and short. Git history remains the detailed record.

## Current status

- **Lifecycle:** Iteration 1 implementation, awaiting owner review.
- **Active area:** Local monorepo scaffold and health flow.
- **Application code:** Next.js Studio shell and FastAPI foundation implemented in the working tree; not committed.
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
- Iteration 1 working tree now contains pinned web/API dependencies, Docker Compose, pgvector initialization, API health probes, a responsive Studio landing shell, and focused checks.

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

- `apps/web`: Next.js Studio foundation and API status display.
- `services/api`: FastAPI application, configuration, correlation IDs, and health endpoints.
- `compose.yaml` and `infra/compose/postgres`: local PostgreSQL/pgvector foundation.

## Verification performed

- Confirmed the selected stories against `Docs/KRIBU_Five_Demo_Stories.md`.
- Confirmed the component/dataflow and LangGraph direction against `Docs/Diagram_PLAN.md` and the architecture pack.
- Confirmed the repository had no previous Git metadata before initialization.
- Web production build, TypeScript, ESLint, API Ruff, and API mypy checks pass.
- Three focused API health/correlation/readiness tests pass; the current FastAPI test client emits one upstream deprecation warning.
- Host-level smoke test passes: liveness `200`, web `200` with API available, and readiness safely returns `503` while PostgreSQL is absent.
- JavaScript and Python frozen lockfile checks pass; Docker Compose configuration validates.
- Docker Desktop is now running; PostgreSQL and API are healthy. Web was restarting because its runtime image invoked pnpm as a non-writable user; the standalone-server Dockerfile fix is part of this uncommitted update.

## Known open questions

- Exact development machine CPU model and operating-system version.
- Whether the live demo must work fully offline after initial setup.
- Target live-response latency.
- Demo users and exact approval roles.

## Next step

Complete the web container fix and present the Gemini decision/documentation update for owner review. Commit and push only after explicit approval; then begin the Gemini provider spike.

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
