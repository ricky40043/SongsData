import asyncio
from pathlib import Path

import typer
from sqlalchemy import func, select

from app.core.config import get_settings
from app.crawlers.taiwanbible import TaiwanBibleCrawler
from app.db.init_db import init_db
from app.db.models import Song, SongImportStaging, SongSource
from app.db.session import SessionLocal
from app.services.importer import approve_staging, stage_song
from app.services.ppt import generate_song_pptx, song_pptx_filename
from app.services.search import search_songs

app = typer.Typer(no_args_is_help=True)


@app.command()
def init() -> None:
    """Create database tables."""
    init_db()
    typer.echo("Database initialized.")


@app.command("crawl-taiwanbible")
def crawl_taiwanbible(
    start_id: int = typer.Option(1, help="First TaiwanBible lyrics ID."),
    end_id: int = typer.Option(20000, help="Last TaiwanBible lyrics ID."),
    auto_approve: bool = typer.Option(False, help="Approve non-duplicate staged songs into canonical tables."),
    delay: float | None = typer.Option(None, help="Delay seconds between requests."),
    stop_after_success: int | None = typer.Option(None, help="Stop after this many successful staged/approved imports."),
    skip_known: bool = typer.Option(True, help="Skip IDs already present in staging or sources before HTTP fetch."),
    concurrency: int = typer.Option(1, help="Number of concurrent HTTP fetch workers."),
) -> None:
    """Crawl TaiwanBible lyrics by numeric ID into staging, optionally approving new songs."""
    asyncio.run(
        _crawl_taiwanbible(
            start_id, end_id, auto_approve, delay, stop_after_success, skip_known, concurrency
        )
    )


@app.command("crawl-taiwanbible-all")
def crawl_taiwanbible_all(
    start_id: int = typer.Option(1, help="First TaiwanBible lyrics ID."),
    max_id: int = typer.Option(
        30000,
        help="Upper scan bound. TaiwanBible currently reports about 19k songs, but IDs are not guaranteed to equal count.",
    ),
    delay: float | None = typer.Option(None, help="Delay seconds between requests."),
    concurrency: int = typer.Option(1, help="Number of concurrent HTTP fetch workers."),
    auto_approve: bool = typer.Option(True, help="Approve non-duplicate staged songs into canonical tables."),
    stop_after_success: int | None = typer.Option(None, help="Smoke-test option: stop after N successful imports."),
) -> None:
    """Crawl the whole TaiwanBible lyrics site by scanning its numeric song IDs."""
    asyncio.run(
        _crawl_taiwanbible(
            start_id, max_id, auto_approve, delay, stop_after_success, True, concurrency
        )
    )


async def _crawl_taiwanbible(
    start_id: int,
    end_id: int,
    auto_approve: bool,
    delay: float | None,
    stop_after_success: int | None,
    skip_known: bool,
    concurrency: int,
) -> None:
    init_db()
    settings = get_settings()
    request_delay = settings.crawler_delay_seconds if delay is None else delay
    concurrency = max(1, concurrency)
    if concurrency > 1:
        await _crawl_taiwanbible_concurrent(
            start_id=start_id,
            end_id=end_id,
            auto_approve=auto_approve,
            request_delay=request_delay,
            stop_after_success=stop_after_success,
            skip_known=skip_known,
            concurrency=concurrency,
        )
        return

    crawler = TaiwanBibleCrawler()
    success_count = 0
    skipped_count = 0
    error_count = 0

    with SessionLocal() as db:
        for song_id in range(start_id, end_id + 1):
            external_id = str(song_id)
            try:
                if skip_known and _taiwanbible_id_exists(db, external_id):
                    skipped_count += 1
                    typer.echo(f"[{song_id}] skipped_known")
                    continue

                detail = await crawler.fetch_detail(song_id)
                if not detail:
                    skipped_count += 1
                    typer.echo(f"[{song_id}] no song")
                else:
                    result = stage_song(db, detail)
                    final_status = result.status
                    if auto_approve and result.status == "staged" and result.staging_id:
                        approved = approve_staging(db, result.staging_id)
                        final_status = approved.status
                    if final_status in {"staged", "approved"}:
                        success_count += 1
                    typer.echo(f"[{song_id}] {final_status}: {detail.title}")
            except Exception as exc:  # noqa: BLE001 - CLI should keep long crawls alive.
                db.rollback()
                error_count += 1
                typer.echo(f"[{song_id}] error: {exc}")

            if stop_after_success and success_count >= stop_after_success:
                break
            await asyncio.sleep(request_delay)

    typer.echo(
        f"Done. success={success_count} skipped={skipped_count} errors={error_count} "
        f"range={start_id}-{end_id}"
    )


async def _crawl_taiwanbible_concurrent(
    start_id: int,
    end_id: int,
    auto_approve: bool,
    request_delay: float,
    stop_after_success: int | None,
    skip_known: bool,
    concurrency: int,
) -> None:
    queue: asyncio.Queue[int | None] = asyncio.Queue()
    counters = {"success": 0, "skipped": 0, "errors": 0}
    stop_event = asyncio.Event()
    write_lock = asyncio.Lock()

    for song_id in range(start_id, end_id + 1):
        queue.put_nowait(song_id)
    for _ in range(concurrency):
        queue.put_nowait(None)

    async def worker(worker_id: int) -> None:
        crawler = TaiwanBibleCrawler()
        while True:
            song_id = await queue.get()
            if song_id is None:
                queue.task_done()
                break
            if stop_event.is_set():
                queue.task_done()
                continue

            external_id = str(song_id)
            try:
                with SessionLocal() as db:
                    if skip_known and _taiwanbible_id_exists(db, external_id):
                        counters["skipped"] += 1
                        typer.echo(f"[{song_id}] skipped_known")
                        continue

                detail = await crawler.fetch_detail(song_id)
                async with write_lock:
                    with SessionLocal() as db:
                        if not detail:
                            counters["skipped"] += 1
                            typer.echo(f"[{song_id}] no song")
                        else:
                            result = stage_song(db, detail)
                            final_status = result.status
                            if auto_approve and result.status == "staged" and result.staging_id:
                                approved = approve_staging(db, result.staging_id)
                                final_status = approved.status
                            if final_status in {"staged", "approved"}:
                                counters["success"] += 1
                            typer.echo(f"[{song_id}] {final_status}: {detail.title}")
                            if (
                                stop_after_success
                                and counters["success"] >= stop_after_success
                            ):
                                stop_event.set()
            except Exception as exc:  # noqa: BLE001 - CLI should keep long crawls alive.
                counters["errors"] += 1
                typer.echo(f"[{song_id}] error: {exc}")
            finally:
                queue.task_done()
                await asyncio.sleep(request_delay)

    workers = [asyncio.create_task(worker(worker_id)) for worker_id in range(1, concurrency + 1)]
    await queue.join()
    await asyncio.gather(*workers)
    typer.echo(
        f"Done. success={counters['success']} skipped={counters['skipped']} "
        f"errors={counters['errors']} range={start_id}-{end_id} concurrency={concurrency}"
    )


def _taiwanbible_id_exists(db, external_id: str) -> bool:
    source_exists = db.scalar(
        select(SongSource.id).where(
            SongSource.source_site == TaiwanBibleCrawler.source_site,
            SongSource.source_external_id == external_id,
        )
    )
    if source_exists:
        return True

    staging_exists = db.scalar(
        select(SongImportStaging.id).where(
            SongImportStaging.source_site == TaiwanBibleCrawler.source_site,
            SongImportStaging.source_external_id == external_id,
        )
    )
    return bool(staging_exists)


@app.command("approve-pending")
def approve_pending(limit: int = typer.Option(100, help="Maximum staging rows to approve.")) -> None:
    init_db()
    approved_count = 0
    with SessionLocal() as db:
        staging_ids = db.scalars(
            select(SongImportStaging.id)
            .where(
                SongImportStaging.parse_status == "parsed",
                SongImportStaging.duplicate_status == "new",
            )
            .order_by(SongImportStaging.id)
            .limit(limit)
        ).all()
        for staging_id in staging_ids:
            result = approve_staging(db, staging_id)
            if result.status == "approved":
                approved_count += 1
                typer.echo(f"approved staging={staging_id} song={result.song_id}")
    typer.echo(f"Approved {approved_count} import(s).")


@app.command()
def stats() -> None:
    init_db()
    with SessionLocal() as db:
        songs = db.scalar(select(func.count()).select_from(Song))
        staging = db.scalar(select(func.count()).select_from(SongImportStaging))
    typer.echo(f"songs={songs} staging={staging}")


@app.command()
def search(keyword: str, limit: int = 10) -> None:
    init_db()
    with SessionLocal() as db:
        for item in search_songs(db, keyword, limit):
            typer.echo(
                f"{item['score']:>5} song_id={item['song_id']} "
                f"title={item['title']} line={item['matched_line']}"
            )


@app.command("make-pptx")
def make_pptx(song_id: int, output: Path | None = None) -> None:
    init_db()
    with SessionLocal() as db:
        song = db.get(Song, song_id)
        if not song:
            typer.echo(f"Song not found: {song_id}")
            raise typer.Exit(code=1)
        if output is None:
            output = Path("data/exports") / song_pptx_filename(song.title, song.id)
        path = generate_song_pptx(db, song_id, output)
    typer.echo(f"Wrote {path}")
