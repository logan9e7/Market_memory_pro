"""Backup refuses insecure connections and missing encryption configuration."""
import os
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-production.sh"


class BackupSafetyTests(unittest.TestCase):
    def run_backup(self, **overrides):
        env = {**os.environ,
            "DATABASE_URL": "postgresql://user:dummy@localhost:5432/mm_test",
            "DATABASE_SSL_ROOT_CERT": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
            "BACKUP_AGE_RECIPIENT": "age1testrecipient",
        }
        env.update(overrides)
        return subprocess.run(["bash", str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=10)

    def test_insecure_ssl_url_refused_before_dump(self):
        result = self.run_backup(DATABASE_URL="postgresql://user@localhost/mm_test?sslmode=disable")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verify-full", result.stderr)

    def test_missing_age_recipient_refused_before_dump(self):
        result = self.run_backup(BACKUP_AGE_RECIPIENT="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BACKUP_AGE_RECIPIENT", result.stderr)

    def test_url_cannot_override_ca_path(self):
        result = self.run_backup(DATABASE_URL="postgresql://user@localhost/mm_test?sslrootcert=/tmp/fake")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sslrootcert", result.stderr)


if __name__ == "__main__":
    unittest.main()
