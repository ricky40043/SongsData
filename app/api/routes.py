from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Song, SongImportStaging, SongLine, SongSlide, SongVersion
from app.db.session import get_db
from app.services.importer import approve_staging, mark_staging_duplicate
from app.services.normalizer import clean_lines, lyrics_hash, normalize_text
from app.services.ppt import generate_song_pptx, song_pptx_filename
from app.services.search import search_songs
from app.services.slides import split_lyrics_to_slides

router = APIRouter(prefix="/api")

MAX_TITLE_LENGTH = 300
MAX_LYRICS_LENGTH = 100_000
MAX_METADATA_LENGTH = 300
MAX_COPYRIGHT_LENGTH = 1_000
MAX_LINE_LENGTH = 500


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
    filename = song_pptx_filename(song.title, song.id)
    path = Path("data/exports") / filename
    try:
        output = generate_song_pptx(db, song_id, path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
