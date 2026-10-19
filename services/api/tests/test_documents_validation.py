from __future__ import annotations

import hashlib
import io
import struct
import zipfile

import pytest

from app.documents.errors import EmptyFileError, UnsupportedMediaTypeError, UploadTooLargeError
from app.documents.validation import CHUNK_BYTES, analyze_upload, display_filename
from tests.documents_fixtures import (
    DOCX_PART,
    MACRO_CONTENT_TYPES,
    XLSX_PART,
    ooxml_bytes,
    pdf_bytes,
)

LIMIT = 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOCAL_HEADER_BYTES = 30


def corrupt_content_types(archive_bytes: bytes) -> bytes:
    """Keep the central directory intact but make the deflate stream invalid (zlib.error)."""
    info = zipfile.ZipFile(io.BytesIO(archive_bytes)).getinfo("[Content_Types].xml")
    offset = info.header_offset
    name_length, extra_length = struct.unpack_from("<HH", archive_bytes, offset + 26)
    start = offset + LOCAL_HEADER_BYTES + name_length + extra_length
    damaged = bytearray(archive_bytes)
    damaged[start : start + info.compress_size] = b"\xff" * info.compress_size
    return bytes(damaged)


@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("report.pdf", pdf_bytes(), "application/pdf"),
        ("REPORT.PDF", pdf_bytes(), "application/pdf"),
        ("letter.docx", ooxml_bytes(DOCX_PART), DOCX),
        ("salaries.xlsx", ooxml_bytes(XLSX_PART), XLSX),
        ("complaints.csv", "id,channel\n1,হেল্পলাইন\n".encode(), "text/csv"),
        ("notes.txt", "\ufeffSYNTHETIC ONLY".encode(), "text/plain"),
        ("readme.md", b"# Synthetic\n", "text/markdown"),
    ],
)
def test_allowed_types_are_accepted_and_hashed(
    filename: str, content: bytes, media_type: str
) -> None:
    analyzed = analyze_upload(io.BytesIO(content), filename, LIMIT)

    assert analyzed.media_type == media_type
    assert analyzed.size_bytes == len(content)
    assert analyzed.sha256 == hashlib.sha256(content).digest()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("tool.exe", b"MZ\x90\x00binary"),
        ("tool.pdf", b"MZ\x90\x00binary renamed to pdf"),
        ("noextension", pdf_bytes()),
        ("archive.zip", ooxml_bytes(DOCX_PART)),
        ("letter.xlsx", ooxml_bytes(DOCX_PART)),
        ("sheet.docx", ooxml_bytes(XLSX_PART)),
        ("letter.docx", ooxml_bytes(DOCX_PART, content_types=None)),
        ("macro.docx", ooxml_bytes(DOCX_PART, content_types=MACRO_CONTENT_TYPES)),
        ("macro.docx", ooxml_bytes(DOCX_PART, extra={"word/vbaProject.bin": b"vba"})),
        ("xlm.xlsx", ooxml_bytes(XLSX_PART, extra={"xl/macrosheets/sheet1.xml": b"<xm/>"})),
        ("corrupt.docx", corrupt_content_types(ooxml_bytes(DOCX_PART))),
        ("letter.docx", b"PK\x03\x04 truncated zip"),
        ("letter.docx", pdf_bytes()),
        ("bad.csv", b"id,name\n1,\xff\xfe\n"),
        ("nul.txt", b"SYNTHETIC\x00ONLY"),
        ("truncated.txt", "বাংলা".encode()[:-1]),
        ("late.pdf", b"x" * 1100 + b"%PDF-1.4"),
    ],
)
def test_disguised_or_unsupported_files_are_rejected(filename: str, content: bytes) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        analyze_upload(io.BytesIO(content), filename, LIMIT)


def test_pdf_header_after_a_short_preamble_is_accepted() -> None:
    content = b"\n" * 500 + pdf_bytes()

    assert analyze_upload(io.BytesIO(content), "a.pdf", LIMIT).media_type == "application/pdf"


def test_multibyte_text_split_across_chunks_is_valid() -> None:
    character = "ক".encode()  # three bytes in UTF-8
    content = b"a" * (CHUNK_BYTES - 1) + character * 10

    assert analyze_upload(io.BytesIO(content), "bangla.txt", LIMIT).size_bytes == len(content)


def test_oversized_content_content_types_part_is_rejected() -> None:
    oversized = b"<Types>" + b" " * (65 * 1024) + b"</Types>"

    with pytest.raises(UnsupportedMediaTypeError):
        analyze_upload(io.BytesIO(ooxml_bytes(DOCX_PART, content_types=oversized)), "a.docx", LIMIT)


def test_empty_file_is_rejected() -> None:
    with pytest.raises(EmptyFileError):
        analyze_upload(io.BytesIO(b""), "empty.txt", LIMIT)


def test_size_limit_is_inclusive() -> None:
    assert analyze_upload(io.BytesIO(b"a" * 100), "limit.txt", 100).size_bytes == 100
    with pytest.raises(UploadTooLargeError):
        analyze_upload(io.BytesIO(b"a" * 101), "limit.txt", 100)


def test_stream_is_rewound_for_storage() -> None:
    stream = io.BytesIO(pdf_bytes())

    analyze_upload(stream, "a.pdf", LIMIT)

    assert stream.tell() == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:\\Users\\someone\\Desktop\\report.pdf", "report.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("  cafe\u0301.md  ", "café.md"),
        (None, ""),
        ("a" * 300 + ".pdf", "a" * 255),
        ("re\x00po\x1frt\n.pdf", "report.pdf"),
        ("ক্‍ষ.txt", "ক্‍ষ.txt"),  # ZWJ (format, not control) is kept
    ],
)
def test_display_filename_is_a_safe_label(raw: str | None, expected: str) -> None:
    assert display_filename(raw) == expected
