from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Song, SongLine
from app.services.normalizer import normalize_text


def search_songs(db: Session, keyword: str, limit: int = 20) -> list[dict]:
    normalized = normalize_text(keyword)
    if not normalized:
        return []

    rows = db.execute(
        select(Song, SongLine)
        .join(SongLine, SongLine.song_id == Song.id)
        .where(
            or_(
                Song.normalized_title.contains(normalized),
                SongLine.normalized_text.contains(normalized),
            )
        )
        .limit(limit * 4)
    ).all()

    ranked = []
    seen: set[int] = set()
    for song, line in rows:
        if song.id in seen:
            continue
        seen.add(song.id)
        line_score = fuzz.partial_ratio(normalized, line.normalized_text)
        title_score = fuzz.partial_ratio(normalized, song.normalized_title)
        ranked.append(
            {
                "song_id": song.id,
                "title": song.title,
                "matched_line": line.text,
                "score": round(max(line_score, title_score), 2),
                "is_verified": song.is_verified,
            }
        )

    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]
