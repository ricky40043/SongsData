from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 - register all tables with Base.metadata.
from app.db.models import Song, SongLine, SongSlide, SongVersion
from app.db.session import Base, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, testing_session
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_create_song_builds_song_version_lines_and_slides(client):
    test_client, testing_session = client
    response = test_client.post(
        "/api/songs",
        json={
            "title": "恩典之路",
            "lyrics": "祢的恩典夠我用\n祢的恩典永不止息",
            "album": "敬拜專輯",
            "author": "作者",
            "composer": "作曲者",
            "copyright_note": "版權備註",
        },
    )

    assert response.status_code == 201
    song_id = response.json()["song_id"]
    with testing_session() as db:
        song = db.get(Song, song_id)
        version = db.scalar(select(SongVersion).where(SongVersion.song_id == song_id))
        assert song is not None
        assert song.album == "敬拜專輯"
        assert song.author == "作者"
        assert song.composer == "作曲者"
        assert song.copyright_note == "版權備註"
        assert version is not None
        assert db.scalar(select(func.count()).select_from(SongLine).where(SongLine.song_id == song_id)) == 2
        assert db.scalar(select(func.count()).select_from(SongSlide).where(SongSlide.song_id == song_id)) == 1


def test_create_song_rejects_duplicate_lyrics_hash_with_existing_song_id(client):
    test_client, _ = client
    first = test_client.post(
        "/api/songs",
        json={"title": "第一首", "lyrics": "恩典，充滿我\n永不止息"},
    )
    existing_song_id = first.json()["song_id"]

    duplicate = test_client.post(
        "/api/songs",
        json={"title": "另一個歌名", "lyrics": "恩典充滿我\n永不止息"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {
        "code": "duplicate_song",
        "message": "A song with the same lyrics already exists.",
        "duplicate_field": "lyrics_hash",
        "song_id": existing_song_id,
    }


def test_create_song_rejects_duplicate_normalized_title(client):
    test_client, _ = client
    first = test_client.post(
        "/api/songs",
        json={"title": "主，愛我", "lyrics": "第一段歌詞"},
    )
    existing_song_id = first.json()["song_id"]

    duplicate = test_client.post(
        "/api/songs",
        json={"title": "主愛我", "lyrics": "不同的歌詞"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["duplicate_field"] == "title"
    assert duplicate.json()["detail"]["song_id"] == existing_song_id


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   ", "lyrics": "有效歌詞"},
        {"title": "有效歌名", "lyrics": "\n\t  "},
    ],
)
def test_create_song_rejects_blank_required_values(client, payload):
    test_client, _ = client

    response = test_client.post("/api/songs", json=payload)

    assert response.status_code == 422


def test_new_song_frontend_is_wired_to_create_api():
    root = Path(__file__).parents[1]
    html = (root / "app/static/index.html").read_text()
    javascript = (root / "app/static/app.js").read_text()

    assert 'id="newSongForm"' in html
    assert 'id="newSongTitle"' in html
    assert 'id="newSongLyrics"' in html
    assert 'id="pptUploadForm"' in html
    assert 'id="pptVersionName"' in html
    assert 'id="deleteSongBtn"' in html
    assert 'id="customPptBtn"' in html
    assert 'id="customPptModal"' in html
    assert 'id="togglePptUploadBtn"' in html
    assert "系統自動產生 PPT" in html
    assert 'fetchJson("/api/songs"' in javascript
    assert 'method: "POST"' in javascript
    assert 'pptx-versions' in javascript
    assert 'method: "DELETE"' in javascript
