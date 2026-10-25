"""Production safety regressions without accessing live accounts or databases."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app


class ProductionSafety(unittest.TestCase):
    def test_production_requires_database_url(self):
        with patch.dict(os.environ, {"MARKET_MEMORY_PRODUCTION": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app()

    def test_test_database_remains_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"MARKET_MEMORY_PRODUCTION": "1"}, clear=True):
                application = create_app(db_path=str(Path(folder) / "test.sqlite"))
                with TestClient(application) as client:
                    self.assertEqual(client.get("/health/ready").status_code, 200)

    def test_nonfinite_trade_returns_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(db_path=str(Path(folder) / "test.sqlite"))
            with TestClient(app) as client:
                registration = client.post("/api/register", json={"username": "testuser", "password": "Strong-Password123!"})
                self.assertEqual(registration.status_code, 201, registration.text)
                for value in ("NaN", "Infinity", "-Infinity"):
                    response = client.post("/api/quant/trades", content='{"returns":[' + value + ']}', headers={"content-type": "application/json"})
                    self.assertIn(response.status_code, (400, 422), response.text)

    def test_strict_readiness_rejects_missing_native(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"MARKET_MEMORY_REQUIRE_NATIVE_QUANT": "1"}):
                app = create_app(db_path=str(Path(folder) / "test.sqlite"))
                with patch("app.main.quant_engine_name", return_value="python"):
                    with TestClient(app) as client:
                        response = client.get("/health/ready")
                        self.assertEqual(response.status_code, 503)
