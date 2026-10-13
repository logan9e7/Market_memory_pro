import concurrent.futures
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.database import IntegrityErrors


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.sqlite3"
        self.app = create_app(self.path)
        self.client = TestClient(self.app)
        self.client.post("/api/register", json={"username": "researcher", "password": "correct-long-password"})

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    @contextmanager
    def direct_db(self):
        with sqlite3.connect(self.path) as connection:
            yield connection

    def quote(self, price=110, currency="INR"):
        response = self.client.post("/api/quotes", json={"symbol": "TCS.NS", "price": price, "currency": currency})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def decision(self, index):
        return self.client.post("/api/decisions", json={"symbol": "TCS.NS", "price": 101, "currency": "INR", "setup": "breakout", "side": "buy", "condition": "above", "trigger_price": 100, "note": "A repeated setup, assessed by my journal.", "request_id": f"decision-{index:04}"})

    def evidence(self, wins=7, total=10):
        for index in range(total):
            response = self.decision(index)
            self.assertEqual(response.status_code, 201)
            response = self.client.post(f"/api/decisions/{response.json()['id']}/review", json={"outcome": "win" if index < wins else "loss", "lesson": "Record what happened, not hindsight."})
            self.assertEqual(response.status_code, 200, response.text)

    def state(self):
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_70_percent_needs_ten_completed_reviews(self):
        self.evidence(wins=7, total=9)
        self.assertFalse(self.state()["strategies"][0]["eligible"])
        self.assertEqual(self.state()["opportunities"], [])
        decision = self.decision(9).json()
        self.client.post(f"/api/decisions/{decision['id']}/review", json={"outcome":"loss", "lesson":"Failed setup"})
        self.assertTrue(self.state()["strategies"][0]["eligible"])
        self.assertEqual(self.state()["strategies"][0]["win_rate"], 70)

    def test_no_execution_without_approval_and_retry_is_once_only(self):
        self.evidence()
        quote = self.quote()
        state = self.state()
        self.assertEqual(state["paper_orders"], [])
        oid = state["opportunities"][0]["id"]
        for _ in range(2):
            response = self.client.post(f"/api/opportunities/{oid}/approval", json={"action":"approve", "quantity":2,"expected_quote_id":quote["id"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["mode"], "paper")
        self.assertEqual(len(self.state()["paper_orders"]), 1)
        response = self.client.post(f"/api/opportunities/{oid}/approval", json={"action":"approve", "quantity":3})
        self.assertEqual(response.status_code, 409)

    def test_repeated_matching_price_does_not_duplicate_proposal(self):
        self.evidence()
        self.quote(110)
        self.quote(112)
        self.assertEqual(len(self.state()["opportunities"]), 1)
        self.quote(90)
        self.assertEqual(self.state()["opportunities"][0]["status"], "expired")
        self.quote(110)
        self.assertEqual(len(self.state()["opportunities"]), 2)

    def test_rejected_permission_cannot_execute(self):
        self.evidence()
        self.quote()
        oid = self.state()["opportunities"][0]["id"]
        response = self.client.post(f"/api/opportunities/{oid}/approval", json={"action":"reject"})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/api/opportunities/{oid}/approval", json={"action":"approve"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state()["paper_orders"], [])

    def test_stale_quote_blocks_approval(self):
        self.evidence()
        self.quote()
        oid = self.state()["opportunities"][0]["id"]
        with self.direct_db() as con:
            con.execute("UPDATE quotes SET recorded_at=?", ((datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat(),))
        response = self.client.post(f"/api/opportunities/{oid}/approval", json={"action":"approve"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state()["paper_orders"], [])

    def test_falling_win_rate_expires_pending_proposal(self):
        self.evidence()
        self.quote()
        oid = self.state()["opportunities"][0]["id"]
        did = self.decision(10).json()["id"]
        self.client.post(f"/api/decisions/{did}/review", json={"outcome":"loss", "lesson":"New evidence lowered historical success"})
        self.assertEqual(self.state()["opportunities"][0]["status"], "expired")
        self.assertEqual(self.client.post(f"/api/opportunities/{oid}/approval",json={"action":"approve"}).status_code,409)

    def test_other_user_cannot_read_review_or_approve(self):
        self.evidence()
        self.quote()
        state = self.state()
        other = TestClient(self.app)
        self.addCleanup(other.close)
        other.post("/api/register", json={"username":"other-user", "password":"another-long-password"})
        self.assertEqual(other.get("/api/state").json()["decisions"], [])
        response = other.post(f"/api/decisions/{state['decisions'][0]['id']}/review",json={"outcome":"win","lesson":"Attempt overwrite"})
        self.assertEqual(response.status_code,404)
        response = other.post(f"/api/opportunities/{state['opportunities'][0]['id']}/approval",json={"action":"approve"})
        self.assertEqual(response.status_code,404)

    def test_currency_specific_alerts(self):
        self.client.post("/api/alerts",json={"symbol":"TCS.NS","currency":"USD","condition":"above","target":100})
        self.quote(110,"INR")
        self.assertEqual(self.state()["alerts"][0]["active"],1)
        self.quote(110,"USD")
        self.assertEqual(self.state()["alerts"][0]["active"],0)

    def test_visit_retry_and_snapshot_original_price(self):
        self.quote(101)
        payload={"event_id":"visit-open-0001","kind":"open"}
        self.client.post("/api/visits",json=payload)
        self.client.post("/api/visits",json=payload)
        self.quote(105)
        state=self.state()
        self.assertEqual(len(state["visits"]),1)
        self.assertEqual(len(state["snapshots"]),1)
        self.assertEqual(state["snapshots"][0]["price"],101)
        with self.direct_db() as con:
            with self.assertRaises(IntegrityErrors):
                con.execute("UPDATE snapshots SET price=999")

    def test_original_decision_and_completed_review_are_preserved(self):
        response=self.decision(0)
        did=response.json()["id"]
        self.decision(0)
        self.assertEqual(len(self.state()["decisions"]),1)
        url=f"/api/decisions/{did}/review"
        self.assertEqual(self.client.post(url,json={"outcome":"win","lesson":"Good discipline"}).status_code,200)
        self.assertEqual(self.client.post(url,json={"outcome":"loss","lesson":"Change history"}).status_code,409)
        self.assertEqual(self.state()["decisions"][0]["note"],"A repeated setup, assessed by my journal.")

    def test_concurrent_approval_creates_single_order(self):
        self.evidence()
        quote = self.quote()
        oid=self.state()["opportunities"][0]["id"]
        cookie=self.client.cookies.get("mm_session")
        def approve(_):
            with TestClient(self.app) as client:
                client.cookies.set("mm_session",cookie)
                return client.post(f"/api/opportunities/{oid}/approval",json={"action":"approve","quantity":1,"expected_quote_id":quote["id"]}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(approve,range(4)))
        self.assertEqual(results,[200]*4)
        self.assertEqual(len(self.state()["paper_orders"]),1)

    def test_price_change_requires_new_explicit_consent(self):
        self.evidence()
        old_quote=self.quote(110)
        oid=self.state()["opportunities"][0]["id"]
        self.quote(120)
        response=self.client.post(f"/api/opportunities/{oid}/approval",json={"action":"approve","quantity":1,"expected_quote_id":old_quote["id"]})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.state()["paper_orders"],[])

    def test_authentication_csrf_and_invalid_prices(self):
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get("/api/state").status_code,401)
        self.assertEqual(self.client.post("/api/quotes",headers={"Origin":"https://evil.example"},json={"symbol":"TCS.NS","price":100}).status_code,403)
        self.assertEqual(self.client.post("/api/quotes",json={"symbol":"TCS.NS","price":-1}).status_code,422)
        response=self.client.post("/api/quotes",content='{"symbol":"TCS.NS","price":1e999}',headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code,422)
        self.client.post("/api/logout",json={})
        self.assertEqual(self.client.get("/api/state").status_code,401)

    def test_login_preserves_existing_data_and_rejects_wrong_password(self):
        self.quote(101)
        self.client.post("/api/logout",json={})
        response=self.client.post("/api/login",json={"username":"researcher","password":"wrong-long-password"})
        self.assertEqual(response.status_code,401)
        response=self.client.post("/api/login",json={"username":"researcher","password":"correct-long-password"})
        self.assertEqual(response.status_code,200)
        self.assertIn("HttpOnly",response.headers["set-cookie"])
        self.assertEqual(self.state()["quotes"][0]["price"],101)

    def test_auth_attempts_are_limited(self):
        self.client.post("/api/logout",json={})
        for _ in range(9):
            response=self.client.post("/api/login",json={"username":"researcher","password":"wrong-long-password"})
            self.assertEqual(response.status_code,401)
        response=self.client.post("/api/login",json={"username":"researcher","password":"wrong-long-password"})
        self.assertEqual(response.status_code,429)


if __name__ == "__main__":
    unittest.main()
