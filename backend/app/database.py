from typing import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import settings

is_sqlite = settings.database_url.startswith("sqlite")

connect_args = {"check_same_thread": False, "timeout": 60} if is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-64000")  # ~64MB cache in RAM
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_fts5_index() -> None:
    """Inizializza l'indice Full-Text Search (FTS5) su SQLite per ricerche <5ms su nome, tipo e testo regole."""
    if not is_sqlite:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                    oracle_id UNINDEXED,
                    name,
                    type_line,
                    oracle_text,
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
        )
