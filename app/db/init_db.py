from app.db import models  # noqa: F401
from app.db.session import Base, engine


def init_db() -> None:
    """Create missing tables without altering existing SQLite tables.

    SongPptVersion is a new table, so this startup-safe initialization is the
    migration for PPT uploads: SQLAlchemy's create_all leaves the existing
    16k+ song tables and rows untouched.
    """

    Base.metadata.create_all(bind=engine)
