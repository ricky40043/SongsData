import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Song,
    SongImportStaging,
    SongLine,
    SongPptVersion,
    SongSlide,
    SongSource,
    SongVersion,
)
from app.db.session import get_db
from app.services.importer import approve_staging, mark_staging_duplicate
from app.services.normalizer import clean_lines, lyrics_hash, normalize_text
from app.services.ppt import generate_song_pptx, song_pptx_filename
from app.services.ppt_versions import (
    MAX_PPTX_UPLOAD_BYTES,
    PptxValidationError,
    safe_download_filename,
    stage_pptx_upload,
)
from app.services.search import search_songs
from app.services.slides import split_lyrics_to_slides

router = APIRouter(prefix="/api")

MAX_TITLE_LENGTH = 300
MAX_LYRICS_LENGTH = 100_000
MAX_METADATA_LENGTH = 300
MAX_COPYRIGHT_LENGTH = 1_000
MAX_LINE_LENGTH = 500
PPTX_UPLOAD_ROOT = Path("data/pptx")
PPTX_EXPORT_ROOT = Path("data/exports")
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DELETE_SONG_PASSWORD = "go for it"


class CreateSongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=MAX_TITLE_LENGTH)
    lyrics: str = Field(..., max_length=MAX_LYRICS_LENGTH)
    album: str | None = Field(default=None, max_length=MAX_METADATA_LENGTH)
    author: str | None = Field(default=None, max_length=MAX_METADATA_LENGTH)
    composer: str | None = Field(default=None, max_length=MAX_METADATA_LENGTH)
    copyright_note: str | None = Field(default=None, max_length=MAX_COPYRIGHT_LENGTH)

    @field_validator("title", "lyrics")
    @classmethod
    def require_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("album", "author", "composer", "copyright_note")
    @classmethod
    def trim_optional_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class DeleteSongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str


def _song_has_generated_ppt(db: Session, song_id: int) -> bool:
    version = db.scalar(
        select(SongVersion)
        .where(SongVersion.song_id == song_id)
        .order_by(SongVersion.id)
        .limit(1)
    )
    return bool(version and version.raw_lyrics and version.raw_lyrics.strip())


def _ppt_version_payload(version: SongPptVersion, request_base: str = "") -> dict:
    return {
        "version_id": version.id,
        "kind": "uploaded",
        "version_name": version.version_name,
        "file_path": version.file_path,
        "download_filename": version.download_filename,
        "sha256": version.sha256,
        "file_size": version.file_size,
        "is_default": version.is_default,
        "overrides_generated": version.overrides_generated,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
        "download_url": (
            f"{request_base}/api/songs/{version.song_id}/pptx-versions/{version.id}/download"
        ),
    }


def _generated_ppt_payload(song: Song, is_default: bool, request_base: str = "") -> dict:
    return {
        "version_id": None,
        "kind": "generated",
        "version_name": "system-generated",
        "file_path": None,
        "download_filename": song_pptx_filename(song.title, song.id),
        "sha256": None,
        "file_size": None,
        "is_default": is_default,
        "overrides_generated": False,
        "created_at": None,
        "updated_at": None,
        "download_url": f"{request_base}/api/songs/{song.id}/pptx",
    }


def _ppt_upload_conflict(
    song_id: int,
    existing_versions: list[SongPptVersion],
    has_generated_ppt: bool,
    message: str,
) -> HTTPException:
    existing = [
        {
            "version_id": version.id,
            "version_name": version.version_name,
            "kind": "uploaded",
            "is_default": version.is_default,
            "download_url": f"/api/songs/{song_id}/pptx-versions/{version.id}/download",
        }
        for version in existing_versions
    ]
    if has_generated_ppt:
        existing.insert(
            0,
            {
                "version_id": None,
                "version_name": "system-generated",
                "kind": "generated",
                "is_default": not any(version.is_default for version in existing_versions),
                "download_url": f"/api/songs/{song_id}/pptx",
            },
        )
    return HTTPException(
        status_code=409,
        detail={
            "code": "pptx_version_conflict",
            "message": message,
            "existing_versions": existing,
            "has_generated_ppt": has_generated_ppt,
        },
    )


def _ensure_upload_path_is_song_owned(path: Path, song_id: int) -> bool:
    root = PPTX_UPLOAD_ROOT.resolve()
    expected_dir = (root / str(song_id)).resolve()
    try:
        return path.resolve().is_relative_to(expected_dir)
    except AttributeError:  # pragma: no cover - Python 3.10 compatibility
        return str(path.resolve()).startswith(f"{expected_dir}{os.sep}")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    return {
        "songs": db.scalar(select(func.count()).select_from(Song)) or 0,
        "staging": db.scalar(select(func.count()).select_from(SongImportStaging)) or 0,
        "pending": db.scalar(
            select(func.count())
            .select_from(SongImportStaging)
            .where(SongImportStaging.parse_status == "parsed")
        )
        or 0,
    }


def _raise_song_duplicate(song: Song, duplicate_field: str) -> None:
    messages = {
        "title": "A song with this title already exists.",
        "lyrics_hash": "A song with the same lyrics already exists.",
    }
    raise HTTPException(
        status_code=409,
        detail={
            "code": "duplicate_song",
            "message": messages[duplicate_field],
            "duplicate_field": duplicate_field,
            "song_id": song.id,
        },
    )


def _handle_song_integrity_error(db: Session, digest: str, exc: IntegrityError) -> None:
    db.rollback()
    existing_lyrics = db.scalar(
        select(Song)
        .join(SongVersion, SongVersion.song_id == Song.id)
        .where(SongVersion.lyrics_hash == digest)
        .order_by(Song.id)
        .limit(1)
    )
    if existing_lyrics:
        _raise_song_duplicate(existing_lyrics, "lyrics_hash")
    raise HTTPException(
        status_code=409,
        detail={
            "code": "song_not_created",
            "message": "The song could not be created safely; please retry.",
        },
    ) from exc


@router.post("/songs", status_code=201)
def create_song(payload: CreateSongRequest, db: Session = Depends(get_db)) -> dict:
    normalized_title = normalize_text(payload.title)
    normalized_lyrics = normalize_text(payload.lyrics)
    if not normalized_title:
        raise HTTPException(status_code=422, detail="title must contain text")
    if not normalized_lyrics:
        raise HTTPException(status_code=422, detail="lyrics must contain text")

    lines = clean_lines(payload.lyrics)
    if not lines:
        raise HTTPException(status_code=422, detail="lyrics must contain at least one line")
    if any(len(line) > MAX_LINE_LENGTH for line in lines):
        raise HTTPException(
            status_code=422,
            detail=f"each lyric line must be at most {MAX_LINE_LENGTH} characters",
        )

    digest = lyrics_hash(normalized_lyrics)
    existing_title = db.scalar(
        select(Song)
        .where(Song.normalized_title == normalized_title)
        .order_by(Song.id)
        .limit(1)
    )
    if existing_title:
        _raise_song_duplicate(existing_title, "title")

    existing_lyrics = db.scalar(
        select(Song)
        .join(SongVersion, SongVersion.song_id == Song.id)
        .where(SongVersion.lyrics_hash == digest)
        .order_by(Song.id)
        .limit(1)
    )
    if existing_lyrics:
        _raise_song_duplicate(existing_lyrics, "lyrics_hash")

    song = Song(
        title=payload.title,
        normalized_title=normalized_title,
        album=payload.album,
        author=payload.author,
        composer=payload.composer,
        copyright_note=payload.copyright_note,
        is_verified=False,
    )
    db.add(song)
    db.flush()

    version = SongVersion(
        song_id=song.id,
        version_name="default",
        raw_lyrics=payload.lyrics,
        normalized_lyrics=normalized_lyrics,
        lyrics_hash=digest,
        is_default=True,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        _handle_song_integrity_error(db, digest, exc)

    for line_order, line in enumerate(lines, start=1):
        db.add(
            SongLine(
                song_id=song.id,
                version_id=version.id,
                line_order=line_order,
                text=line,
                normalized_text=normalize_text(line),
            )
        )

    for slide_order, slide_text in enumerate(split_lyrics_to_slides(payload.lyrics), start=1):
        db.add(
            SongSlide(
                song_id=song.id,
                version_id=version.id,
                slide_order=slide_order,
                text=slide_text,
                line_count=len(clean_lines(slide_text)),
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        _handle_song_integrity_error(db, digest, exc)

    return {
        "status": "created",
        "song_id": song.id,
        "title": song.title,
    }


@router.get("/songs")
def list_songs(
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    normalized = normalize_text(q)

    if normalized:
        matching_song_ids = (
            select(Song.id)
            .outerjoin(SongLine, SongLine.song_id == Song.id)
            .where(
                or_(
                    Song.normalized_title.contains(normalized),
                    SongLine.normalized_text.contains(normalized),
                )
            )
            .distinct()
            .subquery()
        )
        count_query = select(func.count()).select_from(matching_song_ids)
        rows_query = (
            select(Song)
            .where(Song.id.in_(select(matching_song_ids.c.id)))
            .order_by(Song.id.desc())
            .offset(offset)
            .limit(limit)
        )
    else:
        count_query = select(func.count()).select_from(Song)
        rows_query = select(Song).order_by(Song.id.desc()).offset(offset).limit(limit)

    total = db.scalar(count_query) or 0
    songs = db.scalars(rows_query).all()
    return {
        "q": q,
        "limit": limit,
        "offset": offset,
        "total": total,
        "items": [
            {
                "id": song.id,
                "title": song.title,
                "album": song.album,
                "is_verified": song.is_verified,
                "created_at": song.created_at.isoformat() if song.created_at else None,
            }
            for song in songs
        ],
    }


@router.get("/songs/search")
def search(keyword: str, limit: int = 20, db: Session = Depends(get_db)) -> dict:
    return {"keyword": keyword, "results": search_songs(db, keyword, limit)}


@router.get("/songs/{song_id}")
def get_song(song_id: int, db: Session = Depends(get_db)) -> dict:
    song = db.get(Song, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    version = db.scalar(select(SongVersion).where(SongVersion.song_id == song_id))
    return {
        "id": song.id,
        "title": song.title,
        "lyrics": version.raw_lyrics if version else "",
        "album": song.album,
        "author": song.author,
        "composer": song.composer,
        "copyright_note": song.copyright_note,
        "is_verified": song.is_verified,
    }


@router.get("/imports/pending")
def pending_imports(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(SongImportStaging, Song)
        .outerjoin(Song, Song.id == SongImportStaging.possible_duplicate_song_id)
        .where(SongImportStaging.parse_status == "parsed")
        .order_by(SongImportStaging.id)
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "source_site": item.source_site,
                "source_external_id": item.source_external_id,
                "title": item.raw_title,
                "lyrics": item.raw_lyrics,
                "duplicate_status": item.duplicate_status,
                "possible_duplicate_song_id": item.possible_duplicate_song_id,
                "possible_duplicate_title": duplicate.title if duplicate else None,
            }
            for item, duplicate in rows
        ]
    }


@router.post("/imports/{staging_id}/approve")
def approve_import(staging_id: int, db: Session = Depends(get_db)) -> dict:
    result = approve_staging(db, staging_id)
    return result.__dict__


@router.post("/imports/{staging_id}/approve-force")
def approve_import_force(staging_id: int, db: Session = Depends(get_db)) -> dict:
    result = approve_staging(db, staging_id, force=True)
    return result.__dict__


@router.post("/imports/{staging_id}/duplicate")
def duplicate_import(staging_id: int, db: Session = Depends(get_db)) -> dict:
    result = mark_staging_duplicate(db, staging_id)
    return result.__dict__


@router.get("/songs/{song_id}/pptx")
def download_pptx(song_id: int, db: Session = Depends(get_db)) -> FileResponse:
    song = db.get(Song, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    uploaded_default = db.scalar(
        select(SongPptVersion)
        .where(SongPptVersion.song_id == song_id, SongPptVersion.is_default.is_(True))
        .order_by(SongPptVersion.id.desc())
        .limit(1)
    )
    if uploaded_default:
        path = Path(uploaded_default.file_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Uploaded PPTX file not found")
        return FileResponse(
            path,
            media_type=PPTX_MEDIA_TYPE,
            filename=uploaded_default.download_filename,
        )

    filename = song_pptx_filename(song.title, song.id)
    path = PPTX_EXPORT_ROOT / filename
    try:
        output = generate_song_pptx(db, song_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        output,
        media_type=PPTX_MEDIA_TYPE,
        filename=filename,
    )


@router.get("/songs/{song_id}/pptx-versions")
def list_pptx_versions(song_id: int, db: Session = Depends(get_db)) -> dict:
    song = db.get(Song, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    uploaded_versions = db.scalars(
        select(SongPptVersion)
        .where(SongPptVersion.song_id == song_id)
        .order_by(SongPptVersion.created_at, SongPptVersion.id)
    ).all()
    items = [_ppt_version_payload(version) for version in uploaded_versions]
    if _song_has_generated_ppt(db, song_id):
        items.insert(
            0,
            _generated_ppt_payload(
                song,
                is_default=not any(version.is_default for version in uploaded_versions),
            ),
        )
    return {"song_id": song_id, "items": items}


@router.post("/songs/{song_id}/pptx-versions", status_code=201)
def upload_pptx_version(
    song_id: int,
    file: UploadFile = File(...),
    version_name: str = Form(..., max_length=100),
    action: str = Form("ask"),
    db: Session = Depends(get_db),
) -> dict:
    song = db.get(Song, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    version_name = version_name.strip()
    if not version_name:
        raise HTTPException(status_code=422, detail="version_name must not be blank")
    if action not in {"ask", "overwrite", "new_version"}:
        raise HTTPException(
            status_code=422,
            detail="action must be one of: ask, overwrite, new_version",
        )

    existing_versions = db.scalars(
        select(SongPptVersion).where(
            SongPptVersion.song_id == song_id,
            SongPptVersion.version_name == version_name,
        )
    ).all()
    all_uploaded_versions = db.scalars(
        select(SongPptVersion)
        .where(SongPptVersion.song_id == song_id)
        .order_by(SongPptVersion.created_at, SongPptVersion.id)
    ).all()
    has_generated_ppt = _song_has_generated_ppt(db, song_id)
    if action == "ask" and (has_generated_ppt or existing_versions):
        raise _ppt_upload_conflict(
            song_id,
            all_uploaded_versions,
            has_generated_ppt,
            "A generated or uploaded PPTX version already exists; choose overwrite or new_version.",
        )
    if action == "new_version" and existing_versions:
        raise _ppt_upload_conflict(
            song_id,
            all_uploaded_versions,
            has_generated_ppt,
            "An uploaded PPTX with this version name already exists; choose overwrite.",
        )

    destination_dir = PPTX_UPLOAD_ROOT / str(song_id)
    try:
        staged = stage_pptx_upload(
            file,
            destination_dir,
            fallback_filename=song_pptx_filename(version_name, song_id),
            max_bytes=MAX_PPTX_UPLOAD_BYTES,
        )
    except PptxValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    download_filename = safe_download_filename(version_name, staged.download_filename)

    version = existing_versions[0] if existing_versions else SongPptVersion(
        song_id=song_id,
        version_name=version_name,
        file_path="",
        download_filename=download_filename,
        sha256=staged.sha256,
        file_size=staged.file_size,
        is_default=False,
        overrides_generated=False,
    )
    is_overwrite = bool(existing_versions)
    old_path = Path(version.file_path) if version.file_path else None
    final_path: Path | None = None
    backup_path: Path | None = None
    try:
        if not existing_versions:
            db.add(version)
            db.flush()
        final_path = destination_dir / f"{version.id}.pptx"
        if (
            old_path
            and old_path != final_path
            and _ensure_upload_path_is_song_owned(old_path, song_id)
            and old_path.is_file()
        ):
            # Older records should use the same location, but retain a safe
            # rollback path if a manually migrated record does not.
            backup_path = destination_dir / f".pptx-backup-{uuid.uuid4().hex}.tmp"
            os.replace(old_path, backup_path)
        elif final_path.is_file():
            backup_path = destination_dir / f".pptx-backup-{uuid.uuid4().hex}.tmp"
            os.replace(final_path, backup_path)
        os.replace(staged.path, final_path)

        version.file_path = str(final_path)
        version.download_filename = download_filename
        version.sha256 = staged.sha256
        version.file_size = staged.file_size
        version.updated_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) if is_overwrite else None
        )
        if action == "overwrite":
            db.execute(
                update(SongPptVersion)
                .where(SongPptVersion.song_id == song_id)
                .values(is_default=False, overrides_generated=False)
            )
            version.is_default = True
            version.overrides_generated = True
        else:
            version.is_default = False
            version.overrides_generated = False
        db.commit()
    except Exception:
        db.rollback()
        staged.path.unlink(missing_ok=True)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        if backup_path and backup_path.is_file():
            os.replace(backup_path, old_path or final_path)
        raise
    else:
        if backup_path:
            backup_path.unlink(missing_ok=True)

    return {
        "status": "uploaded",
        "song_id": song_id,
        "version": _ppt_version_payload(version),
    }


@router.get("/songs/{song_id}/pptx-versions/{version_id}/download")
def download_uploaded_pptx(
    song_id: int, version_id: int, db: Session = Depends(get_db)
) -> FileResponse:
    version = db.scalar(
        select(SongPptVersion).where(
            SongPptVersion.id == version_id,
            SongPptVersion.song_id == song_id,
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="PPTX version not found")
    path = Path(version.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded PPTX file not found")
    return FileResponse(path, media_type=PPTX_MEDIA_TYPE, filename=version.download_filename)


@router.delete("/songs/{song_id}")
def delete_song(
    song_id: int,
    payload: DeleteSongRequest,
    db: Session = Depends(get_db),
) -> dict:
    if payload.password != DELETE_SONG_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid password")

    song = db.get(Song, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    ppt_paths = [Path(path) for path in db.scalars(
        select(SongPptVersion.file_path).where(SongPptVersion.song_id == song_id)
    ).all()]
    upload_dir = PPTX_UPLOAD_ROOT / str(song_id)
    generated_path = PPTX_EXPORT_ROOT / song_pptx_filename(song.title, song.id)
    db.execute(delete(SongPptVersion).where(SongPptVersion.song_id == song_id))
    db.execute(delete(SongLine).where(SongLine.song_id == song_id))
    db.execute(delete(SongSlide).where(SongSlide.song_id == song_id))
    db.execute(delete(SongSource).where(SongSource.song_id == song_id))
    db.execute(delete(SongVersion).where(SongVersion.song_id == song_id))
    db.delete(song)
    db.commit()

    # Only remove paths recorded for this song and its own upload directory.
    for path in ppt_paths:
        if _ensure_upload_path_is_song_owned(path, song_id):
            path.unlink(missing_ok=True)
    if upload_dir.is_dir() and upload_dir.resolve() == (PPTX_UPLOAD_ROOT / str(song_id)).resolve():
        shutil.rmtree(upload_dir)
    generated_path.unlink(missing_ok=True)
    return {"status": "deleted", "song_id": song_id}
