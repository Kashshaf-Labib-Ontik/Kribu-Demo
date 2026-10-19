# KRIBU Brain — Unified SRS and Delivery Blueprint

## 1. Product Definition

Synthesized from the project reference files: `Demo_Stories.txt`, `Kribu Brain Platform.html`, and `KribuBifold.pdf`.

KRIBU Brain is a governed company-intelligence platform that:

- Connects organizational data and documents.
- Answers cross-source questions with page/cell-level evidence.
- Converts reusable workflows into versioned “skills.”
- Produces reports, drafts, tasks, and recommendations.
- Requires human approval before external or sensitive actions.
- Records every model call, retrieval, tool use, approval, and outcome.

Primary users are employees, department heads, approvers, organization administrators, knowledge owners, and auditors.

The first demo will prove project intelligence using synthetic documents—not all five departmental stories.

## 2. Unified Requirements

### Functional requirements

- **Identity and governance:** Multi-tenant organizations, OIDC login, roles, document-level permissions, retention policies, and configurable action approval rules.
- **Data ingestion:** Manual PDF, DOCX, XLSX, CSV, image, and email upload initially; versioning, duplicate detection, extraction status, metadata, and access-control mapping.
- **Company memory:** Store source documents, structured facts, entities, relationships, embeddings, and provenance separately.
- **Grounded intelligence:** Search by semantic meaning, keywords, project, reporting period, source type, and user permissions. Every material claim must cite its document page, section, table, or spreadsheet cell.
- **Agent workflow:** Understand the request, select approved skills, retrieve evidence, extract typed facts, compare periods, calculate variances, validate citations, and generate an answer or artifact.
- **Skills library:** Versioned skills with typed inputs/outputs, required permissions, model configuration, side-effect classification, owner, and test cases.
- **Artifacts:** Generate management briefings, comparison tables, timelines, clarification questions, email drafts, and follow-up tasks.
- **Human approval:** Sending communications, creating tasks in client systems, or changing business records must pause for review, editing, approval, or rejection.
- **Audit and observability:** Record user, model, prompt/skill version, documents accessed, retrieved evidence, tool calls, cost, latency, approval, and final outcome.
- **Administration:** Manage users, roles, sources, skills, model policies, usage limits, audit exports, and evaluation results.
- **Future use cases:** Complaint-pattern analysis, procurement comparison, sales outreach, and employee-history reconstruction will reuse the same platform primitives.

### Quality requirements

- Unsupported explanations must be labeled “not established by the available evidence.”
- Source content is untrusted: documents cannot instruct the agent to bypass policies or invoke tools.
- Tenant and document ACL filters must run before retrieval results reach the model.
- Runs must be retryable and idempotent; interrupted approval workflows must resume safely.
- Provider, embedding, storage, and connector interfaces must be replaceable.
- Encrypt data in transit and at rest; keep credentials in a secrets manager.
- Meet WCAG 2.2 AA for the user-facing demo.
- Do not claim regulatory compliance until independently assessed.

## 3. Architecture and Technology Stack

```text
Next.js UI
   │ REST + SSE
   ▼
FastAPI application
   ├── Governance, ACLs, and approvals
   ├── Agent and deterministic workflow
   ├── Retrieval and citation validator
   └── Skills and connector interfaces
          │
          ├── PostgreSQL + pgvector
          ├── S3 / MinIO object storage
          └── Worker queue
                 │
                 └── Model provider / external tools

OpenTelemetry → Langfuse → evaluations and monitoring
```

| Layer | Selected technology |
|---|---|
| Frontend | Next.js 16 App Router, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Agent layer | PydanticAI with explicit deterministic workflow nodes; one specialist agent, not an agent swarm |
| Initial model | OpenAI `gpt-6.1-sol`; provider selected through configuration |
| Document processing | Docling; `openpyxl`/Pandas for spreadsheets requiring cell-level provenance |
| Search | PostgreSQL full-text search + pgvector HNSW, metadata filters, reciprocal-rank fusion |
| Storage | PostgreSQL for application/fact data; MinIO locally and S3 in AWS for originals/artifacts |
| Background work | Celery and Redis for ingestion, extraction, and long-running analysis |
| Authentication | OIDC/JWT; local development identity provider, client Entra ID/Google Workspace later |
| Observability | OpenTelemetry and Langfuse for traces, prompts, costs, datasets, and regression evaluations |
| Deployment | Docker Compose locally; AWS ECS Fargate, RDS PostgreSQL, S3, ElastiCache, and Secrets Manager |
| Infrastructure | Terraform, GitHub Actions, pytest, Vitest, Playwright |

Why these choices:

- PydanticAI provides typed tools/results, reusable capabilities, provider-neutral models, evaluations, OpenTelemetry, and durable human-review options. [PydanticAI documentation](https://pydantic.dev/docs/ai/overview/)
- Docling supports PDF, Office, image, email, OCR, and structure-aware chunking. [Docling formats](https://docling-project.github.io/docling/usage/supported_formats/)
- pgvector supports hybrid full-text/vector retrieval and keeps tenant metadata, facts, and vectors in one transactional system. [pgvector documentation](https://github.com/pgvector/pgvector#hybrid-search)
- RDS PostgreSQL currently supports pgvector, preserving the local-to-cloud path. [AWS extension support](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html)
- Official OpenAI documentation currently positions `gpt-6.1-sol` as the intelligence/cost balance. [OpenAI model guide](https://developers.openai.com/api/docs/models)
- Langfuse supports trace-based datasets, offline experiments, and CI regression gates. [Langfuse evaluations](https://langfuse.com/docs/evaluation/overview)

### Memory decision

Do not use Mem0 in the first demo.

- Documents and business facts require stable provenance and ACL-aware retrieval.
- Conversation/run state belongs in PostgreSQL.
- Audit records require append-only application events.
- Mem0 may later store user preferences or recurring conversational context.
- Its graph memory is based on entity co-occurrence rather than typed business relationships, so it should not be KRIBU’s authoritative company knowledge graph. [Mem0 graph-memory documentation](https://docs.mem0.ai/platform/features/graph-memory)

### Core interfaces

- `POST /documents/uploads`
- `POST /runs` and `GET /runs/{id}/events` using SSE
- `POST /approvals/{id}/decision`
- `GET /artifacts/{id}` and `GET /audit-events`
- `SkillDefinition`: version, schemas, permissions, side-effect level, owner, tests.
- `EvidenceRef`: document version, page/cell, excerpt, retrieval score.
- `Finding`: statement, evidence references, confidence, limitations.
- `Connector`: discover changes, fetch content, map ACLs, and execute approved actions.
- Future MCP tools must use OAuth scopes and least privilege. [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

## 4. Demo and Delivery Sequence

1. **Synthetic evidence pack**
   - Create six half-yearly progress reports covering three years, expenditure statements, meeting minutes, field reports, contractor updates, and the project plan.
   - Plant two repeated milestone delays, continuing expenditure, documented blockers, missing information, and one misleading correlation.
   - Create a golden fact sheet and expected answers before writing prompts.

2. **Foundation**
   - Scaffold the web, API, worker, database, object storage, migrations, authentication, audit events, and Docker environment.
   - Implement uploads, Docling extraction, spreadsheet parsing, provenance, hybrid indexing, and document preview.

3. **Project-intelligence workflow**
   - Retrieve authorized sources, extract typed milestones/issues/expenditure, compare periods, distinguish evidence from inference, and validate every citation.
   - Display findings, project timeline, source drawer, confidence/limitations, and a downloadable management briefing.

4. **Governance demonstration**
   - Draft follow-up tasks and clarification emails.
   - Pause at an approval inbox; allow editing, approval, rejection, and resumption.
   - Do not connect or send to real client systems during the demo.

5. **Production expansion**
   - Add client-selected connectors only after datasource discovery.
   - Add complaint, procurement, sales, and HR skills using separate evaluation datasets.
   - Introduce LiteLLM/model failover, structured company relationships, and Mem0 personalization only when their measured need appears.

## 5. Learning and Acceptance Plan

Learn in this order, building a small exercise after each topic:

1. Python, Pydantic, FastAPI, async APIs, SQL/PostgreSQL, TypeScript, Docker, and Git.
2. LLM structured outputs, tool calling, embeddings, chunking, hybrid retrieval, reranking, citations, and prompt-injection risks.
3. PydanticAI agents/capabilities, explicit workflow state, streaming, retries, and approval gates.
4. Docling, spreadsheet provenance, pgvector, object storage, and ingestion workers.
5. OIDC, RBAC, tenant isolation, OAuth connectors, secrets, and MCP security.
6. OpenTelemetry, Langfuse, golden datasets, agent evaluations, AWS, Terraform, and CI/CD.

Acceptance requires:

- The seeded delayed activities, expenditure patterns, and documented blockers are identified correctly.
- Every finding opens the exact supporting page, table, or spreadsheet cell.
- Unsupported causal claims are rejected or clearly qualified.
- Cross-tenant and unauthorized-document retrieval tests always return zero leakage.
- Every side-effect attempt requires approval.
- Duplicate uploads, malformed files, model timeouts, worker restarts, and rejected approvals recover safely.
- Golden-dataset extraction, citation correctness, retrieval recall, briefing quality, and cost/latency regressions are evaluated before deployment.

### Assumptions

- English-first demo; architecture remains Unicode/Bangla-ready.
- Six half-yearly reports resolve the repository’s conflict between “three reports” and a “three-year pattern.”
- AWS is the reference cloud, while Docker and open interfaces preserve portability.
- Live client datasources, real email/task execution, Neo4j, Mem0, and all non-project demo stories are outside the first demo.
- Dependencies are pinned to tested stable versions at scaffold time; floating `latest` container tags are prohibited.
