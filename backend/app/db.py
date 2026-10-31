from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


FTS_SQL = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
        text, content='segments', content_rowid='id',
        tokenize='unicode61 remove_diacritics 0')""",
    """CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
        INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text); END""",
    """CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
        INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text); END""",
    """CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
        INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
        INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text); END""",
]


# Columns added after the first release: (table, column, SQL type, backfill SQL or None)
MIGRATIONS = [
    ("recordings", "source", "TEXT DEFAULT 'device'",
     "UPDATE recordings SET source = CASE WHEN device_id = 'dashboard' THEN 'dashboard' "
     "WHEN device_id = 'rec-demo' THEN 'import' ELSE 'device' END"),
    ("insights", "topics", "JSON", None),
    ("insights", "keywords", "JSON", None),
    ("pending_actions", "source_ref", "TEXT", None),
    ("calendar_events", "source_ref", "TEXT", None),
    ("email_drafts", "source_ref", "TEXT", None),
]


def _migrate(conn) -> None:
    for table, col, typ, backfill in MIGRATIONS:
        cols = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
        if cols and col not in cols:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            if backfill:
                conn.exec_driver_sql(backfill)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _migrate(conn)
        for stmt in FTS_SQL:
            conn.exec_driver_sql(stmt)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
