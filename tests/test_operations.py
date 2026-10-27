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

    def test_production_rejects_sqlite_without_database_url(self):
        with patch.dict("os.environ", {"MARKET_MEMORY_PRODUCTION":"1","DATABASE_URL":"","MARKET_MEMORY_REQUIRE_NATIVE_QUANT":"0"}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app()

    def test_required_native_quant_fails_closed(self):
        with patch.dict("os.environ", {"MARKET_MEMORY_REQUIRE_NATIVE_QUANT":"1"}):
            with patch("app.main.quant_engine_name", return_value="python"):
                with self.assertRaisesRegex(RuntimeError, "native C"):
                    create_app()

    def test_security_headers_and_private_state(self):
        with tempfile.TemporaryDirectory() as folder:
            with TestClient(create_app(db_path=str(Path(folder) / "secure.sqlite3"))) as client:
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                private = client.get("/api/state")
                self.assertEqual(private.status_code, 401)
                self.assertEqual(private.headers["Cache-Control"], "no-store")
                cross_origin = client.post("/api/register", json={"username":"untrusted","password":"Password!12345"},headers={"Origin":"https://evil.invalid"})
                self.assertEqual(cross_origin.status_code, 403)

    def test_missing_pg_ssl_root_fails_closed(self):
        with patch.dict("os.environ", {"PGSSLROOTCERT": "/nonexistent/mm-ca.pem", "DATABASE_SSL_ROOT_CERT": ""}):
            with self.assertRaisesRegex(ValueError, "PGSSLROOTCERT"):
                PostgresConnection("postgresql://ignored.invalid/demo")


if __name__ == "__main__":
    unittest.main()
