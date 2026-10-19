"""Small DB-API adapter for the application's fixed parameterized queries.

SQLite is for local development; psycopg uses PostgreSQL in Supabase/Render.
User input is always bound as parameters, never interpolated into SQL.
"""
import re
import sqlite3

import psycopg
from psycopg.rows import dict_row

IntegrityErrors = (sqlite3.IntegrityError, psycopg.IntegrityError)


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row is not None else None

    def fetchall(self):
        return [Row(row) for row in self.cursor.fetchall()]


class PostgresConnection:
    INSERT_ID_TABLES = {"users", "audit_events", "quotes", "snapshots", "visits", "decisions", "alerts", "opportunities", "paper_orders"}

    def __init__(self, url):
        # A trusted CA must verify Supabase's certificate and hostname.
        self.connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=10, sslmode="verify-full", sslrootcert="system")

    def execute(self, sql, parameters=()):
        if sql == "BEGIN IMMEDIATE":
            # Serialize brief evidence/approval writes across all API instances.
            # This replaces SQLite's single-writer transaction semantics.
            cursor = self.connection.execute("SELECT pg_advisory_xact_lock(74001991)")
            return Cursor(cursor)
        ignored = sql.startswith("INSERT OR IGNORE")
        if ignored:
            sql = sql.replace("INSERT OR IGNORE", "INSERT", 1) + " ON CONFLICT DO NOTHING"
        sql = sql.replace("?", "%s")
        match = re.match(r"INSERT INTO (\w+)", sql)
        return_id = match and match.group(1) in self.INSERT_ID_TABLES
        if return_id:
            sql += " RETURNING id"
        cursor = self.connection.execute(sql, parameters)
        inserted = cursor.fetchone() if return_id else None
        return Cursor(cursor, inserted["id"] if inserted else None)

    def executemany(self, sql, parameters):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), parameters)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()

    def initialize(self, schema):
        # Versioned PostgreSQL migration is kept separately from SQLite DDL.
        self.connection.execute("SELECT pg_advisory_xact_lock(74001990)")
        self.connection.execute(schema)
