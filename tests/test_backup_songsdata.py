import sqlite3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts/backup_songsdata.py"
SPEC = spec_from_file_location("backup_songsdata", MODULE_PATH)
backup_songsdata = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backup_songsdata)


def test_create_database_snapshot_uses_consistent_sqlite_copy(tmp_path, monkeypatch):
    source = tmp_path / "songs.db"
    connection = sqlite3.connect(source)
    connection.executescript(
        """
        CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
        CREATE TABLE song_versions (id INTEGER PRIMARY KEY, song_id INTEGER);
        CREATE TABLE song_lines (id INTEGER PRIMARY KEY, song_id INTEGER);
        CREATE TABLE song_slides (id INTEGER PRIMARY KEY, song_id INTEGER);
        CREATE TABLE song_sources (id INTEGER PRIMARY KEY, song_id INTEGER);
        INSERT INTO songs (title) VALUES ('測試詩歌');
        """
    )
    connection.commit()
    connection.close()
    destination = tmp_path / "backup.db"
    monkeypatch.setattr(backup_songsdata, "DATABASE", source)

    backup_songsdata.create_database_snapshot(destination)

    copied = sqlite3.connect(destination)
    assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert copied.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1
    copied.close()


def test_database_pruning_keeps_latest_30(monkeypatch):
    calls = []
    names = "\n".join(f"songsdata_2026-01-{day:02d}.db" for day in range(1, 32))
    monkeypatch.setattr(backup_songsdata, "run_rclone", lambda *args, **kwargs: calls.append(args) or names)

    backup_songsdata.prune_remote_database_backups()

    deleted = [call[1] for call in calls if call[0] == "deletefile"]
    assert deleted == [f"gdrive:詩歌庫/自動備份/database/daily/songsdata_2026-01-{day:02d}.db" for day in (1,)]
