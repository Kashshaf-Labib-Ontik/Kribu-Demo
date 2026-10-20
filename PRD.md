# KRIBU Demo Product Requirements

**Status:** Iterations 0-6 are implemented and verified locally; Iteration 7 authorized retrieval is next

**Scope:** Local, synthetic-data demo

**Selected stories:** NGO Project, HR, Client Servicing

## 1. Product statement

KRIBU is a governed organizational intelligence platform that answers cross-document questions with traceable evidence. It combines three primary capabilities:

- **KRIBU Guard:** identity, tenant isolation, RBAC, ABAC, document ACLs, policy enforcement, approvals, and audit.
- **KRIBU Brain:** ingestion, normalization, provenance, hybrid retrieval, facts, entities, and organization memory.
- **KRIBU Engine:** LangGraph workflows that plan, retrieve, analyze, validate, cite, generate artifacts, and pause for human approval.

The demo proves these capabilities with synthetic files because live client data sources and schemas are not yet available.

## 2. Goals

- Answer the three selected business questions from multiple files.
- Show the exact page, section, row, or cell supporting each material claim.
- Prevent unauthorized documents and chunks from reaching an LLM.
- Detect patterns, gaps, and inconsistencies rather than only summarizing documents.
- Produce reviewable reports and follow-up tasks without executing external actions.
- Keep domain skills, models, embeddings, storage, and future connectors replaceable.
- Run locally using free and open-source software without a credit card.

## 3. Non-goals for the demo

- Live HRIS, CRM, ERP, email, drive, or project-system connectors.
- Sending real email, changing client records, or creating tasks in external systems.
- Production-scale high availability, disaster recovery, billing, or regulatory certification.
- Training or fine-tuning a foundation model.
- Autonomous decisions about employment, compensation, customers, or project funding.
- Procurement and sales demo stories.
- A general-purpose autonomous agent swarm.

## 4. Users

| Persona | Needs | Demo permissions |
|---|---|---|
| Employee | Ask permitted organizational questions | Public/internal data assigned to the user |
| Department manager | Analyze departmental records | Department-scoped records and reports |
| HR manager | Review sensitive employee history | HR records explicitly granted by policy |
| Approver | Review proposed artifacts/actions | Approval queue and supporting evidence |
| Administrator | Configure users, roles, attributes, sources, and policies | Tenant administration, not automatic content access |
| Auditor | Inspect immutable decision and evidence history | Read-only audit access |

## 5. Demo stories

### 5.1 NGO Project: Where Did the Progress Go?

**Query:** Review three years of half-yearly progress reports and expenditure statements. Identify where delivery is falling behind and why.

**Synthetic evidence:** project plan, six progress reports, expenditure sheets, meeting minutes, field reports, and contractor updates.

**Expected result:** a period comparison identifying repeated missed targets, expenditure trends, documented blockers, unresolved questions, evidence links, and a management briefing draft.

### 5.2 HR: The Complete Employee History in One Question

**Query:** Prepare an employee's complete service history, including tenure, salary revisions, and applicable benefits.

**Synthetic evidence:** appointment letter, salary revision letters, benefit policies, employee profile, and one deliberately missing or inconsistent record.

**Expected result:** a dated timeline, calculated salary changes, applicable benefits, missing/inconsistent documents, evidence links, and an HR review checklist.

### 5.3 Client Servicing: Seeing the Pattern Behind Every Complaint

**Query:** Analyze complaints and previous case records. Identify recurring issues and service gaps.

**Synthetic evidence:** complaint records from several channels, interaction histories, resolutions, categories, dates, and teams.

**Expected result:** evidence-backed issue clusters, recurrence counts, unresolved patterns, affected journey stages, improvement recommendations, and follow-up task drafts.

## 6. Functional requirements

### Guard and governance

- **GOV-01:** Authenticate users with OIDC and derive a trusted tenant context.
- **GOV-02:** Evaluate RBAC and ABAC using subject, resource, action, tenant, and environment attributes.
- **GOV-03:** Enforce tenant and document ACL filters before lexical or vector retrieval.
- **GOV-04:** Deny by default when attributes, policies, or ownership are missing or ambiguous.
- **GOV-05:** Apply the same authorization to document preview, artifacts, citations, and downloads.
- **GOV-06:** Treat LLM security classification as advisory only; it may deny or escalate, never grant access.
- **GOV-07:** Require human approval before any side effect and record approve, edit, reject, expire, and resume events.
- **GOV-08:** Record policy version, policy input, decision, user, resource, and request correlation ID.

### Brain and ingestion

- **BRN-01:** Upload PDF, DOCX, XLSX, CSV, TXT, and Markdown. Image/OCR ingestion is deferred.
- **BRN-02:** Validate file type and size, hash content, detect duplicates, and quarantine failed files.
- **BRN-03:** Preserve immutable originals and create versioned normalized representations.
- **BRN-04:** Extract normalized blocks with exact PDF page, DOCX paragraph/table/row/column, XLSX sheet/A1, CSV row/column, and text/Markdown line/heading locators using deterministic parsers.
- **BRN-05:** Chunk without losing document version or page/cell provenance.
- **BRN-06:** Attach tenant, domain, sensitivity, owner, department, project, date, and ACL metadata before indexing.
- **BRN-07:** Provide authorized hybrid search using PostgreSQL full-text search and pgvector, fused and optionally reranked.
- **BRN-08:** Store facts, entities, relationships, embeddings, and conversational/run state separately from source documents.
- **BRN-09:** Re-index safely when a parser, embedding model, or ACL changes. For the demo, a durable Postgres outbox safely republishes queued parsing work after Redis/worker interruption.

### Engine and skills

- **ENG-01:** Represent each run as a durable LangGraph state machine with PostgreSQL checkpoints.
- **ENG-02:** Classify the request and select only an enabled, authorized, versioned skill.
- **ENG-03:** Build a retrieval plan with required source types, filters, and evidence coverage.
- **ENG-04:** Extract typed facts and perform arithmetic, dates, counts, and comparisons in code rather than mental model calculation.
- **ENG-05:** Separate direct evidence, deterministic calculation, model inference, and unresolved information.
- **ENG-06:** Validate that every material claim has an accessible evidence reference.
- **ENG-07:** Return "not established by the available evidence" when support is insufficient.
- **ENG-08:** Stream understandable progress events and recover safely from retry, restart, or timeout.
- **ENG-09:** Generate versioned artifacts such as timelines, briefings, insight reports, and task drafts.
- **ENG-10:** Keep each story as a skill over shared retrieval, analysis, citation, artifact, and approval subgraphs.

### Studio and administration

- **UX-01:** Provide sign-in, query workspace, run progress, result, evidence drawer, source preview, artifact, and approval views.
- **UX-02:** Make evidence reachable from every finding in no more than one interaction.
- **UX-03:** Display confidence, limitations, missing evidence, and policy denial messages plainly.
- **UX-04:** Let administrators manage demo users, roles, attributes, document metadata, and skill enablement.
- **UX-05:** Provide a searchable read-only audit timeline for each run.

## 7. Quality requirements

- **Security:** zero cross-tenant or unauthorized-document leakage in automated security tests.
- **Grounding:** every material factual claim is supported by an accessible citation.
- **Reliability:** duplicate jobs are idempotent; interrupted workflows resume from a checkpoint.
- **Ingestion safety:** a version becomes previewable only after all normalized blocks and provenance are committed; failed parsing is quarantined with a safe error code.
- **Performance target:** first progress event within 2 seconds; simple retrieval response within 15 seconds and multi-document analysis within 90 seconds on the reference machine. External-model latency and quota delays are reported, not hidden.
- **Accessibility:** keyboard access, visible focus, semantic markup, and WCAG 2.2 AA color contrast.
- **Privacy:** only synthetic demo content may be sent to Gemini; hosted telemetry remains disabled by default.
- **Portability:** provider interfaces isolate model, embedding, object storage, identity, policy, and connector implementations.
- **Auditability:** each run records prompt/skill version, model, retrieved evidence, policy decisions, tool calls, approvals, timings, and output.

## 8. Demo acceptance criteria

The demo is accepted when:

1. All three golden questions produce the expected core findings from synthetic evidence.
2. Citations open the correct document version and exact page, section, row, or cell.
3. A junior/non-HR user cannot retrieve, infer, preview, or cite restricted salary data, including through paraphrases.
4. Unsupported causes are qualified instead of presented as facts.
5. Re-uploading an identical document does not create conflicting active versions.
6. A stopped analysis can resume without repeating approved side effects.
7. Generated tasks remain drafts until an authorized person approves them.
8. A fresh developer can start the complete local stack from documented commands and synthetic seed data.

## 9. Constraints and assumptions

- English-first; data structures remain Unicode and Bangla-ready.
- Two synthetic tenants are seeded to prove isolation; future client deployments may onboard additional tenants through mapped identity and ACL attributes.
- Reference development hardware has 16 GB total system RAM and integrated Intel UHD graphics using shared memory. The demo therefore uses Gemini free-tier inference instead of requiring local LLM inference.
- All provider calls remain behind a replaceable interface so a future private or self-hosted provider can be introduced without changing skills or graphs.
- Gemini free-tier calls are restricted to synthetic demo data; real client information is prohibited because Google may use unpaid-service content for product improvement and human review.
- Synthetic data must be designed together with expected answers before prompt tuning.
- Client schemas and connectors are placeholders until discovery after demo approval.

## 10. Remaining delivery decisions

- Exact development-machine CPU model and operating-system version.
- Whether the demo must run fully offline after initial dependency/model download.
- Which user will demonstrate each role and approval path.
- Maximum acceptable Gemini response time during the live presentation.
