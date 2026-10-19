# KRIBU Project Memory

This is the current implementation handoff. Update it in every material implementation commit; keep it factual and short. Git history remains the detailed record.

## Current status

- **Lifecycle:** Planning / pre-scaffold.
- **Active area:** Repository initialization and implementation plan.
- **Application code:** Not started.
- **Selected stories:** NGO Project, HR Employee History, Client Complaint Patterns.
- **Data:** Synthetic demo packs must be created; no client data sources are available.
- **Cost constraint:** Demo uses only locally runnable free/open-source components and requires no card.

## Completed

- Existing SRS, demo stories, architecture diagrams, and LangGraph design were reviewed.
- Git repository was initialized on branch `main`.
- GitHub remote was configured as `https://github.com/Kashshaf-Labib-Ontik/Kribu-Demo.git`.
- Root README and the six living collaboration documents were prepared.
- The architecture decision was aligned to LangGraph rather than PydanticAI for durable product growth.

## Current decisions

- Modular monorepo: Next.js Studio, FastAPI control plane, worker, PostgreSQL/pgvector, Keycloak, and OPA.
- Three major product components: Guard, Brain, and Engine; supporting components remain explicit modules.
- LangGraph OSS with PostgreSQL checkpoints owns reasoning workflow state.
- Pydantic owns typed contracts; deterministic code owns policy, math, validation, and side effects.
- Authorization uses RBAC + ABAC + document ACLs + RLS. Vector search and LLM reasoning do not grant access.
- Brain uses provenance-aware Docling/openpyxl extraction and authorized hybrid PostgreSQL retrieval.
- Local inference is accessed through a provider interface, initially Ollama. The default instruct/embedding models are selected after a hardware benchmark.
- Local filesystem is the demo object store behind an adapter; hosted object storage is deferred.
- All proposed external actions remain drafts behind human approval during the demo.
- Testing stays focused on security, retrieval, citations, graph behavior, API integration, goldens, and four browser journeys.

## Superseded source decisions

- Earlier documentation naming PydanticAI as the orchestrator is superseded by LangGraph plus Pydantic contracts.
- Earlier documentation naming a paid OpenAI model is superseded for the demo by local inference.
- Earlier scope covering all five stories is narrowed to NGO, HR, and Client Servicing.

## Current file/area being worked on

- Planning documents at repository root.
- No source file is under implementation yet.

## Verification performed

- Confirmed the selected stories against `Docs/KRIBU_Five_Demo_Stories.md`.
- Confirmed the component/dataflow and LangGraph direction against `Docs/Diagram_PLAN.md` and the architecture pack.
- Confirmed the repository had no previous Git metadata before initialization.

## Known open questions

- Development machine CPU, RAM, and GPU/VRAM.
- Whether the live demo must work fully offline after initial setup.
- Target live-response latency.
- Demo users and exact approval roles.

## Next step

Owner reviews `PRD.md`, `Architecture.md`, `rules.md`, `phases.md`, and `design.md`. After approval, start Iteration 1: scaffold the local monorepo and core Docker Compose profile. Do not start the scaffold before that review.

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
