from hashlib import sha256
from io import BytesIO
from urllib.parse import unquote
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.db import models  # noqa: F401 - register all tables with Base.metadata.
from app.db.models import Song, SongPptVersion, SongSource, SongVersion
from app.db.session import Base, get_db
from app.main import app


def _pptx_bytes(marker: str = "slide") -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", f"<presentation>{marker}</presentation>")
    return stream.getvalue()


@pytest.fixture
def pptx_client(tmp_path, monkeypatch):
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

    monkeypatch.setattr(routes, "PPTX_UPLOAD_ROOT", tmp_path / "data" / "pptx")
    monkeypatch.setattr(routes, "PPTX_EXPORT_ROOT", tmp_path / "data" / "exports")
    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client, testing_session, tmp_path
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _create_song(test_client: TestClient, title: str = "測試歌曲") -> int:
    response = test_client.post(
        "/api/songs", json={"title": title, "lyrics": f"{title}第一行\n{title}第二行"}
    )
    assert response.status_code == 201
    return response.json()["song_id"]


def _upload(test_client: TestClient, song_id: int, name: str, action: str, marker: str):
    return test_client.post(
        f"/api/songs/{song_id}/pptx-versions",
        data={"version_name": name, "action": action},
        files={
            "file": (
                f"{marker}.pptx",
                _pptx_bytes(marker),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        },
    )


def test_pptx_upload_ask_overwrite_new_version_and_download(pptx_client):
    test_client, _, _ = pptx_client
    song_id = _create_song(test_client)

    ask = _upload(test_client, song_id, "現場版", "ask", "ask")
    assert ask.status_code == 409
    assert ask.json()["detail"]["code"] == "pptx_version_conflict"
    assert ask.json()["detail"]["has_generated_ppt"] is True
    assert {"code", "message", "existing_versions", "has_generated_ppt"} <= ask.json()[
        "detail"
    ].keys()

    overwritten = _upload(test_client, song_id, "現場版", "overwrite", "overwritten")
    assert overwritten.status_code == 201
    overwritten_version = overwritten.json()["version"]
    assert overwritten_version["is_default"] is True
    assert overwritten_version["overrides_generated"] is True
    assert overwritten_version["file_size"] == len(_pptx_bytes("overwritten"))
    assert overwritten_version["sha256"] == sha256(_pptx_bytes("overwritten")).hexdigest()

    new_version = _upload(test_client, song_id, "投影機版", "new_version", "new")
    assert new_version.status_code == 201
    assert new_version.json()["version"]["is_default"] is False
    assert (
        _upload(test_client, song_id, "投影機版", "new_version", "duplicate").status_code == 409
    )

    downloaded = test_client.get(
        f"/api/songs/{song_id}/pptx-versions/{overwritten_version['version_id']}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == _pptx_bytes("overwritten")
    assert "現場版.pptx" in unquote(downloaded.headers["content-disposition"])

    standard = test_client.get(f"/api/songs/{song_id}/pptx")
    assert standard.status_code == 200
    assert standard.content == _pptx_bytes("overwritten")

    generated = test_client.get(f"/api/songs/{song_id}/pptx?source=generated")
    assert generated.status_code == 200
    assert generated.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert generated.content != standard.content

    listed = test_client.get(f"/api/songs/{song_id}/pptx-versions")
    assert listed.status_code == 200
    assert [item["kind"] for item in listed.json()["items"]] == [
        "generated",
        "uploaded",
        "uploaded",
    ]
    assert listed.json()["items"][0]["download_url"].endswith("?source=generated")
    assert sum(item["is_default"] for item in listed.json()["items"]) == 1


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("not-a-pptx.txt", b"not pptx", "extension"),
        ("broken.pptx", b"not a zip", "valid PPTX ZIP"),
    ],
)
def test_pptx_upload_validates_extension_and_zip(pptx_client, filename, content, expected):
    test_client, _, _ = pptx_client
    song_id = _create_song(test_client)
    response = test_client.post(
        f"/api/songs/{song_id}/pptx-versions",
        data={"version_name": "invalid", "action": "overwrite"},
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 422
    assert expected in response.json()["detail"]


def test_pptx_upload_rejects_size_limit_without_creating_record(pptx_client, monkeypatch):
    test_client, testing_session, _ = pptx_client
    song_id = _create_song(test_client)
    monkeypatch.setattr(routes, "MAX_PPTX_UPLOAD_BYTES", 10)

    response = _upload(test_client, song_id, "太大", "overwrite", "too-large")

    assert response.status_code == 422
    with testing_session() as db:
        assert db.scalar(select(SongPptVersion).where(SongPptVersion.song_id == song_id)) is None


def test_delete_song_requires_password_and_only_removes_target_song(pptx_client):
    test_client, testing_session, tmp_path = pptx_client
    deleted_song_id = _create_song(test_client, "要刪除")
    kept_song_id = _create_song(test_client, "要保留")
    upload = _upload(test_client, deleted_song_id, "自訂", "overwrite", "delete-me")
    assert upload.status_code == 201

    wrong = test_client.request("DELETE", f"/api/songs/{deleted_song_id}", json={"password": "no"})
    assert wrong.status_code == 403
    assert test_client.get(f"/api/songs/{deleted_song_id}").status_code == 200

    with testing_session() as db:
        db.add(SongSource(song_id=deleted_song_id, source_site="test", source_external_id="delete"))
        db.commit()

    deleted = test_client.request(
        "DELETE", f"/api/songs/{deleted_song_id}", json={"password": "go for it"}
    )
    assert deleted.status_code == 200
    assert test_client.get(f"/api/songs/{deleted_song_id}").status_code == 404
    assert test_client.get(f"/api/songs/{kept_song_id}").status_code == 200
    assert not (tmp_path / "data" / "pptx" / str(deleted_song_id)).exists()

    with testing_session() as db:
        assert db.get(Song, deleted_song_id) is None
        assert db.scalar(select(SongVersion).where(SongVersion.song_id == deleted_song_id)) is None
        assert (
            db.scalar(select(SongPptVersion).where(SongPptVersion.song_id == deleted_song_id))
            is None
        )
