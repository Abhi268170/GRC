"""Uploaded files: read with a size limit, and safe file names for downloads."""

import re
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

CHUNK = 1024 * 1024


async def read_limited(file: UploadFile, max_bytes: int, too_large: str) -> bytes:
    """Read an upload, stopping as soon as it passes the limit."""
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(413, too_large)
    chunks, total = [], 0
    while chunk := await file.read(CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, too_large)
        chunks.append(chunk)
    return b"".join(chunks)


def clean_filename(name: str | None, fallback: str = "file") -> str:
    """A display name without path parts or control characters, at most 200 characters."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:200] or fallback


def content_disposition(filename: str, inline: bool = False) -> str:
    """A Content-Disposition value that is valid for any file name: an ASCII fallback plus the
    real name percent-encoded (RFC 6266), so quotes and non-Latin names can't break the header."""
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", filename.encode("ascii", "replace").decode()).strip() or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
