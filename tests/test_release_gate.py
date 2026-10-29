"""The deploy gate must refuse stale revisions and failed C++ CI."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts" / "check-release-gate.py"
spec = importlib.util.spec_from_file_location("deploy_gate", path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class DeployGateTests(unittest.TestCase):
    def test_matching_ci_allows_deploy(self):
        with patch.object(gate, "REPO", "example/repo"), patch.object(gate, "SHA", "a" * 40), patch.object(gate, "TOKEN", "synthetic"):
            with patch.object(gate, "get_json", side_effect=[
                {"sha": "a" * 40},
                {"workflow_runs": [{"head_sha": "a" * 40, "event": "push", "conclusion": "success"}]}
            ]):
                self.assertTrue(gate.gate())

    def test_stale_revision_skips_deploy(self):
        with patch.object(gate, "REPO", "example/repo"), patch.object(gate, "SHA", "a" * 40), patch.object(gate, "TOKEN", "synthetic"):
            with patch.object(gate, "get_json", return_value={"sha": "b" * 40}):
                self.assertFalse(gate.gate())

    def test_failed_native_ci_blocks_deploy(self):
        with patch.object(gate, "REPO", "example/repo"), patch.object(gate, "SHA", "a" * 40), patch.object(gate, "TOKEN", "synthetic"):
            with patch.object(gate, "get_json", side_effect=[
                {"sha": "a" * 40},
                {"workflow_runs": [{"head_sha": "a" * 40, "event": "push", "conclusion": "failure"}]}
            ]):
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    gate.gate()


if __name__ == "__main__":
    unittest.main()
