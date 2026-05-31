"""
Central upload limits and allowed MIME types (chunk upload + vault upload).
"""

ALLOWED_CONTENT_TYPES = frozenset({
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "text/comma-separated-values",
    "application/csv",
    "application/x-csv",
    "image/jpeg",
    "image/png",
    "application/pdf",
    "image/webp",
    "application/zip",
    "application/x-zip-compressed",
    "application/json",
    "application/xml",
    "text/xml",
    # magic may return octet-stream for ZIP-based Office docs; cross-checked with declared type on chunk 0
    "application/octet-stream",
})

ALLOWED_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".zip", ".json", ".xml",
})

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB per file
#MAX_STORAGE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB per user
MAX_STORAGE_BYTES = 10 * 1024 * 1024  # 10 MB per user
MAX_CHUNK_BYTES = 10 * 1024 * 1024  # 10 MB per chunk (match frontend CHUNK_SIZE)


def format_bytes(n: int) -> str:
    mb = 1024 * 1024
    gb = 1024 * 1024 * 1024
    if n < mb:
        return f"{n / 1024:.2f} KB"
    if n < gb:
        return f"{n / mb:.2f} MB"
    return f"{n / gb:.2f} GB"


def extension_for_filename(name: str) -> str:
    if not name or "." not in name:
        return ""
    return name[name.rfind(".") :].lower()


def is_allowed_extension(filename: str) -> bool:
    ext = extension_for_filename(filename)
    return bool(ext) and ext in ALLOWED_EXTENSIONS
