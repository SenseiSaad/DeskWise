"""Upload validation: extension allowlist, decompression-bomb and size guards.

Every uploaded byte eventually reaches `rag.extract_text` — through indexing,
preview, or versioning — so the expensive checks (PDF page cap, extracted-text
cap, zip-bomb guard) live in the extraction path where they cannot be skipped,
and the cheap checks (extension, filename length) run in the views so a bad
file is rejected with a clean 400 before it is stored.
"""
from __future__ import annotations

import io
import zipfile

# Only these extensions may be uploaded. The list doubles as the map to
# extract_text's parsers; anything else is rejected at the API boundary.
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg",
}
MAX_FILENAME_LENGTH = 255

# Extraction caps. A 500-page scanned PDF or a 40GB-expanded DOCX must cost a
# bounded amount of CPU/RAM no matter who uploaded it.
MAX_PDF_PAGES = 500
MAX_EXTRACTED_CHARS = 2_000_000  # 2MB of text ≈ 500k tokens — far above any chunk need

# Zip-bomb guards for the OOXML formats (docx/pptx are zip archives).
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class UploadRejected(ValueError):
    """A user-facing upload rejection; views turn this into a 400 response."""


def validate_filename(filename: str) -> str:
    """Return the cleaned basename, rejecting empty/oversized/traversal names."""
    import os

    raw = str(filename or "").strip()
    if not raw:
        raise UploadRejected("A file with a valid name is required.")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise UploadRejected("Path traversal characters or separators are not allowed in filenames.")
    name = os.path.basename(raw)
    if not name or name != raw:
        raise UploadRejected("Invalid filename.")
    if len(name) > MAX_FILENAME_LENGTH:
        raise UploadRejected(
            f"Filename is too long (max {MAX_FILENAME_LENGTH} characters)."
        )
    return name


def validate_extension(filename: str) -> str:
    """Return the lowercased extension when allowlisted, else raise."""
    name = (filename or "").lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadRejected(
            f"File type '{ext or 'unknown'}' is not supported. Allowed: {allowed}."
        )
    return ext


def guard_zip_archive(raw: bytes) -> None:
    """Reject zip archives (docx/pptx) whose decompressed size is absurd.

    A small malicious .docx can expand to gigabytes and exhaust memory during
    parsing; the compressed/uncompressed sizes are declared in the zip central
    directory, so the check costs nothing and needs no decompression.
    """
    if len(raw) < 4 or raw[:2] != b"PK":
        return
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        raise UploadRejected("The document archive is corrupt.")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise UploadRejected(
            "The document expands to more than the supported size limit."
        )
    if len(raw) > 0 and total / len(raw) > MAX_COMPRESSION_RATIO:
        raise UploadRejected("The document archive has an unsafe compression ratio.")


def truncate_text(text: str) -> str:
    """Hard cap on extracted text so no single file can flood memory/DB."""
    if text and len(text) > MAX_EXTRACTED_CHARS:
        return text[:MAX_EXTRACTED_CHARS]
    return text


# AI-07: the server, not the client, decides the stored content type, and the
# first bytes must match the claimed binary format.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_MAGIC = {
    ".docx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}


def content_type_for(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return CONTENT_TYPES.get(name[dot:] if dot >= 0 else "", "application/octet-stream")


def validate_magic(filename: str, head: bytes) -> None:
    """Reject a binary upload whose leading bytes do not match its extension."""
    ext = validate_extension(filename)
    head = head or b""
    if ext == ".pdf":
        # The PDF header may appear anywhere in the first 1024 bytes.
        if b"%PDF-" not in head[:1024]:
            raise UploadRejected("The file content does not match its .pdf extension.")
        return
    sigs = _MAGIC.get(ext)
    if sigs and not any(head.startswith(s) for s in sigs):
        raise UploadRejected(f"The file content does not match its {ext} extension.")


INDEX_FAILED_MESSAGE = "This file could not be indexed. Try re-indexing it, or re-upload it in another format."


def index_error_message(exc: BaseException) -> str:
    """The text stored in Document.index_error (AI-06).

    UploadRejected messages are written for users and kept. Anything else is a
    parser/provider/storage exception that can name internal hosts or paths, so
    the client gets a generic message and the detail goes to the server log."""
    if isinstance(exc, UploadRejected):
        return str(exc)[:300]
    import logging
    logging.getLogger(__name__).warning("document indexing failed: %s", type(exc).__name__, exc_info=exc)
    return INDEX_FAILED_MESSAGE
