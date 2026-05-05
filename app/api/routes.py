from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Song, SongImportStaging, SongLine, SongVersion
from app.db.session import get_db
from app.services.importer import approve_staging, mark_staging_duplicate
from app.services.normalizer import normalize_text
from app.services.ppt import generate_song_pptx, song_pptx_filename
from app.services.search import search_songs

router = APIRouter(prefix="/api")


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
