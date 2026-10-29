"""Registration email verification: delivery, replay, expiry and resend controls."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app


class EmailVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "email.sqlite3"
        self.client = TestClient(create_app(db_path=str(self.path)))
        self.environment = patch.dict(os.environ, {"MARKET_MEMORY_EMAIL_VERIFICATION_REQUIRED": "1"})
        self.environment.start()
        self.ready = patch("app.api_auth.delivery_ready", return_value=True)
        self.ready.start()
        self.tokens = []
        self.sender = patch("app.api_auth.send_verification_email",
                            side_effect=lambda email, token: self.tokens.append((email, token)))
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.ready.stop()
        self.environment.stop()
        self.client.close()
        self.directory.cleanup()

    def register(self, username="newresearcher", email="researcher@example.com"):
        return self.client.post("/api/register", json={
            "username": username, "email": email, "password": "Correct-Password123!"
        })

    def login(self, username="newresearcher"):
        return self.client.post("/api/login", json={
            "username": username, "password": "Correct-Password123!"
        })

    def test_register_requires_email_and_does_not_issue_session(self):
        response = self.client.post("/api/register", json={
            "username": "noemail", "password": "Correct-Password123!"
        })
        self.assertEqual(response.status_code, 422)
        response = self.register()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["verification_required"])
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.assertEqual(self.login().status_code, 403)
        self.assertEqual(len(self.tokens), 1)
        with sqlite3.connect(self.path) as con:
            stored = con.execute("SELECT token_hash FROM email_verifications").fetchone()[0]
            self.assertNotEqual(stored, self.tokens[0][1])

    def test_single_use_verification_then_login(self):
        self.register()
        token = self.tokens[0][1]
        response = self.client.post("/api/auth/verify-email", json={"token": token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post("/api/auth/verify-email", json={"token": token}).status_code, 400)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/state").status_code, 200)

    def test_expired_token_refused(self):
        self.register()
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE email_verifications SET expires_at=?",
                        ((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),))
        self.assertEqual(self.client.post("/api/auth/verify-email", json={"token": self.tokens[0][1]}).status_code, 400)
        self.assertEqual(self.login().status_code, 403)

    def test_resend_is_throttled_and_invalidates_old_token(self):
        self.register()
        payload = {"username": "newresearcher", "email": "researcher@example.com"}
        self.assertEqual(self.client.post("/api/auth/resend-verification", json=payload).status_code, 202)
        self.assertEqual(len(self.tokens), 1, "Resend cooldown ignored")
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE email_verifications SET created_at=?",
                        ((datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),))
        self.assertEqual(self.client.post("/api/auth/resend-verification", json=payload).status_code, 202)
        self.assertEqual(len(self.tokens), 2)
        self.assertEqual(self.client.post("/api/auth/verify-email", json={"token": self.tokens[0][1]}).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/verify-email", json={"token": self.tokens[1][1]}).status_code, 200)

    def test_resend_smtp_outage_does_not_reveal_account_or_rotate_token(self):
        self.register()
        original = self.tokens[0][1]
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE email_verifications SET created_at=?",
                        ((datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),))
        payload = {"username": "newresearcher", "email": "researcher@example.com"}
        with patch("app.api_auth.send_verification_email", side_effect=OSError("SMTP down")):
            pending = self.client.post("/api/auth/resend-verification", json=payload)
            unknown = self.client.post("/api/auth/resend-verification", json={
                "username": "missing", "email": "missing@example.com"
            })
        self.assertEqual(pending.status_code, 202)
        self.assertEqual(pending.json(), unknown.json())
        self.assertEqual(self.client.post("/api/auth/verify-email", json={"token": original}).status_code, 200)

    def test_resend_does_not_enumerate_accounts(self):
        self.register()
        a = self.client.post("/api/auth/resend-verification", json={
            "username": "nonexistent", "email": "nobody@example.com"
        })
        b = self.client.post("/api/auth/resend-verification", json={
            "username": "newresearcher", "email": "wrong@example.com"
        })
        self.assertEqual(a.status_code, 202)
        self.assertEqual(a.json(), b.json())

    def test_smtp_failure_rolls_back_registration(self):
        with patch("app.api_auth.send_verification_email", side_effect=OSError("SMTP unavailable")):
            response = self.register()
        self.assertEqual(response.status_code, 503)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM email_verifications").fetchone()[0], 0)

    def test_https_email_uses_fragment_and_verified_tls(self):
        import json
        from unittest.mock import MagicMock
        from app.email_delivery import send_verification_email
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"id":"test-message-id"}'
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch.dict(os.environ, {
            "MARKET_MEMORY_ORIGIN": "https://market-memory-pro.onrender.com",
            "MARKET_MEMORY_RESEND_API_KEY": "re_test-only-not-real",
            "MARKET_MEMORY_EMAIL_FROM": "verify@example.com",
        }), patch("app.email_delivery.urlopen", return_value=response) as sender:
            send_verification_email("researcher@example.com", "test-safe-token")
        request = sender.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNotNone(sender.call_args.kwargs.get("context"))
        self.assertEqual(sender.call_args.kwargs["timeout"], 10)
        payload = json.loads(request.data)
        self.assertIn("/#verify-email=test-safe-token", payload["text"])
        self.assertNotIn("/?token=", payload["text"])
        self.assertEqual(payload["to"], ["researcher@example.com"])
        self.assertTrue(request.get_header("Idempotency-key").startswith("verify-"))

    def test_https_email_requires_provider_acceptance_receipt(self):
        from unittest.mock import MagicMock
        from app.email_delivery import send_verification_email
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{}'
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch.dict(os.environ, {
            "MARKET_MEMORY_ORIGIN": "https://market-memory-pro.onrender.com",
            "MARKET_MEMORY_RESEND_API_KEY": "re_test-only-not-real",
            "MARKET_MEMORY_EMAIL_FROM": "verify@example.com",
        }), patch("app.email_delivery.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "did not confirm acceptance"):
                send_verification_email("researcher@example.com", "test-safe-token")

    def test_missing_email_api_blocks_registration(self):
        with patch("app.api_auth.delivery_ready", return_value=False):
            response = self.register()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.tokens, [])

    def test_duplicate_email_is_rejected(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register(username="different-user").status_code, 409)

    def test_verification_link_cross_origin_write_rejected(self):
        self.register()
        response = self.client.post("/api/auth/verify-email",
            headers={"Origin": "https://attacker.example"},
            json={"token": self.tokens[0][1]})
        self.assertEqual(response.status_code, 403)

    def test_existing_legacy_accounts_remain_verified(self):
        with sqlite3.connect(self.path) as con:
            row = con.execute("SELECT email_verified FROM users WHERE username='nonexistent'").fetchone()
            self.assertIsNone(row)
            con.execute("INSERT INTO users(username,password_hash) VALUES('legacy','test-hash')")
            self.assertEqual(con.execute("SELECT email_verified FROM users WHERE username='legacy'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
