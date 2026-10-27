"""Regression test for case-insensitive HTTP headers in production probe."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts" / "verify-production.py"
spec = importlib.util.spec_from_file_location("production_probe", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ProductionProbeTests(unittest.TestCase):
    def test_lowercase_reverse_proxy_headers_are_accepted(self):
        responses = {
            "/health/live": (200, {}, json.dumps({"status":"alive","revision":"abc123",
                "quant_engine":"cpp-pybind11"}).encode()),
            "/health/ready": (200, {}, json.dumps({"status":"ready","revision":"abc123",
                "database":"reachable","execution_mode":"paper",
                "quant_engine":"cpp-pybind11"}).encode()),
            "/": (200, {"x-frame-options":"DENY",
                "content-security-policy":"default-src 'self'; frame-ancestors 'none'"},
                b"MARKET MEMORY PRO"),
            "/static/app.js": (200, {}, b"x"*101),
            "/static/style.css": (200, {}, b"x"*101),
            "/api/state": (401, {"cache-control":"no-store"}, b"{}"),
        }
        with patch.object(probe, "request", side_effect=lambda path: responses[path]):
            probe.verify()

if __name__ == "__main__":
    unittest.main()
