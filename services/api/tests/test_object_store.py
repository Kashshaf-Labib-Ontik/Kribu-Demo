from __future__ import annotations

import hashlib
import io
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest

from app.documents.errors import DocumentStoreUnavailableError
from app.documents.storage import LocalFileObjectStore, storage_key

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("22222222-2222-4222-8222-222222222222")
CONTENT = b"SYNTHETIC ONLY: stored original"
DIGEST = hashlib.sha256(CONTENT).digest()


def test_put_is_content_addressed_tenant_scoped_and_idempotent(tmp_path: Path) -> None:
    store = LocalFileObjectStore(tmp_path)

    first = store.put(io.BytesIO(CONTENT), tenant_id=TENANT, sha256=DIGEST)
    second = store.put(io.BytesIO(CONTENT), tenant_id=TENANT, sha256=DIGEST)
    other = store.put(io.BytesIO(CONTENT), tenant_id=OTHER_TENANT, sha256=DIGEST)

    assert first == second == storage_key(TENANT, DIGEST)
    assert first == f"tenants/{TENANT}/sha256/{DIGEST.hex()[:2]}/{DIGEST.hex()}"
    assert other.startswith(f"tenants/{OTHER_TENANT}/")
    assert (tmp_path / first).read_bytes() == CONTENT
    stored = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(stored) == 2  # one blob per tenant, no temporary files left behind


def test_put_reads_from_the_start_of_the_stream(tmp_path: Path) -> None:
    stream = io.BytesIO(CONTENT)
    stream.seek(len(CONTENT))

    key = LocalFileObjectStore(tmp_path).put(stream, tenant_id=TENANT, sha256=DIGEST)

    assert (tmp_path / key).read_bytes() == CONTENT


def test_unwritable_root_is_a_store_outage(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_bytes(b"file in the way")
    store = LocalFileObjectStore(blocked)

    with pytest.raises(DocumentStoreUnavailableError):
        store.put(io.BytesIO(CONTENT), tenant_id=TENANT, sha256=DIGEST)
    with pytest.raises(DocumentStoreUnavailableError):
        store.probe()


def test_probe_leaves_nothing_behind(tmp_path: Path) -> None:
    LocalFileObjectStore(tmp_path / "store").probe()

    assert list((tmp_path / "store").iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_blobs_are_private_to_the_api_user(tmp_path: Path) -> None:
    key = LocalFileObjectStore(tmp_path).put(io.BytesIO(CONTENT), tenant_id=TENANT, sha256=DIGEST)

    assert stat.S_IMODE((tmp_path / key).stat().st_mode) == 0o600


def test_cleanup_failure_does_not_hide_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("held open")

    monkeypatch.setattr(Path, "unlink", refuse_unlink)
    store = LocalFileObjectStore(tmp_path)

    key = store.put(io.BytesIO(CONTENT), tenant_id=TENANT, sha256=DIGEST)
    store.probe()

    assert (tmp_path / key).read_bytes() == CONTENT
