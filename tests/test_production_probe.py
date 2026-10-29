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
                "database":"reachable","schema":"current","execution_mode":"paper",
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

    def test_revision_wait_retries_only_stale_deploy(self):
        with patch.object(probe, "EXPECTED_REVISION", "abc123"):
            with patch.dict("os.environ", {"WAIT_FOR_REVISION_SECONDS": "60"}):
                with patch.object(probe, "verify", side_effect=[
                    AssertionError("Unexpected deployed commit"), None]) as verify:
                    with patch.object(probe.time, "sleep") as sleep:
                        probe.verify_with_revision_wait()
                    self.assertEqual(verify.call_count, 2)
                    sleep.assert_called_once()

    def test_revision_wait_does_not_mask_other_failures(self):
        with patch.object(probe, "EXPECTED_REVISION", "abc123"):
            with patch.dict("os.environ", {"WAIT_FOR_REVISION_SECONDS": "60"}):
                with patch.object(probe, "verify", side_effect=AssertionError("Private API exposed")):
                    with self.assertRaisesRegex(AssertionError, "Private API exposed"):
                        probe.verify_with_revision_wait()

if __name__ == "__main__":
    unittest.main()
