"""Operational middleware and trust-store configuration regression tests."""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.database import PostgresConnection
from app.main import create_app


class OperationsTests(unittest.TestCase):
    def test_observability_and_liveness(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(db_path=str(Path(folder) / "data.db"))) as client:
                response = client.get("/health/live")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "alive")
                self.assertEqual(len(response.headers["X-Request-ID"]), 32)
                unauthorized = client.get("/api/state")
                self.assertEqual(unauthorized.status_code, 401)
                self.assertNotEqual(response.headers["X-Request-ID"], unauthorized.headers["X-Request-ID"])
                self.assertEqual(client.get("/health/ready").status_code, 200)

    def test_custom_pg_ssl_root_is_always_verify_full(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "db.crt"
            root.write_text("unit-test-only")
            with patch.dict("os.environ", {"PGSSLROOTCERT": str(root), "DATABASE_SSL_ROOT_CERT": ""}):
                with patch("app.database.psycopg.connect") as connect:
                    PostgresConnection("postgresql://ignored.invalid/demo")
                    self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
                    self.assertEqual(connect.call_args.kwargs["sslrootcert"], str(root))

    def test_missing_pg_ssl_root_fails_closed(self):
        with patch.dict("os.environ", {"PGSSLROOTCERT": "/nonexistent/mm-ca.pem", "DATABASE_SSL_ROOT_CERT": ""}):
            with self.assertRaisesRegex(ValueError, "PGSSLROOTCERT"):
                PostgresConnection("postgresql://ignored.invalid/demo")


if __name__ == "__main__":
    unittest.main()
