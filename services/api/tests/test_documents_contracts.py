from __future__ import annotations

import json

import pytest

from app.documents.errors import (
    AclInvalidError,
    AclRequiredError,
    IdempotencyKeyInvalidError,
    IdempotencyKeyRequiredError,
    MetadataInvalidError,
)
from app.documents.service import (
    parse_metadata,
    request_fingerprint,
    requested_grants,
    require_idempotency_key,
)


def metadata(**overrides: object) -> str:
    payload: dict[str, object] = {
        "title": "Synthetic salary letter",
        "classification": "restricted_hr",
        "department": "human-resources",
        "domain": "hr",
        "project": "HR history",
        "document_date": "2026-01-31",
        "grants": [{"principal_type": "role", "principal_id": "hr_manager"}],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_valid_metadata_is_normalized() -> None:
    parsed = parse_metadata(metadata(title="  Café বেতন  "))

    assert parsed.title == "Café বেতন"
    assert parsed.domain == "hr"
    assert parse_metadata(metadata(title="ক্‍ষ")).title == "ক্‍ষ"  # ZWJ is allowed
    assert str(parsed.document_date) == "2026-01-31"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (metadata(classification="top_secret"), "classification_invalid"),
        (metadata(classification=None), "classification_invalid"),
        (metadata(domain="finance"), "metadata_invalid"),
        (metadata(title="   "), "metadata_invalid"),
        (metadata(title="x" * 201), "metadata_invalid"),
        (metadata(owner="someone-else"), "metadata_invalid"),
        (metadata(document_date="31/01/2026"), "metadata_invalid"),
        (metadata(title="salary\u0000letter"), "metadata_invalid"),
        (metadata(project="line\nbreak"), "metadata_invalid"),
        (
            metadata(grants=[{"principal_type": "subject", "principal_id": "a\u0000b"}]),
            "metadata_invalid",
        ),
        ("not json", "metadata_invalid"),
    ],
)
def test_invalid_metadata_is_rejected_with_a_stable_code(raw: str, code: str) -> None:
    with pytest.raises(MetadataInvalidError) as raised:
        parse_metadata(raw)

    assert raised.value.code == code


def test_upload_requires_an_explicit_read_grant() -> None:
    with pytest.raises(AclRequiredError):
        requested_grants(parse_metadata(metadata(grants=[])))


@pytest.mark.parametrize(
    "grant",
    [
        {"principal_type": "role", "principal_id": "superuser"},
        {"principal_type": "department", "principal_id": "engineering"},
    ],
    ids=["unknown-role", "department-mismatch"],
)
def test_invalid_grants_are_rejected(grant: dict[str, str]) -> None:
    with pytest.raises(AclInvalidError):
        requested_grants(parse_metadata(metadata(grants=[grant])))


def test_unknown_principal_type_is_invalid_metadata() -> None:
    with pytest.raises(MetadataInvalidError):
        parse_metadata(metadata(grants=[{"principal_type": "group", "principal_id": "x"}]))


def test_grants_are_deduplicated_and_read_only() -> None:
    grants = requested_grants(
        parse_metadata(
            metadata(
                grants=[
                    {"principal_type": "role", "principal_id": "hr_manager"},
                    {"principal_type": "role", "principal_id": "hr_manager"},
                    {"principal_type": "department", "principal_id": "human-resources"},
                ]
            )
        )
    )

    assert [(g.principal_type, g.principal_id, g.action) for g in grants] == [
        ("role", "hr_manager", "resource.read"),
        ("department", "human-resources", "resource.read"),
    ]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_idempotency_key_is_required(value: str | None) -> None:
    with pytest.raises(IdempotencyKeyRequiredError):
        require_idempotency_key(value)


@pytest.mark.parametrize("value", ["short", "x" * 129, "has space here", "semi;colon12"])
def test_malformed_idempotency_key_is_rejected(value: str) -> None:
    with pytest.raises(IdempotencyKeyInvalidError):
        require_idempotency_key(value)


def test_well_formed_idempotency_key_is_accepted() -> None:
    assert require_idempotency_key("upload-2026.10:19_A") == "upload-2026.10:19_A"


def test_fingerprint_covers_route_target_metadata_and_file_hash() -> None:
    base = request_fingerprint("document.create", "new", {"title": "a"}, b"\x01" * 32)

    assert base == request_fingerprint("document.create", "new", {"title": "a"}, b"\x01" * 32)
    assert base != request_fingerprint("document.create", "new", {"title": "a"}, b"\x02" * 32)
    assert base != request_fingerprint("document.create", "new", {"title": "b"}, b"\x01" * 32)
    assert base != request_fingerprint(
        "document.version.create", "new", {"title": "a"}, b"\x01" * 32
    )
