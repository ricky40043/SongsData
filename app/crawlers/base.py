from dataclasses import dataclass


@dataclass(frozen=True)
class CrawlSongDetail:
    source_site: str
    source_url: str
    source_external_id: str
    title: str
    lyrics: str
    album: str | None = None
