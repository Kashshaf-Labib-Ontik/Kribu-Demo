"""Prove an upload's type from its bytes, hash it, and measure it in one chunked pass.

Standard library only. The extension must agree with the content: PDF needs a ``%PDF-``
header, DOCX/XLSX need a ZIP whose central directory holds the expected OOXML parts (no
member is inflated except a size-capped ``[Content_Types].xml``), and CSV/TXT/Markdown must be
strict UTF-8 without NUL bytes. Macro-enabled Office files are rejected. Blocking I/O: call
from a worker thread.
"""

from __future__ import annotations

import codecs
import hashlib
import lzma
import zipfile
import zlib
from dataclasses import dataclass
from typing import BinaryIO

from app.documents.contracts import normalize_text, strip_control_characters
from app.documents.errors import EmptyFileError, UnsupportedMediaTypeError, UploadTooLargeError

CHUNK_BYTES = 64 * 1024
PDF_HEADER_WINDOW = 1024
CONTENT_TYPES_MAX_BYTES = 64 * 1024
MAX_FILENAME_LENGTH = 255
ZIP_SIGNATURE = b"PK\x03\x04"
# Code-bearing OOXML parts: VBA projects and Excel 4.0 (XLM) macro sheets.
MACRO_PART_MARKERS = ("vbaproject.bin", "macrosheets/")
# Everything a corrupt or hostile archive can raise while being listed or inflated.
ARCHIVE_ERRORS = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    KeyError,
    OSError,
    RuntimeError,
    EOFError,
    ValueError,
    NotImplementedError,
    zlib.error,
    lzma.LZMAError,
)

PDF_TYPES = {".pdf": "application/pdf"}
TEXT_TYPES = {".csv": "text/csv", ".txt": "text/plain", ".md": "text/markdown"}
OOXML_TYPES = {
    ".docx": (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
}
ALLOWED_EXTENSIONS = frozenset(PDF_TYPES) | frozenset(TEXT_TYPES) | frozenset(OOXML_TYPES)


@dataclass(frozen=True)
class AnalyzedFile:
    sha256: bytes
    size_bytes: int
    media_type: str


def display_filename(raw_name: str | None) -> str:
    """The caller's file name for display only: last path segment without control
    characters, NFC, length-capped."""
    name = (raw_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return normalize_text(strip_control_characters(name))[:MAX_FILENAME_LENGTH]


def extension_of(filename: str) -> str:
    _, dot, suffix = filename.rpartition(".")
    return f".{suffix.lower()}" if dot and suffix else ""


def analyze_upload(stream: BinaryIO, filename: str, max_bytes: int) -> AnalyzedFile:
    extension = extension_of(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedMediaTypeError()

    is_text = extension in TEXT_TYPES
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    digest = hashlib.sha256()
    size = 0
    head = b""
    stream.seek(0)
    while chunk := stream.read(CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise UploadTooLargeError()
        digest.update(chunk)
        if len(head) < PDF_HEADER_WINDOW:
            head += chunk[: PDF_HEADER_WINDOW - len(head)]
        if is_text:
            _check_text_chunk(decoder, chunk)

    if size == 0:
        raise EmptyFileError()
    if is_text:
        _check_text_chunk(decoder, b"", final=True)
        media_type = TEXT_TYPES[extension]
    elif extension in PDF_TYPES:
        if b"%PDF-" not in head:
            raise UnsupportedMediaTypeError()
        media_type = PDF_TYPES[extension]
    else:
        required_part, media_type = OOXML_TYPES[extension]
        if not head.startswith(ZIP_SIGNATURE):
            raise UnsupportedMediaTypeError()
        _check_ooxml(stream, required_part)

    stream.seek(0)
    return AnalyzedFile(sha256=digest.digest(), size_bytes=size, media_type=media_type)


def _check_text_chunk(
    decoder: codecs.IncrementalDecoder, chunk: bytes, *, final: bool = False
) -> None:
    if b"\x00" in chunk:
        raise UnsupportedMediaTypeError()
    try:
        decoder.decode(chunk, final=final)
    except UnicodeDecodeError as exc:
        raise UnsupportedMediaTypeError() from exc


def _check_ooxml(stream: BinaryIO, required_part: str) -> None:
    stream.seek(0)
    try:
        with zipfile.ZipFile(stream) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or required_part not in names:
                raise UnsupportedMediaTypeError()
            if any(marker in name.lower() for name in names for marker in MACRO_PART_MARKERS):
                raise UnsupportedMediaTypeError()
            info = archive.getinfo("[Content_Types].xml")
            if info.file_size > CONTENT_TYPES_MAX_BYTES:
                raise UnsupportedMediaTypeError()
            with archive.open(info) as handle:
                content_types = handle.read(CONTENT_TYPES_MAX_BYTES + 1)
    except ARCHIVE_ERRORS as exc:
        raise UnsupportedMediaTypeError() from exc
    if len(content_types) > CONTENT_TYPES_MAX_BYTES or b"macroenabled" in content_types.lower():
        raise UnsupportedMediaTypeError()
