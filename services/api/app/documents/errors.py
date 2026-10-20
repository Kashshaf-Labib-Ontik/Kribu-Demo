from __future__ import annotations

from app.core.errors import AppError


class DocumentError(AppError):
    pass


class UploadTooLargeError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="upload_too_large",
            message="The upload exceeds the maximum allowed size.",
            status_code=413,
        )


class UnsupportedMediaTypeError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="unsupported_media_type",
            message="Only PDF, DOCX, XLSX, CSV, TXT, and Markdown files are accepted.",
            status_code=415,
        )


class EmptyFileError(DocumentError):
    def __init__(self) -> None:
        super().__init__(code="empty_file", message="The uploaded file is empty.", status_code=422)


class SingleFileRequiredError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="single_file_required",
            message="Exactly one file must be uploaded.",
            status_code=422,
        )


class MetadataInvalidError(DocumentError):
    def __init__(self, code: str = "metadata_invalid") -> None:
        super().__init__(code=code, message="The document metadata is invalid.", status_code=422)


class AclRequiredError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="acl_required",
            message="At least one read grant is required.",
            status_code=422,
        )


class AclInvalidError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="acl_invalid",
            message="One or more access grants are invalid.",
            status_code=422,
        )


class IdempotencyKeyRequiredError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="idempotency_key_required",
            message="An Idempotency-Key header is required for uploads.",
            status_code=400,
        )


class IdempotencyKeyInvalidError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="idempotency_key_invalid",
            message="The Idempotency-Key header is invalid.",
            status_code=400,
        )


class IdempotencyKeyReusedError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="idempotency_key_reused",
            message="This Idempotency-Key was already used for a different request.",
            status_code=422,
        )


class UploadForbiddenError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="upload_forbidden",
            message="You are not allowed to upload this document.",
            status_code=403,
        )


class DocumentStoreUnavailableError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="document_store_unavailable",
            message="Document storage is temporarily unavailable.",
            status_code=503,
        )


class DocumentPreviewUnavailableError(DocumentError):
    def __init__(self) -> None:
        super().__init__(
            code="document_preview_unavailable",
            message="A normalized preview is not available for this document version.",
            status_code=409,
        )
