from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import UploadFile

MAX_PPTX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
SAFE_FILENAME_RE = re.compile(r"[^\w .()\[\]-]+", re.UNICODE)
REQUIRED_PPTX_MEMBERS = {"[Content_Types].xml", "ppt/presentation.xml"}


class PptxValidationError(ValueError):
    """The uploaded file is not an acceptable PPTX."""


@dataclass(frozen=True)
class StagedPptx:
    path: Path
    download_filename: str
    sha256: str
    file_size: int


def safe_download_filename(filename: str | None, fallback: str) -> str:
    """Return a single safe basename while retaining the user's filename."""

    candidate = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    candidate = SAFE_FILENAME_RE.sub("_", candidate).strip(" .")
    if not candidate:
        candidate = fallback
    if not candidate.lower().endswith(".pptx"):
        candidate = f"{candidate}.pptx"
    return candidate[:255]


def stage_pptx_upload(
    upload: UploadFile,
    destination_dir: Path,
    fallback_filename: str,
    max_bytes: int = MAX_PPTX_UPLOAD_BYTES,
) -> StagedPptx:
    """Copy, hash, and validate an upload in the final directory's filesystem."""

    original_name = upload.filename or ""
    if Path(original_name.replace("\\", "/")).suffix.lower() != ".pptx":
        raise PptxValidationError("file must have a .pptx extension")

    destination_dir.mkdir(parents=True, exist_ok=True)
    staged_path: Path | None = None
    digest = sha256()
    file_size = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination_dir, prefix=".pptx-upload-", suffix=".tmp", delete=False
        ) as staged_file:
            staged_path = Path(staged_file.name)
            while True:
                chunk = upload.file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_bytes:
                    raise PptxValidationError(
                        f"file exceeds the maximum size of {max_bytes} bytes"
                    )
                staged_file.write(chunk)
                digest.update(chunk)

        try:
            with ZipFile(staged_path) as archive:
                names = set(archive.namelist())
                missing = REQUIRED_PPTX_MEMBERS - names
                if missing:
                    missing_names = ", ".join(sorted(missing))
                    raise PptxValidationError(f"PPTX is missing required entries: {missing_names}")
                if archive.testzip() is not None:
                    raise PptxValidationError("PPTX contains a corrupt ZIP member")
        except (BadZipFile, OSError) as exc:
            raise PptxValidationError("file is not a valid PPTX ZIP archive") from exc

        return StagedPptx(
            path=staged_path,
            download_filename=safe_download_filename(original_name, fallback_filename),
            sha256=digest.hexdigest(),
            file_size=file_size,
        )
    except Exception:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise
