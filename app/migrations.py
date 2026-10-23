"""Transactional, checksum-verified PostgreSQL migration runner.

Never resets or deletes trading data. Re-applies no successfully recorded migration.
Legacy installations without a ledger bootstrap by replaying the idempotent 001
migration once, then record all versions atomically.
"""
import hashlib
import os
import re
from pathlib import Path

from app.database import PostgresConnection

FILE_PATTERN = re.compile(r"^(?P<version>[0-9]{3})_[a-z][a-z0-9_]*\.sql$")
MIGRATION_LOCK = 74001990


class MigrationError(RuntimeError):
    pass


def discover(directory):
    root = Path(directory)
    migrations = []
    versions = set()
    for path in sorted(root.glob("*.sql")):
        match = FILE_PATTERN.fullmatch(path.name)
        if not match:
            raise MigrationError("Invalid migration filename: " + path.name)
        version = int(match.group("version"))
        if version in versions:
            raise MigrationError("Duplicate migration version: " + str(version))
        versions.add(version)
        raw = path.read_bytes()
        migrations.append((version, path.name, hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")))
    if not migrations:
        raise MigrationError("No PostgreSQL migration files available")
    return migrations


def apply_migrations(con, directory, check_only=False):
    """Call inside a transaction. The caller commits or rolls back."""
    con.connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
    scripts = discover(directory)
    table = con.connection.execute("SELECT to_regclass('mm_schema_migrations') AS name").fetchone()
    if table["name"] is None:
        if check_only:
            raise MigrationError("Migration ledger missing; apply migrations before startup")
        con.connection.execute("""
            CREATE TABLE mm_schema_migrations(
              version INTEGER PRIMARY KEY,
              filename TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    installed = {
        row["version"]: row
        for row in con.connection.execute(
            "SELECT version, filename, sha256 FROM mm_schema_migrations ORDER BY version"
        ).fetchall()
    }
    known = {version for version, _, _, _ in scripts}
    if any(version not in known for version in installed):
        raise MigrationError("Database has unknown migration versions; refusing to proceed")
    new_versions = []
    for version, filename, digest, sql in scripts:
        previous = installed.get(version)
        if previous:
            if previous["sha256"] != digest or previous["filename"] != filename:
                raise MigrationError("Migration checksum changed: " + filename)
            continue
        if check_only:
            raise MigrationError("Pending PostgreSQL migration: " + filename)
        con.connection.execute(sql)
        con.connection.execute(
            "INSERT INTO mm_schema_migrations(version,filename,sha256) VALUES(%s,%s,%s)",
            (version, filename, digest),
        )
        new_versions.append(version)
    return new_versions


def run_cli():
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    if action not in {"apply", "check"}:
        raise SystemExit("Usage: python -m app.migrations [check|apply]")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL must be set; no changes made")
    con = PostgresConnection(url)
    try:
        applied = apply_migrations(
            con, Path(__file__).resolve().parent.parent / "migrations",
            check_only=(action == "check"),
        )
        con.commit()
        print("Database migrations verified" if action == "check" else
              "Database migrations applied: " + (", ".join(map(str, applied)) or "none"))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    run_cli()
