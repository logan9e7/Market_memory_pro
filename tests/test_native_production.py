"""Ensure production-required native engine cannot silently fall back."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app
from app.quant_hybrid import engine_name


class NativeProductionTests(unittest.TestCase):
    def test_compiled_native_is_active(self):
        self.assertEqual(engine_name(), "cpp-pybind11")

    def test_health_reports_compiled_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"MARKET_MEMORY_REQUIRE_NATIVE_QUANT": "1"}):
                app = create_app(db_path=str(Path(folder) / "native-health.sqlite"))
            with TestClient(app) as client:
                self.assertEqual(client.get("/health/live").json()["quant_engine"], "cpp-pybind11")
                self.assertEqual(client.get("/health/ready").json()["quant_engine"], "cpp-pybind11")

    def test_missing_native_fails_closed_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"MARKET_MEMORY_REQUIRE_NATIVE_QUANT": "1"}):
                with patch("app.main.quant_engine_name", return_value="python"):
                    with self.assertRaisesRegex(RuntimeError, "Required native"):
                        create_app(db_path=str(Path(folder) / "should-not-start.sqlite"))


if __name__ == "__main__":
    unittest.main()
