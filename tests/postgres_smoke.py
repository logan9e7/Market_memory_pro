"""Run the application regression suite on a disposable TLS PostgreSQL DB.

Requires TEST_DATABASE_URL ending in /mm_test and
MARKET_MEMORY_ALLOW_TEST_RESET=1. Refuses all other database names.
"""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

url = os.environ.get("TEST_DATABASE_URL", "")
if urlsplit(url).path != "/mm_test" or os.environ.get("MARKET_MEMORY_ALLOW_TEST_RESET") != "1":
    raise SystemExit("Requires explicitly authorized disposable database mm_test; no changes made")
os.environ["DATABASE_URL"] = url
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.database import PostgresConnection
from app.main import create_app
from test_workflow import WorkflowTests


class PostgresWorkflowTests(WorkflowTests):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "unused.sqlite3"
        # The verified URL above points only to the disposable test database.
        self.app = create_app()
        con = PostgresConnection(url)
        try:
            con.execute("TRUNCATE users, sessions, auth_attempts, quotes, visits, snapshots, strategies, decisions, alerts, opportunities, paper_orders, audit_events RESTART IDENTITY CASCADE")
            con.commit()
        finally:
            con.close()
        self.client = TestClient(self.app)
        response=self.client.post("/api/register",json={"username":"researcher","password":"Correct-long-password1!"})
        self.assertEqual(response.status_code,201,response.text)

    @contextmanager
    def direct_db(self):
        con=PostgresConnection(url)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def test_migration_ledger_is_repeatable_and_checksum_verified(self):
        from app.migrations import apply_migrations, MigrationError
        con=PostgresConnection(url)
        try:
            root=Path(__file__).resolve().parent.parent / "migrations"
            versions=con.connection.execute(
                "SELECT version FROM mm_schema_migrations ORDER BY version").fetchall()
            self.assertEqual([r["version"] for r in versions],[1,2,3,4])
            ledger=con.connection.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname='mm_schema_migrations'"
            ).fetchone()
            self.assertTrue(ledger["relrowsecurity"])
            self.assertEqual(apply_migrations(con,root,check_only=True),[])
            index_exists=con.connection.execute(
                "SELECT to_regclass('mm_lab_notes_idea_fk') AS name"
            ).fetchone()
            self.assertIsNotNone(index_exists["name"])
            con.commit()
            with tempfile.TemporaryDirectory() as folder:
                for path in root.glob("*.sql"):
                    content=path.read_text()
                    if path.name.startswith("002_"):
                        content += "\\n-- changed checksum\\n"
                    (Path(folder)/path.name).write_text(content)
                with self.assertRaises(MigrationError):
                    apply_migrations(con,folder,check_only=True)
            con.rollback()
        finally:
            con.close()

    def test_public_supabase_roles_cannot_read_application_tables(self):
        import psycopg
        con=PostgresConnection(url)
        try:
            con.connection.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF; END $$")
            con.commit()
            flags=con.connection.execute("SELECT relrowsecurity FROM pg_class WHERE relname IN ('users','sessions','decisions','quotes')").fetchall()
            self.assertEqual(len(flags),4)
            self.assertTrue(all(row["relrowsecurity"] for row in flags))
            con.connection.execute("SET ROLE authenticated")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                con.connection.execute("SELECT * FROM sessions")
            con.rollback()
        finally:
            con.close()


    def test_legacy_partial_schema_migration_preserves_existing_user(self):
        from app.migrations import apply_migrations
        root=Path(__file__).resolve().parent.parent / "migrations"
        con=PostgresConnection(url)
        try:
            # Only the disposable mm_test database; never touch production schemas.
            con.connection.execute("CREATE SCHEMA mm_legacy_upgrade_test")
            con.connection.execute("SET LOCAL search_path TO mm_legacy_upgrade_test")
            con.connection.execute("""
                CREATE TABLE users(
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
            """)
            con.connection.execute(
                "INSERT INTO users(username,password_hash) VALUES(%s,%s)",
                ("existing-user", "preexisting-hash")
            )
            self.assertEqual(apply_migrations(con,root),[1,2,3,4])
            saved=con.connection.execute(
                "SELECT username,password_hash FROM users WHERE username=%s",
                ("existing-user",)
            ).fetchone()
            self.assertEqual(saved["password_hash"],"preexisting-hash")
            self.assertEqual(apply_migrations(con,root,check_only=True),[])
            # Roll back the isolated schema and test user atomically.
            con.rollback()
        finally:
            con.close()

    def test_user_scoped_advisory_locks_allow_independent_writes(self):
        import psycopg
        from app.locking import lock_scopes
        first=PostgresConnection(url)
        second=PostgresConnection(url)
        try:
            lock_scopes(first,"user:60001")
            second.connection.execute("SET LOCAL lock_timeout = '250ms'")
            lock_scopes(second,"user:60002")  # Independent user must not block.
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                lock_scopes(second,"user:60001")  # Same user must serialize.
            second.rollback()
        finally:
            first.rollback()
            first.close()
            second.close()


if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(PostgresWorkflowTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
