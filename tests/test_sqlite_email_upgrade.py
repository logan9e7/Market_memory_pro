"""Legacy SQLite data is preserved when adding signup email fields."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app.db_runtime import create_database


class SQLiteUpgradeTests(unittest.TestCase):
    def test_legacy_users_keep_access_and_gain_email_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            with sqlite3.connect(path) as con:
                con.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
                con.execute("INSERT INTO users(username,password_hash) VALUES('legacy-user','existing-hash')")
            db = create_database(Path(folder), db_path=str(path))
            with db() as con:
                row = con.execute("SELECT username,password_hash,email,email_verified FROM users WHERE username='legacy-user'").fetchone()
                self.assertEqual(row["password_hash"], "existing-hash")
                self.assertEqual(row["email_verified"], 1)
                self.assertIsNone(row["email"])
                con.execute("INSERT INTO users(username,password_hash,email,email_verified) VALUES(?,?,?,?)",
                            ("new-user", "hash", "test@example.com", False))
                self.assertEqual(con.execute("SELECT count(*) FROM email_verifications").fetchone()[0], 0)
            with db() as con:
                self.assertEqual(con.execute("SELECT count(*) FROM users").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
