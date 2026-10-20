from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.errors import ModelProviderUnavailableError
from app.brain.contracts import ChunkDraft, SourceReference
from app.brain.dependencies import get_embedding_provider
from app.brain.embeddings import INDEX_CONTRACT
from app.brain.tasks import _publish_generation
from app.core.database import create_session_factory

pytestmark = pytest.mark.integration

DEMO_TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
USERS: dict[str, dict[str, Any]] = {
    "mike": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "tenant_id": DEMO_TENANT,
        "roles": ["employee"],
        "department": "engineering",
    },
    "helen.hr": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "tenant_id": DEMO_TENANT,
        "roles": ["hr_manager"],
        "department": "human-resources",
    },
    "priya.manager": {
        "subject": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
        "tenant_id": DEMO_TENANT,
        "roles": ["manager", "approver"],
        "department": "programs",
    },
    "evan.external": {
        "subject": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "tenant_id": OTHER_TENANT,
        "roles": ["employee"],
        "department": "engineering",
    },
}


class FakeEmbeddings:
    async def embed_documents(self, *, title: str, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 767 for _ in texts]

    async def embed_query(self, query: str) -> list[float]:
        return [1.0] + [0.0] * 767

    async def close(self) -> None:
        return None


class UnavailableEmbeddings(FakeEmbeddings):
    async def embed_query(self, query: str) -> list[float]:
        raise ModelProviderUnavailableError(retryable=True)


def bearer(token_for: Callable[..., str], username: str) -> dict[str, str]:
    user = USERS[username]
    token = token_for(
        subject=user["subject"],
        username=username,
        tenant_id=user["tenant_id"],
        roles=user["roles"],
        department=user["department"],
    )
    return {"Authorization": f"Bearer {token}"}


def seed_indexed_document(
    owner_db: Any,
    *,
    tenant_id: str,
    title: str,
    classification: str,
    department: str,
    principal_type: str,
    principal_id: str,
    domain: str,
    text: str,
) -> tuple[str, str, str]:
    document_id, version_id, extraction_id, generation_id, chunk_id = [uuid4() for _ in range(5)]
    grant_id, job_id = uuid4(), uuid4()
    actor = (
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"
        if tenant_id == OTHER_TENANT
        else "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
    )
    tenant_uuid = UUID(tenant_id)
    owner_db.execute(
        "INSERT INTO resource_descriptors "
        "(id, tenant_id, resource_type, classification, department, owner_subject_id, title) "
        "VALUES ($1, $2, 'document', $3, $4, $5, $6)",
        document_id,
        tenant_uuid,
        classification,
        department,
        actor,
        title,
    )
    owner_db.execute(
        "INSERT INTO resource_acl_grants "
        "(id, tenant_id, resource_id, principal_type, principal_id, action) "
        "VALUES ($1, $2, $3, $4, $5, 'resource.read')",
        grant_id,
        tenant_uuid,
        document_id,
        principal_type,
        principal_id,
    )
    owner_db.execute(
        "INSERT INTO documents "
        "(id, tenant_id, domain, project, document_date, latest_version_number, "
        "created_by_subject_id) "
        "VALUES ($1, $2, $3, 'Community Clinic', DATE '2026-03-31', 1, $4)",
        document_id,
        tenant_uuid,
        domain,
        actor,
    )
    owner_db.execute(
        "INSERT INTO document_versions "
        "(id, tenant_id, document_id, version_number, sha256, size_bytes, media_type, "
        "original_filename, storage_key, status, created_by_subject_id) "
        "VALUES ($1, $2, $3, 1, decode(repeat('01', 32), 'hex'), 100, "
        "'text/markdown', 'synthetic.md', 'synthetic/key', 'stored', $4)",
        version_id,
        tenant_uuid,
        document_id,
        actor,
    )
    owner_db.execute(
        "INSERT INTO document_extractions "
        "(id, tenant_id, document_id, document_version_id, parser_name, parser_version, "
        "normalization_version, block_count) "
        "VALUES ($1, $2, $3, $4, 'markdown', 'stdlib', 'normalization-v1', 1)",
        extraction_id,
        tenant_uuid,
        document_id,
        version_id,
    )
    owner_db.execute(
        "INSERT INTO document_ingestion_jobs "
        "(id, tenant_id, document_id, document_version_id, actor_subject_id, state) "
        "VALUES ($1, $2, $3, $4, $5, 'ready')",
        job_id,
        tenant_uuid,
        document_id,
        version_id,
        actor,
    )
    owner_db.execute(
        "INSERT INTO document_index_generations "
        "(id, tenant_id, document_id, document_version_id, extraction_id, chunker_version, "
        "embedding_provider, embedding_model, embedding_dimension, index_contract, "
        "content_hash, chunk_count, state) "
        "VALUES ($1, $2, $3, $4, $5, 'structure-v1', 'gemini', "
        "'gemini-embedding-2', 768, "
        "'gemini:gemini-embedding-2:768:question-answering-v1:structure-v1', "
        "decode(repeat('02', 32), 'hex'), 1, 'ready')",
        generation_id,
        tenant_uuid,
        document_id,
        version_id,
        extraction_id,
    )
    owner_db.execute(
        "INSERT INTO document_search_chunks "
        "(id, tenant_id, generation_id, document_id, document_version_id, ordinal, text, "
        "source_references, content_hash, embedding) "
        "VALUES ($1, $2, $3, $4, $5, 1, $6, "
        "jsonb_build_array(jsonb_build_object('block_id', $7::text, "
        "'locator', jsonb_build_object('kind', 'markdown_line', 'line', 3), "
        "'start_character', null, 'end_character', null)), "
        "decode(repeat('03', 32), 'hex'), $8::vector)",
        chunk_id,
        tenant_uuid,
        generation_id,
        document_id,
        version_id,
        text,
        str(uuid4()),
        "[1," + ",".join("0" for _ in range(767)) + "]",
    )
    owner_db.execute(
        "INSERT INTO document_index_heads "
        "(tenant_id, document_version_id, active_generation_id) VALUES ($1, $2, $3)",
        tenant_uuid,
        version_id,
        generation_id,
    )
    return str(document_id), str(version_id), str(chunk_id)


@pytest.fixture
def retrieval_client(api_client: TestClient) -> TestClient:
    api_client.app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddings()
    return api_client


def search(client: TestClient, token_for: Callable[..., str], username: str, query: str) -> Any:
    return client.post(
        "/v1/retrieval/search",
        headers={**bearer(token_for, username), "X-Correlation-ID": f"retrieval-{uuid4()}"},
        json={"query": query, "limit": 8},
    )


def test_authorization_precedes_ranking_and_evidence_keeps_provenance(
    retrieval_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    salary_document, salary_version, _ = seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="Roger Albert salary history",
        classification="restricted_hr",
        department="human-resources",
        principal_type="role",
        principal_id="hr_manager",
        domain="hr",
        text="Roger Albert monthly compensation is BDT 145,000.",
    )
    ngo_document, _, ngo_chunk = seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="March NGO progress report",
        classification="internal",
        department="programs",
        principal_type="department",
        principal_id="programs",
        domain="ngo",
        text="Milestone M-17 is delayed because the permit remains pending.",
    )

    mike = search(retrieval_client, token_for, "mike", "What is Albert's compensation?")
    helen = search(retrieval_client, token_for, "helen.hr", "What is Albert's compensation?")
    priya = search(retrieval_client, token_for, "priya.manager", "Why is M-17 delayed?")

    assert mike.status_code == 200
    assert mike.json()["evidence"] == []
    assert helen.status_code == 200
    assert helen.json()["evidence"][0]["document_id"] == salary_document
    assert helen.json()["evidence"][0]["version_id"] == salary_version
    assert helen.json()["evidence"][0]["source_references"][0]["locator"]["line"] == 3
    assert priya.status_code == 200
    assert priya.json()["evidence"][0]["document_id"] == ngo_document
    assert priya.json()["evidence"][0]["chunk_id"] == ngo_chunk
    assert priya.json()["evidence"][0]["untrusted_source"] is True


def test_cross_tenant_chunks_never_enter_results(
    retrieval_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    other_document, _, _ = seed_indexed_document(
        owner_db,
        tenant_id=OTHER_TENANT,
        title="Other tenant runbook",
        classification="internal",
        department="engineering",
        principal_type="department",
        principal_id="engineering",
        domain="complaints",
        text="Unique cross tenant confidential phrase.",
    )

    mike = search(retrieval_client, token_for, "mike", "Unique cross tenant confidential phrase")
    evan = search(
        retrieval_client, token_for, "evan.external", "Unique cross tenant confidential phrase"
    )

    assert mike.status_code == 200 and mike.json()["evidence"] == []
    assert evan.status_code == 200
    assert evan.json()["evidence"][0]["document_id"] == other_document


def test_latest_version_without_index_never_falls_back(
    retrieval_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    document_id, _, _ = seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="Current programme report",
        classification="internal",
        department="programs",
        principal_type="department",
        principal_id="programs",
        domain="ngo",
        text="Old status said the permit was pending.",
    )
    owner_db.execute(
        "UPDATE documents SET latest_version_number = 2 WHERE id = $1",
        UUID(document_id),
    )

    response = search(retrieval_client, token_for, "priya.manager", "permit status")

    assert response.status_code == 200
    assert document_id not in {item["document_id"] for item in response.json()["evidence"]}


def test_narrowing_filters_apply_before_ranking(
    retrieval_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    document_id, _, _ = seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="Filtered programme report",
        classification="internal",
        department="programs",
        principal_type="department",
        principal_id="programs",
        domain="ngo",
        text="Milestone M-17 is delayed.",
    )

    response = retrieval_client.post(
        "/v1/retrieval/search",
        headers=bearer(token_for, "priya.manager"),
        json={
            "query": "Why is M-17 delayed?",
            "filters": {
                "domain": "ngo",
                "project": "community clinic",
                "document_date_from": "2026-01-01",
                "document_date_to": "2026-12-31",
            },
        },
    )

    assert response.status_code == 200
    assert document_id in {item["document_id"] for item in response.json()["evidence"]}


def test_duplicate_index_delivery_keeps_one_active_generation(owner_db: Any, app_dsn: str) -> None:
    document_id, version_id, chunk_id = seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="Idempotent index publication",
        classification="internal",
        department="programs",
        principal_type="department",
        principal_id="programs",
        domain="ngo",
        text="A complete active generation already exists.",
    )
    extraction_id = owner_db.fetch(
        "SELECT id FROM document_extractions WHERE document_version_id = $1",
        UUID(version_id),
    )[0]["id"]
    job_id = uuid4()
    actor_id = USERS["priya.manager"]["subject"]
    owner_db.execute(
        "INSERT INTO document_index_jobs "
        "(id, tenant_id, document_id, document_version_id, extraction_id, "
        "actor_subject_id, index_contract, state, attempt_count) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, 'processing', 1)",
        job_id,
        UUID(DEMO_TENANT),
        UUID(document_id),
        UUID(version_id),
        extraction_id,
        actor_id,
        INDEX_CONTRACT,
    )
    draft = ChunkDraft(
        ordinal=1,
        text="This duplicate must not be published.",
        source_references=[
            SourceReference(
                block_id=uuid4(),
                locator={"kind": "markdown_line", "line": 1},
            )
        ],
        content_hash=b"duplicate".ljust(32, b"0"),
    )
    engine = create_async_engine(app_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    session_factory = create_session_factory(engine)

    async def replay() -> None:
        try:
            for _ in range(2):
                await _publish_generation(
                    session_factory,
                    job_id=job_id,
                    tenant_id=DEMO_TENANT,
                    actor_id=actor_id,
                    chunks=[draft],
                    embeddings=[[1.0] + [0.0] * 767],
                )
        finally:
            await engine.dispose()

    asyncio.run(replay())
    counts = owner_db.fetch(
        "SELECT "
        "(SELECT count(*) FROM document_index_generations WHERE document_version_id = $1) "
        "AS generations, "
        "(SELECT count(*) FROM document_index_heads WHERE document_version_id = $1) AS heads, "
        "(SELECT count(*) FROM document_search_chunks WHERE document_version_id = $1) AS chunks, "
        "(SELECT state FROM document_index_jobs WHERE id = $2) AS job_state",
        UUID(version_id),
        job_id,
    )[0]
    assert dict(counts) == {"generations": 1, "heads": 1, "chunks": 1, "job_state": "ready"}
    assert (
        UUID(chunk_id)
        == owner_db.fetch(
            "SELECT id FROM document_search_chunks WHERE document_version_id = $1", UUID(version_id)
        )[0]["id"]
    )


def test_query_embedding_failure_is_a_safe_503(
    retrieval_client: TestClient, token_for: Callable[..., str], owner_db: Any
) -> None:
    seed_indexed_document(
        owner_db,
        tenant_id=DEMO_TENANT,
        title="Programme report",
        classification="internal",
        department="programs",
        principal_type="department",
        principal_id="programs",
        domain="ngo",
        text="Permit pending.",
    )
    retrieval_client.app.dependency_overrides[get_embedding_provider] = lambda: (
        UnavailableEmbeddings()
    )

    response = search(retrieval_client, token_for, "priya.manager", "permit")

    assert response.status_code == 503
    assert response.json()["code"] == "retrieval_unavailable"
    assert "permit" not in response.text


def test_client_cannot_supply_authorization_attributes(
    retrieval_client: TestClient, token_for: Callable[..., str]
) -> None:
    response = retrieval_client.post(
        "/v1/retrieval/search",
        headers=bearer(token_for, "mike"),
        json={"query": "salary", "tenant_id": DEMO_TENANT, "roles": ["hr_manager"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "request_invalid"
