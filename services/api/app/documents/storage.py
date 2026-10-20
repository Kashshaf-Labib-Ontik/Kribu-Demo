"""Original-file storage behind the ``ObjectStore`` boundary.

Keys are content-addressed per tenant (``tenants/{tenant}/sha256/{hh}/{hex}``), so identical
bytes in one tenant share a blob and tenants never share one. Callers never see paths. Every
``put`` performs the full write (no short-circuit for an existing blob) so timing reveals
nothing about other uploads. Methods block; call them from a worker thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from app.documents.errors import DocumentStoreUnavailableError

logger = logging.getLogger(__name__)

COPY_CHUNK_BYTES = 1024 * 1024
REPLACE_ATTEMPTS = 10
REPLACE_RETRY_SECONDS = 0.01


class ObjectStore(Protocol):
    def put(self, source: BinaryIO, *, tenant_id: UUID, sha256: bytes) -> str: ...

    def read(self, key: str) -> bytes: ...

    def probe(self) -> None: ...


def storage_key(tenant_id: UUID, sha256: bytes) -> str:
    digest = sha256.hex()
    return f"tenants/{tenant_id}/sha256/{digest[:2]}/{digest}"


class LocalFileObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, source: BinaryIO, *, tenant_id: UUID, sha256: bytes) -> str:
        key = storage_key(tenant_id, sha256)
        target = self._root / key
        # Keep the temporary name short.  Repeating the 64-character digest here pushed
        # otherwise valid pytest and user paths over Windows' legacy MAX_PATH boundary.
        temporary = target.parent / f".{uuid4().hex}.tmp"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.seek(0)
            with _create_private(temporary) as handle:
                shutil.copyfileobj(source, handle, COPY_CHUNK_BYTES)
                handle.flush()
                os.fsync(handle.fileno())
            self._replace(temporary, target, sha256)
            _fsync_directory(target.parent)
        except OSError as exc:
            logger.warning("document store write failed", exc_info=True)
            raise DocumentStoreUnavailableError() from exc
        finally:
            _remove_quietly(temporary)
        return key

    def probe(self) -> None:
        probe_file = self._root / f".probe-{uuid4().hex}"
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with _create_private(probe_file) as handle:
                handle.write(b"ok")
        except OSError as exc:
            logger.warning("document store probe failed", exc_info=True)
            raise DocumentStoreUnavailableError() from exc
        finally:
            _remove_quietly(probe_file)

    def read(self, key: str) -> bytes:
        """Return a stored object after rejecting path traversal or absolute keys.

        The storage key always comes from the database; this extra validation keeps the adapter
        safe if a future caller accidentally treats a client value as a key.
        """
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise DocumentStoreUnavailableError()
        try:
            return (self._root / relative).read_bytes()
        except OSError as exc:
            logger.warning("document store read failed", exc_info=True)
            raise DocumentStoreUnavailableError() from exc

    @staticmethod
    def _replace(temporary: Path, target: Path, sha256: bytes) -> None:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, target)
                return
            except PermissionError:
                # Windows briefly locks a destination while another writer replaces or opens it.
                # An existing blob with the expected hash is already the desired outcome.
                try:
                    if target.exists() and _sha256_of(target) == sha256:
                        return
                except PermissionError:
                    pass
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_RETRY_SECONDS)


def _create_private(path: Path) -> BinaryIO:
    """A new file readable only by the API user (blobs keep this mode after the replace)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    return os.fdopen(os.open(path, flags, 0o600), "wb")


def _remove_quietly(path: Path) -> None:
    """Cleanup must never mask the original outcome; a leftover temp file is harmless."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("document store cleanup failed", exc_info=True)


def _sha256_of(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.digest()


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":  # directory handles cannot be fsynced on Windows
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
