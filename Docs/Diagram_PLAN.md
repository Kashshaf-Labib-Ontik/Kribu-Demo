# KRIBU Full-Product Architecture Diagram Pack

## Summary

Create an engineering-focused architecture pack covering the complete KRIBU product, including all five departmental skill packs, enterprise governance, data ingestion, company memory, LangGraph execution, approvals, connectors, observability, security, and AWS production deployment.

Deliverables:

- Editable diagrams.net source
- Individual SVG diagrams
- Combined multi-page PDF
- Markdown legend explaining components, interfaces, trust boundaries, and data flows

## Diagram Pack

1. **System Context**
   - Users: employees, department heads, approvers, administrators, knowledge owners, auditors.
   - Client systems: ERP, CRM, email, drives, HRIS, meetings, calendars and external APIs.
   - KRIBU product surfaces: Workspace, Source Explorer, Approval Inbox, Skill Studio, Administration, Audit and Evaluation.
   - Skill packs: Project Intelligence, Complaints, Procurement, Sales and HR.

2. **Application and Service Architecture**
   - Next.js frontend and FastAPI control plane.
   - Identity/Tenant, Source, Ingestion, Retrieval, Knowledge, Skill Registry, Run, Policy, Approval, Artifact, Connector, Audit and Evaluation services.
   - LangGraph workers for durable business workflows.
   - Celery workers for parsing, indexing, synchronization and independent infrastructure jobs.
   - REST, SSE, queue/event and internal service boundaries.

3. **Data Ingestion and Company Memory**
   - OAuth connector, webhook, polling and manual-upload paths.
   - Quarantine, malware/file validation, duplicate detection, OCR/parsing, normalization, chunking and provenance.
   - ACL projection before indexing.
   - Full-text indexing, embeddings, facts, entities and typed relationships.
   - Original, normalized and generated artifact storage.
   - PostgreSQL/pgvector as the initial relationship store behind a pluggable `RelationshipStore`.

4. **LangGraph Intelligence Workflow**
   - Request classification and skill selection.
   - Authorization-aware retrieval.
   - Typed extraction, calculations, cross-period comparison and evidence validation.
   - Citation verification, confidence and limitation handling.
   - Artifact generation and approval interrupts.
   - Safe resume, retries, idempotency, failure compensation and dead-letter handling.
   - Approved connector execution and outcome recording.

5. **Security, Governance and Multi-Tenancy**
   - OIDC authentication, tenant context and role resolution.
   - Shared services with PostgreSQL row-level security.
   - Document ACLs applied before retrieval reaches a model.
   - Policy engine, tool allowlists, prompt-injection controls and controlled model egress.
   - KMS encryption, Secrets Manager, signed object access and OAuth scope boundaries.
   - Append-only audit events and exportable evidence.
   - Future dedicated-tenant deployment escape hatch.

6. **Skills, Connectors and Evaluation Lifecycle**
   - Draft, test, review, approve, version, publish, deprecate and rollback skill stages.
   - Typed input/output schemas, permissions, owner, model policy and side-effect classification.
   - Connector discovery, content fetching, ACL mapping and approved action execution.
   - Golden datasets, offline evaluations, regression gates and production feedback.
   - Shared platform primitives reused by all five departmental use cases.

7. **AWS Production Deployment**
   - Route 53, CloudFront, WAF and Application Load Balancer.
   - ECS Fargate services and workers across multiple availability zones.
   - RDS PostgreSQL Multi-AZ with pgvector and RLS.
   - S3 with versioning and KMS for sources, artifacts and audit exports.
   - SQS with retry queues and DLQs; ElastiCache for cache, locks and event coordination.
   - OpenTelemetry collector feeding Langfuse and CloudWatch.
   - GitHub Actions, Terraform, ECR, migration and evaluation deployment gates.
   - Point-in-time recovery, cross-region backup copies and restore paths.

## Interfaces and Core Types

Show the following contracts explicitly:

- APIs: uploads, sources, runs, SSE events, approvals, artifacts, skills, connectors, audit and administration.
- Types: `TenantContext`, `DocumentVersion`, `ACLDescriptor`, `EvidenceRef`, `Finding`, `SkillDefinition`, `RunState`, `ApprovalRequest`, `Artifact` and `ConnectorAction`.
- Adapters: `Connector`, `ModelProvider`, `EmbeddingProvider`, `ObjectStore`, `RelationshipStore` and `AuditSink`.
- Events: ingestion requested/completed/failed, run state changed, approval requested/decided, action executed and evaluation completed.

## Validation

- Trace every demo story from source system to evidence-backed output.
- Confirm unauthorized content cannot reach retrieval results or models.
- Confirm every external side effect crosses an approval boundary.
- Confirm citations retain document-version and page/cell provenance.
- Confirm restart, retry, rejection and duplicate-event paths are visible.
- Verify diagram readability, connector direction, legend consistency and PDF/SVG exports.
- Label current technology, future-pluggable components and trust boundaries distinctly.

## Assumptions

- LangGraph is the production orchestration foundation; Pydantic provides typed contracts.
- LangGraph runs in self-hosted KRIBU workers with PostgreSQL checkpoints.
- PostgreSQL/pgvector is authoritative initially; graph storage remains replaceable.
- Shared multi-tenancy uses RLS, with a future dedicated-client option.
- AWS uses one active Multi-AZ region with cross-region backups and a 99.9% availability target.
- Client-specific datasources remain connector placeholders until datasource discovery.
