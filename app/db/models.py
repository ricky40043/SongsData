from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    album: Mapped[str | None] = mapped_column(String(300), nullable=True)
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    composer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    copyright_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    versions: Mapped[list["SongVersion"]] = relationship(back_populates="song")


class SongVersion(Base):
    __tablename__ = "song_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id"), index=True)
    version_name: Mapped[str] = mapped_column(String(100), default="default")
    raw_lyrics: Mapped[str] = mapped_column(Text)
    normalized_lyrics: Mapped[str] = mapped_column(Text, index=True)
    lyrics_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    song: Mapped[Song] = relationship(back_populates="versions")


class SongLine(Base):
    __tablename__ = "song_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("song_versions.id"), index=True)
    line_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(500))
    normalized_text: Mapped[str] = mapped_column(String(500), index=True)


class SongSlide(Base):
    __tablename__ = "song_slides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("song_versions.id"), index=True)
    slide_order: Mapped[int] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SongSource(Base):
    __tablename__ = "song_sources"
    __table_args__ = (
        UniqueConstraint("source_site", "source_external_id", name="uq_source_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id"), index=True)
    source_site: Mapped[str] = mapped_column(String(100), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SongImportStaging(Base):
    __tablename__ = "song_import_staging"
    __table_args__ = (
        UniqueConstraint("source_site", "source_external_id", name="uq_staging_source_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_site: Mapped[str] = mapped_column(String(100), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    raw_title: Mapped[str] = mapped_column(String(300))
    raw_lyrics: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    normalized_lyrics: Mapped[str] = mapped_column(Text)
    lyrics_hash: Mapped[str] = mapped_column(String(64), index=True)
    parse_status: Mapped[str] = mapped_column(String(50), default="parsed", index=True)
    duplicate_status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    possible_duplicate_song_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
