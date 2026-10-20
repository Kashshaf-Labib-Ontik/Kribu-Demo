# TODOS

## Brain

### Retrieval SQL twin of the Rego read rules, with a shared parity table

**What:** Implement Iteration 7 retrieval authorization as SQL predicates that mirror `policies/rego/authz.rego` read rules, guarded by one case table run by both `opa test` and pytest.

**Why:** Search must filter by tenant and ACL inside the candidate query (`rules.md:59`); calling OPA per candidate does not scale, and a SQL copy that drifts from Rego silently leaks or hides documents.

**Context:** Approved in the 2026-10-19 engineering review (D5/D16). `authorize()` stays the per-object path for opening evidence and downloads. The retrieval audit record (query id, scope hash, candidate count, returned ids, policy version) was approved at D21. Start from `app/policy/resources.py` and the `may_read` and `read_grant` rules in `authz.rego`.

**Effort:** L
**Priority:** P1
**Depends on:** Iteration 6 normalized chunks; exit gate of Iteration 7.

### Image uploads with OCR

**What:** Accept PNG/JPEG uploads (signature rules in `app/documents/validation.py`) once an OCR parser path exists.

**Why:** PRD BRN-01 lists common image files; scanned evidence is unreadable without OCR, so images were deferred at D3.

**Context:** The allowlist is one constant and the sniff rules are table-tested in `tests/test_documents_validation.py`. Pre-fetch OCR model weights for offline demos (`phases.md` risk table).

**Effort:** M
**Priority:** P3
**Depends on:** Iteration 6 parser framework and an OCR engine decision (RapidOCR or Tesseract).

### Malware scanning of uploaded originals

**What:** Scan stored originals with an open-source scanner (for example a ClamAV daemon in Compose) before they become visible to parsers; infected files become quarantined.

**Why:** `Docs/Diagram_PLAN.md:31` calls for malware validation; Iteration 5 only proves type and size. Required before any non-synthetic file is accepted.

**Context:** Hook after `LocalFileObjectStore.put` and before a version is handed to parsing. Signature databases are large (about 300 MB) and must be pre-fetched for offline demos. Synthetic-only data policy (`rules.md:37`) keeps current risk low.

**Effort:** M
**Priority:** P2
**Depends on:** Iteration 6 quarantine status; client-data handling agreements.

### Blob garbage collection and reference counting

**What:** Sweep unreferenced blobs under `tenants/{tenant}/sha256/` and add a reference check before any delete path.

**Why:** A failed insert transaction after `put` leaves an orphan blob, and blobs are shared by identical uploads within a tenant, so deleting one document must not delete bytes another still uses.

**Context:** References live in `document_versions.storage_key`. A sweeper needs a grace period so it never races an in-flight upload. Start in `app/documents/storage.py`.

**Effort:** M
**Priority:** P2
**Depends on:** Must land before any document delete or retention feature (`Architecture.md` data model).

## Audit

### Audit indexes for the run timeline

**What:** Add indexes on `authorization_audit_events` (tenant, created_at; tenant, resource_id; correlation_id) sized to the Iteration 12 timeline queries.

**Why:** The table only indexes `tenant_id`; timeline and per-resource history queries will scan.

**Context:** Approved in the 2026-10-19 engineering review (D15). Design the indexes against the actual Iteration 12 queries rather than guessing now.

**Effort:** S
**Priority:** P3
**Depends on:** Iteration 12 approval and audit journey.

## Completed
