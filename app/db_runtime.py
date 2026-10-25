"""Application database connection lifecycle with rollback semantics."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.database import PostgresConnection
from app.migrations import apply_migrations
from app.schema import SCHEMA

def create_database(root, db_path=None):
    postgres_url = os.getenv("DATABASE_URL") if db_path is None else None
    database = Path(db_path or os.getenv("MARKET_MEMORY_DB", str(root / ".data" / "memory.sqlite3")))
    if not postgres_url and db_path is None and os.getenv("MARKET_MEMORY_PRODUCTION") == "1":
        raise RuntimeError("Production cannot use an ephemeral SQLite database")
    if not postgres_url:
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def db():
        if postgres_url:
            con = PostgresConnection(postgres_url)
        else:
            con = sqlite3.connect(database, timeout=10)
            database.chmod(0o600)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    with db() as con:
        if postgres_url:
            # Backwards-compatible for Render services that still use the old start command.
            # Only pending, checksum-verified migrations execute; no repeated schema DDL.
            check_only = os.getenv("MARKET_MEMORY_MIGRATIONS_AT_STARTUP", "1") != "1"
            apply_migrations(con, root / "migrations", check_only=check_only)
        else:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    return db
