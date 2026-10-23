"""Transaction-scoped concurrency control without a global writer bottleneck.

SQLite retains BEGIN IMMEDIATE's single-writer semantics.
PostgreSQL locks a deterministic, namespaced 64-bit key per account or
authentication budget, allowing independent users to write concurrently.
All callers must acquire their required scopes before querying or writing.
"""
import sqlite3
from app.database import PostgresConnection


def lock_scopes(con, *scopes):
    keys = sorted(set(scopes))
    if not keys or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("At least one nonempty lock scope is required")
    if isinstance(con, PostgresConnection):
        for key in keys:
            con.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(?::text, 74001991))",
                ("mm:" + key,),
            )
    elif isinstance(con, sqlite3.Connection):
        con.execute("BEGIN IMMEDIATE")
    else:
        raise TypeError("Unsupported database connection for scoped locks")
