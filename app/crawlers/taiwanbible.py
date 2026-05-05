import re

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.crawlers.base import CrawlSongDetail


class TaiwanBibleCrawler:
    source_site = "TaiwanBible"
    base_url = "https://www.taiwanbible.com/web/lyrics/view.jsp?ID={song_id}"

    def __init__(self) -> None:
        settings = get_settings()
        self.headers = {"User-Agent": settings.crawler_user_agent}
        self.timeout = settings.crawler_timeout_seconds

    def build_url(self, song_id: int) -> str:
        return self.base_url.format(song_id=song_id)

    async def fetch_detail(self, song_id: int) -> CrawlSongDetail | None:
        url = self.build_url(song_id)
        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        return self.parse_detail(response.text, url, str(song_id))

    def parse_detail(self, html: str, source_url: str, source_external_id: str) -> CrawlSongDetail | None:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n")
        raw_lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in raw_lines if line]

        id_marker = f"本詩歌資料庫編號: {source_external_id}"
        if id_marker not in lines:
            return None

        try:
            start = lines.index("詩歌園地")
        except ValueError:
            start = 0

        content = lines[start + 1 :]
        content = self._drop_until_after(content, {"專輯列表", "我的詩歌本", "新增詩歌", "搜尋詩歌"})

        title = self._first_content_line(content)
        if not title:
            return None

        album = None
        lyric_lines: list[str] = []
        after_title = False
        for line in content:
            if not after_title:
                after_title = line == title
                continue
            if line.startswith("專輯:"):
                album = line.replace("專輯:", "", 1).strip() or None
                continue
            if line in {"MIDI 下載", "加到我的詩歌本", "EMAIL歌詞", "製作投影片"}:
                continue
            if line.startswith("本詩歌資料庫編號:") or line.startswith("請注意!"):
                break
            if self._is_noise(line):
                continue
            lyric_lines.append(line)

        lyrics = "\n".join(lyric_lines).strip()
        if not lyrics:
            return None

        return CrawlSongDetail(
            source_site=self.source_site,
            source_url=source_url,
            source_external_id=source_external_id,
            title=title,
            lyrics=lyrics,
            album=album,
        )

    def _drop_until_after(self, lines: list[str], markers: set[str]) -> list[str]:
        last_marker_idx = -1
        for idx, line in enumerate(lines[:20]):
            if line in markers:
                last_marker_idx = idx
        return lines[last_marker_idx + 1 :] if last_marker_idx >= 0 else lines

    def _first_content_line(self, lines: list[str]) -> str | None:
        for line in lines:
            if not self._is_noise(line) and not line.startswith("專輯:"):
                return line
        return None

    def _is_noise(self, line: str) -> bool:
        if re.fullmatch(r"\[[^\]]+\]", line):
            return True
        return line in {"Image", "詩歌園地", "專輯列表", "我的詩歌本", "新增詩歌", "搜尋詩歌"}
