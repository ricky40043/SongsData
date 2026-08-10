#!/usr/bin/env python3
"""Back up the SongsData SQLite database and uploaded PPTX files to Google Drive."""

from __future__ import annotations

import fcntl
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
DATABASE = APP_ROOT / "data/songs.db"
UPLOADED_PPTX = APP_ROOT / "data/pptx"
LOCAL_BACKUPS = Path(os.environ.get("SONGSDATA_LOCAL_BACKUPS", "/home/ricky/songsdata-backups/automated"))
LOCK_FILE = LOCAL_BACKUPS.parent / ".cloud-backup.lock"
REMOTE_ROOT = os.environ.get("SONGSDATA_BACKUP_REMOTE", "gdrive:詩歌庫/自動備份").rstrip("/")
KEEP_DAYS = 30
TIMEZONE = ZoneInfo("Asia/Taipei")
DATABASE_RE = re.compile(r"^songsdata_(\d{4}-\d{2}-\d{2})\.db$")
PPT_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})/?$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("songsdata-backup")


def run_rclone(*args: str, capture_output: bool = False) -> str:
    command = [os.environ.get("RCLONE_BIN", "/usr/bin/rclone"), *args]
    LOG.info("執行：rclone %s", " ".join(args))
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
    )
    return result.stdout if capture_output else ""


def create_database_snapshot(destination: Path) -> None:
    if not DATABASE.is_file():
        raise RuntimeError(f"找不到正式資料庫：{DATABASE}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        source = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True, timeout=60)
        target = sqlite3.connect(temp_path)
        try:
            source.backup(target, pages=2048, sleep=0.05)
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError(f"資料庫完整性檢查失敗：{integrity}")
            tables = target.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            songs = target.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            if tables < 5:
                raise RuntimeError(f"資料表數量異常，拒絕上傳：{tables}")
            LOG.info("SQLite 快照完成：%s，資料表 %d，歌曲 %d", destination.name, tables, songs)
        finally:
            target.close()
            source.close()
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def upload_database(snapshot: Path) -> None:
    daily = f"{REMOTE_ROOT}/database/daily/{snapshot.name}"
    latest = f"{REMOTE_ROOT}/database/songsdata_latest.db"
    options = ("--checksum", "--drive-use-trash=true", "--retries=5", "--low-level-retries=10")
    run_rclone("copyto", str(snapshot), daily, *options)
    run_rclone("copyto", str(snapshot), latest, *options)


def upload_uploaded_pptx(today: date) -> None:
    if not UPLOADED_PPTX.is_dir():
        LOG.info("尚無上傳 PPTX 目錄，略過 PPTX 備份：%s", UPLOADED_PPTX)
        return
    daily_remote = f"{REMOTE_ROOT}/pptx/daily/{today.isoformat()}"
    latest_remote = f"{REMOTE_ROOT}/pptx/latest"
    options = (
        "--create-empty-src-dirs",
        "--fast-list",
        "--transfers=8",
        "--checkers=16",
        "--drive-use-trash=true",
        "--retries=5",
        "--low-level-retries=10",
    )
    run_rclone("copy", str(UPLOADED_PPTX), daily_remote, *options)
    run_rclone("sync", str(UPLOADED_PPTX), latest_remote, *options)


def prune_remote_database_backups() -> None:
    remote = f"{REMOTE_ROOT}/database/daily"
    names = sorted(
        name.strip()
        for name in run_rclone("lsf", remote, "--files-only", capture_output=True).splitlines()
        if DATABASE_RE.match(name.strip())
    )
    for old_name in names[:-KEEP_DAYS]:
        LOG.info("刪除 Google Drive 過期資料庫備份：%s", old_name)
        run_rclone("deletefile", f"{remote}/{old_name}", "--drive-use-trash=true")


def prune_remote_pptx_backups() -> None:
    remote = f"{REMOTE_ROOT}/pptx/daily"
    try:
        listing = run_rclone("lsf", remote, "--dirs-only", capture_output=True)
    except subprocess.CalledProcessError as exc:
        # Before the first PPTX upload, the remote directory does not exist.
        # Database backup and the rest of the job should still complete.
        if exc.returncode == 3:
            LOG.info("尚無 Google Drive PPTX 每日備份目錄，略過清理")
            return
        raise
    names = sorted(
        match.group(1)
        for raw in listing.splitlines()
        if (match := PPT_DATE_RE.match(raw.strip()))
    )
    for old_name in names[:-KEEP_DAYS]:
        LOG.info("刪除 Google Drive 過期 PPTX 備份：%s", old_name)
        path = f"{remote}/{old_name}"
        run_rclone("delete", path, "--drive-use-trash=true")
        run_rclone("rmdirs", path, "--leave-root=false")


def write_success_marker(snapshot: Path) -> None:
    content = (
        f"last_success={datetime.now(TIMEZONE).isoformat()}\n"
        f"database={snapshot.name}\n"
        f"database_size={snapshot.stat().st_size}\n"
        f"pptx_source={UPLOADED_PPTX}\n"
        f"retention_days={KEEP_DAYS}\n"
    )
    fd, temp_name = tempfile.mkstemp(prefix="songsdata-backup-status-", text=True)
    os.close(fd)
    status_path = Path(temp_name)
    try:
        status_path.write_text(content, encoding="utf-8")
        run_rclone("copyto", str(status_path), f"{REMOTE_ROOT}/last-success.txt", "--drive-use-trash=true")
    finally:
        status_path.unlink(missing_ok=True)


def main() -> int:
    LOCAL_BACKUPS.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.error("已有另一個 SongsData 備份程序正在執行")
            return 2

        today = datetime.now(TIMEZONE).date()
        snapshot = LOCAL_BACKUPS / f"songsdata_{today.isoformat()}.db"
        create_database_snapshot(snapshot)
        upload_database(snapshot)
        upload_uploaded_pptx(today)
        prune_remote_database_backups()
        prune_remote_pptx_backups()
        write_success_marker(snapshot)
    LOG.info("SongsData Google Drive 備份全部完成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        LOG.exception("rclone 執行失敗，結束碼：%s", error.returncode)
        sys.exit(error.returncode or 1)
    except Exception:
        LOG.exception("SongsData 備份失敗")
        sys.exit(1)
