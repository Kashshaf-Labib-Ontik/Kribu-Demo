"""Synthetic file builders shared by document tests. Content is fictional."""

from __future__ import annotations

import io
import zipfile

DOCX_PART = "word/document.xml"
XLSX_PART = "xl/workbook.xml"
CONTENT_TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="xml" ContentType="application/xml"/></Types>'
)
MACRO_CONTENT_TYPES = CONTENT_TYPES.replace(
    b"application/xml", b"application/vnd.ms-word.document.macroEnabled.main+xml"
)


def pdf_bytes(text: str = "SYNTHETIC ONLY: demo PDF") -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n% "
        + text.encode()
        + b"\ntrailer << /Root 1 0 R >>\n%%EOF\n"
    )


def ooxml_bytes(
    part: str,
    *,
    content_types: bytes | None = CONTENT_TYPES,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if content_types is not None:
            archive.writestr("[Content_Types].xml", content_types)
        archive.writestr(part, b"<document>SYNTHETIC ONLY</document>")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()
