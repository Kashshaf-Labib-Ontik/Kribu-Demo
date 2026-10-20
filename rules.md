# KRIBU Engineering Rules

These rules apply to implementation, review, and generated code. Security and data-boundary rules override delivery speed.

## 1. Required choices

- Use the stack and boundaries in `Architecture.md`; record a decision before replacing a major component.
- Use Python type hints, Pydantic boundary models, and TypeScript strict mode.
- Use `uv` for Python and `pnpm` for JavaScript dependency management.
- Pin direct dependencies and container image versions; do not use floating `latest` tags.
- Put configuration in validated settings and environment variables; commit only `.env.example`.
- Keep all demo services local and open-source; enabling hosted telemetry or model calls must be explicit opt-in.
- Keep business logic out of HTTP routes, React components, and LangGraph node plumbing.
- Generate API clients from OpenAPI rather than maintaining duplicate request types by hand.

## 2. Component boundaries

- Studio calls the API only. It never connects directly to PostgreSQL, OPA, Keycloak administration, Gemini, Ollama, or storage.
- Route handlers authenticate, validate, delegate, and map errors; application services own use cases.
- LangGraph nodes call typed tools/services. They never execute arbitrary SQL, shell commands, or unrestricted filesystem operations.
- Brain accepts an `AuthorizationScope`; it cannot perform an unscoped search.
- Guard is the only source of authorization decisions. UI visibility is not authorization.
- Skills contain domain schemas, prompts, and reports; shared ingestion/retrieval/policy code stays outside skill folders.
- Celery handles ingestion and infrastructure jobs. LangGraph owns user-facing reasoning workflow state.
- Source documents, normalized content, derived facts, embeddings, run state, and audit events remain distinct data types.

## 3. Authorization and privacy

- Deny by default. Missing tenant, user, action, resource attributes, ACL mapping, or policy response means deny.
- Validate JWT signature, issuer, audience, expiry, and tenant; never trust client-supplied roles or tenant IDs.
- Enforce tenant isolation in both application queries and PostgreSQL RLS.
- Apply ACL filters inside the retrieval query before ranking, reranking, prompting, preview, citation, or artifact access.
- Never use vector similarity, prompt instructions, model reasoning, or a person's name as proof of permission.
- An LLM safety classifier may deny or escalate only. It can never grant access or override OPA.
- Avoid revealing whether an inaccessible record exists. Return a generic denial with a correlation ID.
- Redact secrets and sensitive content from logs, traces, fixtures, screenshots, and exception messages.
- Use synthetic data only until client data handling and retention agreements exist.

## 4. AI boundaries

- Treat retrieved text as untrusted data, not instructions. Delimit it and prohibit tool/policy changes from source content.
- Models may classify intent, extract into a schema, compare evidence, and draft language.
- Deterministic code must perform authorization, money/date arithmetic, aggregation, citation existence checks, idempotency, and action execution.
- Every material claim must reference one or more `EvidenceRef` values. Do not invent citations.
- Clearly label inference, calculation, missing evidence, conflicting evidence, and direct quotation.
- Use bounded retries and bounded graph loops. On exhaustion, return a partial qualified result.
- Keep prompts and skills versioned. Record model, parameters, prompt/skill version, and retrieved evidence per run.
- Use Gemini free-tier inference only for synthetic demo data. Never send real client, salary, HR, complaint, or confidential organizational data to it.
- This boundary also applies to `gemini-embedding-2`; embedding calls are external model processing, not local database operations.
- Keep the Gemini API key server-side and outside Git; never expose it in browser variables, logs, traces, prompts, screenshots, or errors.
- Put Gemini behind `ModelProvider`; enforce timeouts, bounded exponential backoff for 429/5xx responses, token limits, and provider-specific error mapping.
- Never fine-tune on client data during the demo and never silently fall back from an approved private provider to a free external provider.
- Do not add Mem0, a graph database, an agent swarm, autonomous browser/code execution, or an unapproved model provider without an accepted use case and evaluation.

## 5. Retrieval and provenance

- Preserve document ID, immutable version ID, content hash, and exact locator throughout parsing and chunking.
- Prefer deterministic Office/spreadsheet parsers where page/cell accuracy matters; use OCR only when needed.
- Store the embedding model ID and chunking version so indexes can be rebuilt.
- Publish a new immutable index generation and switch its active head only after every chunk and vector validates; never mix dimensions, models, or chunker versions.
- Keep authorization predicates in the same query or transaction that selects candidates.
- Combine lexical and semantic retrieval; measure on golden queries before tuning weights.
- Do not degrade to lexical-only search when the approved query-embedding provider fails; fail closed with a safe `503` so result semantics stay explicit.
- Evaluate current ACLs before embedding/ranking and never encode permission into vectors; authorization revocation must work without reindexing.
- Never store raw queries, bearer tokens, or document text in retrieval audit rows.
- Do not cache results across users unless the authorization scope is part of the cache key.
- Recheck access when opening evidence or downloading an artifact, even if a prior run was authorized.

## 6. Errors and reliability

- Define domain errors and map them once to RFC 9457-style problem details.
- Include a correlation ID and safe machine-readable error code in every failed request.
- Log the detailed exception server-side, but never expose stack traces, prompts, tokens, filesystem paths, or SQL to users.
- Mark errors as retryable or terminal. Retry only transient operations with exponential backoff and jitter.
- Require idempotency keys for uploads, jobs, approval decisions, and future connector actions.
- Use database transactions around state changes and an outbox pattern when a durable event/job must follow a commit.
- Quarantine malformed or unsafe files; do not silently index partial content as complete.
- Use explicit timeouts and cancellation for model, parser, policy, and database calls.

## 7. Code quality

- Prefer small modules with descriptive names over generic `utils` files.
- Avoid premature microservices, factories, inheritance, and abstraction. Introduce an interface at a genuine provider or trust boundary.
- Do not use `Any`/untyped dictionaries for domain state where a typed model is practical.
- Use UTC in storage and ISO 8601 at APIs; localize only for presentation.
- Use `Decimal` and explicit currencies for money; never binary floating point.
- Add database changes only through reviewed Alembic migrations.
- Format/lint Python with Ruff and type-check important service and graph boundaries with mypy.
- Use ESLint/Prettier and strict TypeScript for the web application.

## 8. Minimal testing policy

Testing is risk-based, not coverage-percentage-driven.

Required tests:

- OPA policy decision tables and cross-tenant/ACL denial cases.
- Retrieval authorization and citation locator integrity.
- LangGraph routing, retry limit, checkpoint resume, and approval interrupt.
- One golden evaluation dataset per selected story.
- API integration tests for uploads, runs, evidence, and approvals.
- One Playwright happy path per story plus one unauthorized salary attempt.

Avoid snapshots of large prompts, exhaustive presentation-component tests, duplicate schema tests, and tests that merely restate framework behavior.

## 9. Dependencies and licenses

- Prefer maintained dependencies with an OSI-approved license compatible with the project.
- Record major dependency purpose and license; reject unclear, source-available-only, or unexpectedly paid runtime requirements for the demo.
- Do not add a library for a small function available in the standard library.
- Run dependency and container vulnerability checks before the final demo, but do not block early iteration on low-risk development-only findings.

## 10. Git and iteration

- Keep iterations vertically demonstrable and small enough to review in one sitting.
- Never commit or push an iteration until the owner has reviewed the working-tree changes and explicitly approved the commit.
- After approval, commit the accepted iteration with a concise imperative message describing the change.
- Do not mention Codex, AI agents, co-authorship, or collaboration tooling in commit messages.
- Do not commit secrets, real client data, local model weights, generated caches, database volumes, or large transient artifacts.
- Update `memory.md` in every material implementation commit with current state, decisions, active file/area, verification, and next step.
- Suggested message style: `Add document ingestion pipeline`, `Enforce document ACL retrieval`, `Implement NGO analysis skill`.
- Do not rewrite shared history or force-push without explicit agreement.

## 11. Definition of an iteration complete

An iteration is complete only when its acceptance slice works, focused checks pass, documentation and `memory.md` match reality, and the repository has no accidental generated/secrets files.
