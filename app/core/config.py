from functools import lru_cache
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/songs.db")
    crawler_user_agent: str = os.getenv("CRAWLER_USER_AGENT", "SongsDataCrawler/0.1")
    crawler_delay_seconds: float = float(os.getenv("CRAWLER_DELAY_SECONDS", "1.0"))
    crawler_timeout_seconds: float = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
