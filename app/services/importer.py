from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawlers.base import CrawlSongDetail
from app.db.models import Song, SongImportStaging, SongLine, SongSlide, SongSource, SongVersion
from app.services.normalizer import clean_lines, lyrics_hash, normalize_text
from app.services.slides import split_lyrics_to_slides


@dataclass(frozen=True)
class ImportResult:
    status: str
    staging_id: int | None = None
    song_id: int | None = None
    message: str | None = None


def stage_song(db: Session, detail: CrawlSongDetail) -> ImportResult:
    existing_staging = db.scalar(
        select(SongImportStaging).where(
            SongImportStaging.source_site == detail.source_site,
            SongImportStaging.source_external_id == detail.source_external_id,
        )
    )
    if existing_staging:
        return ImportResult(status="skipped_existing_staging", staging_id=existing_staging.id)

    existing_source = db.scalar(
        select(SongSource).where(
            SongSource.source_site == detail.source_site,
            SongSource.source_external_id == detail.source_external_id,
        )
    )
    if existing_source:
        return ImportResult(status="skipped_existing_source", song_id=existing_source.song_id)

    normalized_title = normalize_text(detail.title)
    normalized_lyrics = normalize_text(detail.lyrics)
    digest = lyrics_hash(normalized_lyrics)
    duplicate_song = db.scalar(
        select(Song)
        .join(SongVersion, SongVersion.song_id == Song.id)
        .where(SongVersion.lyrics_hash == digest)
    )

    staging = SongImportStaging(
        source_site=detail.source_site,
        source_url=detail.source_url,
        source_external_id=detail.source_external_id,
        raw_title=detail.title,
        raw_lyrics=detail.lyrics,
        normalized_title=normalized_title,
        normalized_lyrics=normalized_lyrics,
        lyrics_hash=digest,
        parse_status="parsed",
        duplicate_status="duplicate_hash" if duplicate_song else "new",
        possible_duplicate_song_id=duplicate_song.id if duplicate_song else None,
    )
    db.add(staging)
    db.commit()
    db.refresh(staging)
    return ImportResult(status="staged", staging_id=staging.id)


def approve_staging(db: Session, staging_id: int, force: bool = False) -> ImportResult:
    staging = db.get(SongImportStaging, staging_id)
    if not staging:
        return ImportResult(status="not_found", message=f"staging_id={staging_id}")
    if not force and staging.duplicate_status == "duplicate_hash" and staging.possible_duplicate_song_id:
        return ImportResult(
            status="duplicate_needs_review",
            staging_id=staging.id,
            song_id=staging.possible_duplicate_song_id,
        )

    song = Song(
        title=staging.raw_title,
        normalized_title=staging.normalized_title,
        is_verified=False,
    )
    db.add(song)
    db.flush()

    version = SongVersion(
        song_id=song.id,
        version_name="default",
        raw_lyrics=staging.raw_lyrics,
        normalized_lyrics=staging.normalized_lyrics,
        lyrics_hash=staging.lyrics_hash,
        is_default=True,
    )
    db.add(version)
    db.flush()

    for idx, line in enumerate(clean_lines(staging.raw_lyrics), start=1):
        db.add(
            SongLine(
                song_id=song.id,
                version_id=version.id,
                line_order=idx,
                text=line,
                normalized_text=normalize_text(line),
            )
        )

    for idx, slide_text in enumerate(split_lyrics_to_slides(staging.raw_lyrics), start=1):
        db.add(
            SongSlide(
                song_id=song.id,
                version_id=version.id,
                slide_order=idx,
                text=slide_text,
                line_count=len(clean_lines(slide_text)),
            )
        )

    db.add(
        SongSource(
            song_id=song.id,
            source_site=staging.source_site,
            source_url=staging.source_url,
            source_external_id=staging.source_external_id,
        )
    )
    staging.parse_status = "approved"
    db.commit()
    return ImportResult(status="approved", staging_id=staging.id, song_id=song.id)


def mark_staging_duplicate(db: Session, staging_id: int) -> ImportResult:
    staging = db.get(SongImportStaging, staging_id)
    if not staging:
        return ImportResult(status="not_found", message=f"staging_id={staging_id}")
    staging.parse_status = "duplicate"
    db.commit()
    return ImportResult(
        status="marked_duplicate",
        staging_id=staging.id,
        song_id=staging.possible_duplicate_song_id,
    )
