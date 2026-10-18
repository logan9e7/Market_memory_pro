"""Authentication regression tests for the local SQLite development backend."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app

class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(db_path=str(Path(self.tmp.name) / "test.sqlite3")))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_password_rotation_revokes_sessions(self):
        a = self.client.post("/api/register", json={"username":"quantuser","password":"initial-password-123"})
        self.assertEqual(a.status_code, 201)
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)
        bad = self.client.post("/api/auth/change-password",json={"current_password":"wrong-password-123","new_password":"new-password-123"})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post("/api/auth/change-password",json={"current_password":"initial-password-123","new_password":"new-password-123"})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/session").status_code,401)
        self.assertEqual(self.client.post("/api/login",json={"username":"quantuser","password":"initial-password-123"}).status_code,401)
        self.assertEqual(self.client.post("/api/login",json={"username":"quantuser","password":"new-password-123"}).status_code,200)
        self.assertEqual(self.client.post("/api/auth/logout-all",json={}).status_code,200)
        self.assertEqual(self.client.get("/api/auth/session").status_code,401)

if __name__ == "__main__":
    unittest.main()
