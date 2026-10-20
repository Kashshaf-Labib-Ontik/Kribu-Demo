"""Document upload lifecycle against real PostgreSQL (RLS, grants) and OPA guard-v2."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from tests.documents_fixtures import DOCX_PART, ooxml_bytes, pdf_bytes

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
HR_METADATA: dict[str, Any] = {
    "title": "Synthetic salary revision letter",
    "classification": "restricted_hr",
    "department": "human-resources",
    "domain": "hr",
    "project": "Roger Albert history",
    "document_date": "2026-01-31",
    "grants": [{"principal_type": "role", "principal_id": "hr_manager"}],
}
ENGINEERING_METADATA: dict[str, Any] = {
    "title": "Synthetic engineering runbook",
    "classification": "internal",
    "department": "engineering",
    "grants": [{"principal_type": "department", "principal_id": "engineering"}],
}


class Api:
    def __init__(self, client: TestClient, token_for: Callable[..., str]) -> None:
        self.client = client
        self.token_for = token_for

    def headers(self, username: str, *, key: str | None = None, **overrides: Any) -> dict[str, str]:
        user = {**USERS.get(username, {}), **overrides}
        token = self.token_for(
            subject=user["subject"],
            username=username,
            tenant_id=user["tenant_id"],
            roles=user["roles"],
            department=user["department"],
        )
        headers = {"Authorization": f"Bearer {token}", "X-Correlation-ID": f"doc-{uuid4()}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    def upload(
        self,
        username: str,
        metadata: dict[str, Any],
        content: bytes,
        *,
        filename: str = "letter.pdf",
        key: str | None = "auto",
        **user_overrides: Any,
    ) -> Response:
        return self.client.post(
            "/v1/documents/uploads",
            headers=self.headers(
                username, key=f"key-{uuid4()}" if key == "auto" else key, **user_overrides
            ),
            data={"metadata": json.dumps(metadata)},
            files={"file": (filename, content, "application/octet-stream")},
        )

    def upload_version(
        self, username: str, document_id: str, content: bytes, *, key: str | None = "auto"
    ) -> Response:
        return self.client.post(
            f"/v1/documents/{document_id}/versions",
            headers=self.headers(username, key=f"key-{uuid4()}" if key == "auto" else key),
            files={"file": ("letter.pdf", content, "application/octet-stream")},
        )

    def get(self, username: str, document_id: str) -> Response:
        return self.client.get(f"/v1/documents/{document_id}", headers=self.headers(username))


@pytest.fixture
def api(api_client: TestClient, token_for: Callable[..., str]) -> Api:
    return Api(api_client, token_for)


def unique_pdf(label: str = "doc") -> bytes:
    return pdf_bytes(f"SYNTHETIC ONLY: {label} {uuid4()}")


@pytest.fixture
def temporary_profile(owner_db: Any) -> Iterator[Callable[[str, str], str]]:
    created: list[str] = []

    def create(username: str, department: str) -> str:
        subject = str(uuid4())
        owner_db.execute(
            "INSERT INTO user_profiles "
            "(id, tenant_id, external_subject, username, display_name, department) "
            "VALUES ($1::uuid, $2::uuid, $1::text, $3, $3, $4)",
            subject,
            DEMO_TENANT,
            username,
            department,
        )
        created.append(subject)
        return subject

    yield create
    for subject in created:
        owner_db.execute("DELETE FROM user_profiles WHERE id = $1::uuid", subject)


# --- create and read ---------------------------------------------------------------------


def test_hr_upload_creates_document_and_only_permitted_readers_see_it(
    api: Api, owner_db: Any, document_store: Path
) -> None:
    content = unique_pdf("hr")

    created = api.upload("helen.hr", HR_METADATA, content)

    assert created.status_code == 201, created.text
    body = created.json()
    document_id = body["document_id"]
    assert body["duplicate_of"] is None
    assert body["version"]["version_number"] == 1
    assert body["version"]["status"] == "stored"
    assert body["version"]["media_type"] == "application/pdf"
    assert body["version"]["size_bytes"] == len(content)
    assert "storage_key" not in created.text and str(document_store) not in created.text

    helen = api.get("helen.hr", document_id)
    assert helen.status_code == 200
    assert helen.json()["title"] == HR_METADATA["title"]
    assert helen.json()["domain"] == "hr"
    assert helen.json()["document_date"] == "2026-01-31"
    assert [v["version_number"] for v in helen.json()["versions"]] == [1]
    assert api.get("mike", document_id).status_code == 404
    assert api.get("evan.external", document_id).status_code == 404

    key = owner_db.fetch(
        "SELECT storage_key FROM document_versions WHERE document_id = $1::uuid", document_id
    )[0]["storage_key"]
    assert key.startswith(f"tenants/{DEMO_TENANT}/sha256/")
    assert (document_store / key).read_bytes() == content


def test_create_decision_is_audited_with_the_upload_action(api: Api, owner_db: Any) -> None:
    headers = api.headers("helen.hr", key=f"key-{uuid4()}")

    response = api.client.post(
        "/v1/documents/uploads",
        headers=headers,
        data={"metadata": json.dumps(HR_METADATA)},
        files={"file": ("a.pdf", unique_pdf(), "application/pdf")},
    )

    rows = owner_db.fetch(
        "SELECT action, allowed, resource_id::text AS resource_id, policy_version "
        "FROM authorization_audit_events WHERE correlation_id = $1",
        headers["X-Correlation-ID"],
    )
    assert [dict(row) for row in rows] == [
        {
            "action": "document.create",
            "allowed": True,
            "resource_id": response.json()["document_id"],
            "policy_version": "guard-v2",
        }
    ]


def test_department_self_service_and_boundaries(
    api: Api, owner_db: Any, temporary_profile: Callable[[str, str], str]
) -> None:
    assert api.upload("mike", ENGINEERING_METADATA, unique_pdf()).status_code == 201

    programs = {
        **ENGINEERING_METADATA,
        "department": "programs",
        "grants": [{"principal_type": "department", "principal_id": "programs"}],
    }
    denied = api.upload("mike", programs, unique_pdf())
    assert denied.status_code == 403
    assert denied.json()["code"] == "upload_forbidden"
    assert api.upload("mike", HR_METADATA, unique_pdf()).status_code == 403
    assert api.upload("priya.manager", programs, unique_pdf()).status_code == 201

    auditor = temporary_profile("audit.user", "engineering")
    as_auditor = api.upload(
        "audit.user",
        ENGINEERING_METADATA,
        unique_pdf(),
        subject=auditor,
        tenant_id=DEMO_TENANT,
        roles=["auditor", "employee"],
        department="engineering",
    )
    assert as_auditor.status_code == 403

    admin = temporary_profile("admin.user", "it")
    as_admin = api.upload(
        "admin.user",
        HR_METADATA,
        unique_pdf(),
        subject=admin,
        tenant_id=DEMO_TENANT,
        roles=["administrator"],
        department="it",
    )
    assert as_admin.status_code == 201
    # Uploading never grants reading: the administrator cannot open the HR document.
    admin_read = api.client.get(
        f"/v1/documents/{as_admin.json()['document_id']}",
        headers=api.headers(
            "admin.user",
            subject=admin,
            tenant_id=DEMO_TENANT,
            roles=["administrator"],
            department="it",
        ),
    )
    assert admin_read.status_code == 404

    denials = owner_db.fetch(
        "SELECT count(*) AS n FROM authorization_audit_events "
        "WHERE action = 'document.create' AND allowed = false"
    )
    assert denials[0]["n"] >= 3


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        ({**HR_METADATA, "grants": []}, "acl_required"),
        (
            {**HR_METADATA, "grants": [{"principal_type": "department", "principal_id": "it"}]},
            "acl_invalid",
        ),
        (
            {
                **HR_METADATA,
                "grants": [{"principal_type": "subject", "principal_id": str(uuid4())}],
            },
            "acl_invalid",
        ),
        ({**HR_METADATA, "classification": "top_secret"}, "classification_invalid"),
        ({**HR_METADATA, "domain": "finance"}, "metadata_invalid"),
    ],
)
def test_invalid_metadata_and_acl_are_rejected(
    api: Api, metadata: dict[str, Any], code: str
) -> None:
    response = api.upload("helen.hr", metadata, unique_pdf())

    assert response.status_code == 422
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("tool.pdf", b"MZ\x90\x00 renamed executable", 415, "unsupported_media_type"),
        ("letter.xlsx", ooxml_bytes(DOCX_PART), 415, "unsupported_media_type"),
        ("empty.txt", b"", 422, "empty_file"),
    ],
)
def test_bad_files_are_rejected_and_nothing_is_stored(
    api: Api, owner_db: Any, filename: str, content: bytes, status: int, code: str
) -> None:
    title = f"Rejected {uuid4()}"

    response = api.upload("helen.hr", {**HR_METADATA, "title": title}, content, filename=filename)

    assert (response.status_code, response.json()["code"]) == (status, code)
    rows = owner_db.fetch("SELECT 1 FROM resource_descriptors WHERE title = $1", title)
    assert rows == []


def test_two_files_in_one_upload_are_rejected(api: Api) -> None:
    response = api.client.post(
        "/v1/documents/uploads",
        headers=api.headers("helen.hr", key=f"key-{uuid4()}"),
        data={"metadata": json.dumps(HR_METADATA)},
        files=[
            ("file", ("a.pdf", unique_pdf(), "application/pdf")),
            ("other", ("b.pdf", unique_pdf(), "application/pdf")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "single_file_required"


def test_upload_requires_authentication_and_idempotency_key(api: Api) -> None:
    anonymous = api.client.post(
        "/v1/documents/uploads",
        data={"metadata": json.dumps(HR_METADATA)},
        files={"file": ("a.pdf", unique_pdf(), "application/pdf")},
    )
    without_key = api.upload("helen.hr", HR_METADATA, unique_pdf(), key=None)

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "authentication_required"
    assert without_key.status_code == 400
    assert without_key.json()["code"] == "idempotency_key_required"


def test_oversized_upload_is_rejected_by_the_guard(
    api_client_factory: Callable[..., TestClient], token_for: Callable[..., str]
) -> None:
    small = Api(api_client_factory(upload_max_bytes=1024), token_for)

    response = small.upload("helen.hr", HR_METADATA, b"%PDF-1.4\n" + b"x" * 70_000)
    within_overhead = small.upload("helen.hr", HR_METADATA, b"%PDF-1.4\n" + b"x" * 2_000)

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"
    assert within_overhead.status_code == 413  # guard allowed the body; the file check did not


# --- idempotency and duplicates ----------------------------------------------------------


def test_replay_with_same_key_returns_the_same_result(api: Api, owner_db: Any) -> None:
    key = f"key-{uuid4()}"
    content = unique_pdf()

    first = api.upload("helen.hr", HR_METADATA, content, key=key)
    replay = api.upload("helen.hr", HR_METADATA, content, key=key)
    reused = api.upload("helen.hr", HR_METADATA, unique_pdf(), key=key)

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    assert reused.status_code == 422
    assert reused.json()["code"] == "idempotency_key_reused"
    rows = owner_db.fetch(
        "SELECT count(*) AS n FROM documents WHERE id = $1::uuid", first.json()["document_id"]
    )
    assert rows[0]["n"] == 1


def test_own_duplicate_points_to_the_existing_document(api: Api) -> None:
    content = unique_pdf()
    first = api.upload("helen.hr", HR_METADATA, content)

    again = api.upload("helen.hr", {**HR_METADATA, "title": "Same bytes again"}, content)

    assert again.status_code == 200
    assert again.json()["duplicate_of"] == first.json()["document_id"]
    assert again.json()["version"]["id"] == first.json()["version"]["id"]


def test_own_reupload_with_different_access_is_a_new_document(api: Api) -> None:
    content = unique_pdf("access")
    first = api.upload("helen.hr", HR_METADATA, content).json()["document_id"]
    helen_only = [{"principal_type": "subject", "principal_id": USERS["helen.hr"]["subject"]}]
    internal_hr = {
        **HR_METADATA,
        "classification": "internal",
        "grants": [{"principal_type": "department", "principal_id": "human-resources"}],
    }

    narrower = api.upload("helen.hr", {**HR_METADATA, "grants": helen_only}, content)
    reclassified = api.upload("helen.hr", internal_hr, content)

    for response in (narrower, reclassified):
        assert response.status_code == 201
        assert response.json()["duplicate_of"] is None
        assert response.json()["document_id"] != first
    assert api.get("helen.hr", narrower.json()["document_id"]).json()["grants"] == [
        {**helen_only[0], "action": "resource.read"}
    ]


def test_other_users_identical_file_is_a_new_document_and_leaks_nothing(
    api: Api, owner_db: Any
) -> None:
    content = unique_pdf("shared")
    helen = api.upload(
        "helen.hr",
        {
            **ENGINEERING_METADATA,
            "department": "human-resources",
            "grants": [{"principal_type": "role", "principal_id": "hr_manager"}],
        },
        content,
    )
    headers = api.headers("mike", key=f"key-{uuid4()}")

    mike = api.client.post(
        "/v1/documents/uploads",
        headers=headers,
        data={"metadata": json.dumps(ENGINEERING_METADATA)},
        files={"file": ("a.pdf", content, "application/pdf")},
    )

    assert helen.status_code == 201
    assert mike.status_code == 201
    assert mike.json()["duplicate_of"] is None
    assert mike.json()["document_id"] != helen.json()["document_id"]
    audit = owner_db.fetch(
        "SELECT action FROM authorization_audit_events WHERE correlation_id = $1",
        headers["X-Correlation-ID"],
    )
    assert [row["action"] for row in audit] == ["document.create"]  # no read probes


# --- versions ----------------------------------------------------------------------------


def test_versions_inherit_acl_and_support_rollback(api: Api) -> None:
    v1_content, v2_content = unique_pdf("v1"), unique_pdf("v2")
    document_id = api.upload("helen.hr", HR_METADATA, v1_content).json()["document_id"]

    v2 = api.upload_version("helen.hr", document_id, v2_content)
    same_as_latest = api.upload_version("helen.hr", document_id, v2_content)
    rollback = api.upload_version("helen.hr", document_id, v1_content)

    assert v2.status_code == 201 and v2.json()["version"]["version_number"] == 2
    assert same_as_latest.status_code == 200
    assert same_as_latest.json()["version"]["id"] == v2.json()["version"]["id"]
    assert rollback.status_code == 201 and rollback.json()["version"]["version_number"] == 3
    document = api.get("helen.hr", document_id).json()
    assert document["latest_version_number"] == 3
    assert [v["version_number"] for v in document["versions"]] == [1, 2, 3]
    assert api.get("mike", document_id).status_code == 404


def test_version_upload_on_hidden_or_missing_document_is_a_safe_404(api: Api) -> None:
    document_id = api.upload("helen.hr", HR_METADATA, unique_pdf()).json()["document_id"]

    by_mike = api.upload_version("mike", document_id, unique_pdf())
    by_other_tenant = api.upload_version("evan.external", document_id, unique_pdf())
    missing = api.upload_version("helen.hr", str(uuid4()), unique_pdf())

    assert by_mike.status_code == by_other_tenant.status_code == missing.status_code == 404
    assert by_mike.json()["code"] == missing.json()["code"] == "resource_not_found"


def test_adding_a_version_requires_read_access(api: Api) -> None:
    content = unique_pdf("unreadable")
    helen_only = {
        **ENGINEERING_METADATA,
        "grants": [{"principal_type": "subject", "principal_id": USERS["helen.hr"]["subject"]}],
    }
    # Mike may upload engineering documents but is not on this one's ACL, even as its creator.
    hidden = api.upload("mike", helen_only, content).json()["document_id"]
    shared = api.upload("mike", ENGINEERING_METADATA, unique_pdf()).json()["document_id"]

    same_bytes = api.upload_version("mike", hidden, content)
    other_bytes = api.upload_version("mike", hidden, unique_pdf())

    assert same_bytes.status_code == other_bytes.status_code == 404
    same_body, other_body = same_bytes.json(), other_bytes.json()
    assert {**same_body, "correlation_id": None} == {**other_body, "correlation_id": None}
    assert api.get("helen.hr", hidden).json()["latest_version_number"] == 1
    assert api.upload_version("mike", shared, unique_pdf()).status_code == 201


def test_concurrent_identical_versions_create_exactly_one(api: Api, owner_db: Any) -> None:
    document_id = api.upload("helen.hr", HR_METADATA, unique_pdf()).json()["document_id"]
    content = unique_pdf("race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: api.upload_version("helen.hr", document_id, content), range(2))
        )

    assert sorted(response.status_code for response in responses) == [200, 201]
    rows = owner_db.fetch(
        "SELECT version_number FROM document_versions WHERE document_id = $1::uuid "
        "ORDER BY version_number",
        document_id,
    )
    assert [row["version_number"] for row in rows] == [1, 2]


# --- storage and database boundaries -----------------------------------------------------


def test_store_outage_returns_503_and_commits_nothing(
    api_client_factory: Callable[..., TestClient],
    token_for: Callable[..., str],
    owner_db: Any,
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"a file where the store directory should be")
    client = Api(api_client_factory(store_path=blocked), token_for)
    title = f"Store outage {uuid4()}"

    response = client.upload("helen.hr", {**HR_METADATA, "title": title}, unique_pdf())

    assert response.status_code == 503
    assert response.json()["code"] == "document_store_unavailable"
    assert owner_db.fetch("SELECT 1 FROM resource_descriptors WHERE title = $1", title) == []
    assert client.client.get("/v1/health/ready").json()["code"] == "document_store_unavailable"


@pytest.mark.asyncio
async def test_runtime_role_cannot_rewrite_documents(app_dsn: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    connection = await asyncpg.connect(app_dsn)
    try:
        assert await connection.fetchval("SELECT count(*) FROM documents") == 0  # no context
        for statement in (
            "UPDATE document_versions SET status = 'stored' WHERE false",
            "DELETE FROM document_versions WHERE false",
            "UPDATE documents SET domain = 'hr' WHERE false",
            "DELETE FROM documents WHERE false",
            "UPDATE upload_requests SET response_status = 200 WHERE false",
        ):
            transaction = connection.transaction()
            await transaction.start()
            try:
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true), "
                    "set_config('app.user_id', $2, true)",
                    DEMO_TENANT,
                    USERS["helen.hr"]["subject"],
                )
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await connection.execute(statement)
            finally:
                await transaction.rollback()
    finally:
        await connection.close()


def _as_app_role(app_dsn: str, username: str, statement: str, *args: Any) -> Any:
    """Run one statement as kribu_app in the user's tenant context and roll it back."""
    import asyncpg  # type: ignore[import-untyped]

    async def run() -> Any:
        connection = await asyncpg.connect(app_dsn)
        try:
            transaction = connection.transaction()
            await transaction.start()
            try:
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true), "
                    "set_config('app.user_id', $2, true)",
                    USERS[username]["tenant_id"],
                    USERS[username]["subject"],
                )
                return await connection.fetch(statement, *args)
            finally:
                await transaction.rollback()
        finally:
            await connection.close()

    return asyncio.run(run())


def test_version_counter_only_advances_by_one(api: Api, app_dsn: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    document_id = api.upload("helen.hr", HR_METADATA, unique_pdf()).json()["document_id"]

    for change in ("- 1", "+ 5"):
        with pytest.raises(asyncpg.CheckViolationError):
            _as_app_role(
                app_dsn,
                "helen.hr",
                "UPDATE documents SET latest_version_number = latest_version_number "
                f"{change} WHERE id = $1::uuid",
                document_id,
            )


def test_stored_upload_responses_are_private_to_their_sender(api: Api, app_dsn: str) -> None:
    key = f"private-{uuid4()}"
    assert api.upload("helen.hr", HR_METADATA, unique_pdf(), key=key).status_code == 201

    query = "SELECT 1 FROM upload_requests WHERE idempotency_key = $1"
    assert len(_as_app_role(app_dsn, "helen.hr", query, key)) == 1
    assert _as_app_role(app_dsn, "mike", query, key) == []


def test_callers_who_may_not_upload_cannot_probe_for_users(api: Api) -> None:
    probing = {
        **HR_METADATA,
        "grants": [{"principal_type": "subject", "principal_id": str(uuid4())}],
    }

    response = api.upload("mike", probing, unique_pdf())

    assert response.status_code == 403
    assert response.json()["code"] == "upload_forbidden"


# --- parsing preview and original download ------------------------------------------------


def test_preview_waits_for_a_complete_parse_and_preserves_authorization(
    api: Api, owner_db: Any
) -> None:
    created = api.upload("helen.hr", HR_METADATA, unique_pdf("preview")).json()
    document_id = created["document_id"]
    version_id = created["version"]["id"]

    waiting = api.client.get(
        f"/v1/documents/{document_id}/versions/{version_id}/preview",
        headers=api.headers("helen.hr"),
    )
    denied = api.client.get(
        f"/v1/documents/{document_id}/versions/{version_id}/preview",
        headers=api.headers("mike"),
    )
    downloaded = api.client.get(
        f"/v1/documents/{document_id}/versions/{version_id}/download",
        headers=api.headers("helen.hr"),
    )

    assert waiting.status_code == 202
    assert waiting.json()["status"] == "queued"
    assert denied.status_code == 404
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")

    extraction_id = str(uuid4())
    owner_db.execute(
        "UPDATE document_ingestion_jobs SET state = 'ready' WHERE document_version_id = $1::uuid",
        version_id,
    )
    owner_db.execute(
        "INSERT INTO document_extractions "
        "(id, tenant_id, document_id, document_version_id, parser_name, parser_version, "
        "normalization_version, block_count) "
        "VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, 'test', '1', 'v1', 1)",
        extraction_id,
        DEMO_TENANT,
        document_id,
        version_id,
    )
    owner_db.execute(
        "INSERT INTO document_content_blocks "
        "(id, tenant_id, extraction_id, document_id, document_version_id, ordinal, "
        "block_type, text, locator) "
        "VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::uuid, 1, 'paragraph', $6, $7::jsonb)",
        str(uuid4()),
        DEMO_TENANT,
        extraction_id,
        document_id,
        version_id,
        "SYNTHETIC ONLY: approved preview content.",
        json.dumps({"kind": "text_line", "line": 1}),
    )

    ready = api.client.get(
        f"/v1/documents/{document_id}/versions/{version_id}/preview",
        headers=api.headers("helen.hr"),
    )
    assert ready.status_code == 200
    assert ready.json()["blocks"] == [
        {
            "ordinal": 1,
            "block_type": "paragraph",
            "text": "SYNTHETIC ONLY: approved preview content.",
            "locator": {"kind": "text_line", "line": 1},
        }
    ]
