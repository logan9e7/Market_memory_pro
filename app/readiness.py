"""Read-only readiness gate: database connectivity AND migration integrity.

The liveness probe must not depend on PostgreSQL. Readiness refuses stale or
checksum-mismatched schemas so that a web process cannot accept new traffic
against an incompatible database. No schema DDL is performed here.
"""
from app.migrations import apply_migrations


def verify_database_readiness(con, migrations_directory, postgres=False):
    con.execute("SELECT 1 FROM users LIMIT 1").fetchall()
    if postgres:
        apply_migrations(con, migrations_directory, check_only=True)
