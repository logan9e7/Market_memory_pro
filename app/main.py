"""User-owned market evidence and explicit, paper-only strategy execution."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.database import IntegrityErrors, PostgresConnection
from app.intelligence import analyze_evidence
from app.schema import SCHEMA
from app.retention import RETENTION
from app.api_quant import make_quant_router
from app.api_markets import make_markets_router
from app.api_intelligence import make_intelligence_router
from app.evidence import load_evidence, retention_preview

ROOT = Path(__file__).resolve().parent.parent
MIN_REVIEWS = 10
MIN_WIN_RATE_PERCENT = 70
QUOTE_FRESHNESS_SECONDS = 15 * 60
SESSION_DAYS = 7
SESSION_MAX_AGE_SECONDS = SESSION_DAYS * 24 * 60 * 60
PASSWORD_HASH_ITERATIONS = 600_000
AUTH_WINDOW_MINUTES = 5
AUTH_IP_ATTEMPTS = 30
AUTH_USER_ATTEMPTS = 10


def now():
    return datetime.now(timezone.utc).isoformat()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=256)


class RegistrationCredentials(Credentials):
    password: str = Field(min_length=12, max_length=256)

    @field_validator("password")
    @classmethod
    def validate_strength(cls, value):
        if not all((any(c.islower() for c in value), any(c.isupper() for c in value),
                    any(c.isdigit() for c in value), any(not c.isalnum() for c in value))):
            raise ValueError("Use uppercase, lowercase, number and symbol")
        return value


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, value):
        if not all((any(c.islower() for c in value), any(c.isupper() for c in value),
                    any(c.isdigit() for c in value), any(not c.isalnum() for c in value))):
            raise ValueError("Use uppercase, lowercase, number and symbol")
        return value


class Quote(BaseModel):
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9.^_-]+$")
    price: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, value):
        return value.upper()


class Snapshot(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=5000)


class Visit(BaseModel):
    event_id: str = Field(min_length=8, max_length=100)
    kind: Literal["open", "close"]


class Decision(Quote):
    setup: str = Field(min_length=2, max_length=120)
    side: Literal["buy", "sell"]
    condition: Literal["above", "below"]
    trigger_price: float = Field(gt=0, allow_inf_nan=False)
    note: str = Field(min_length=1, max_length=5000)
    request_id: str = Field(min_length=8, max_length=100)

    @field_validator("setup", "note")
    @classmethod
    def text_required(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be blank")
        return value


class Review(BaseModel):
    outcome: Literal["win", "loss"]
    lesson: str = Field(min_length=1, max_length=5000)

    @field_validator("lesson")
    @classmethod
    def lesson_required(cls, value):
        if not value.strip():
            raise ValueError("Record a lesson")
        return value.strip()


class Alert(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    condition: Literal["above", "below"]
    target: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")





def create_app(db_path=None):
    postgres_url = os.getenv("DATABASE_URL") if db_path is None else None
    database = Path(db_path or os.getenv("MARKET_MEMORY_DB", str(ROOT / ".data" / "memory.sqlite3")))
    if not postgres_url:
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def db():
        if postgres_url:
            con = PostgresConnection(postgres_url)
        else:
            con = sqlite3.connect(database, timeout=10)
            database.chmod(0o600)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    with db() as con:
        if postgres_url:
            con.initialize((ROOT / "migrations" / "001_postgres.sql").read_text())
        else:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    app = FastAPI(title="Market Memory Pro", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Never echo passwords or non-finite numeric values in validation errors.
        errors = [{"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]} for item in exc.errors()]
        return JSONResponse({"detail": "Check the form values and try again.", "errors": errors}, status_code=422)

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected = os.getenv("MARKET_MEMORY_ORIGIN") or str(request.base_url).rstrip("/")
            if origin and origin != expected:
                return Response("Cross-origin write rejected", status_code=403)
            if not origin and request.cookies.get("mm_session"):
                fetch_site = request.headers.get("sec-fetch-site")
                if fetch_site in {"cross-site", "same-site"}:
                    return Response("Unverified browser write rejected", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def user(request: Request):
        token = request.cookies.get("mm_session", "")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with db() as con:
            row = con.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash, now())).fetchone()
        if not row:
            raise HTTPException(401, "Sign in to access your memory")
        return row["user_id"]

    def audit(con, uid, kind, entity, details):
        con.execute("INSERT INTO audit_events(user_id,kind,entity_id,details,recorded_at) VALUES(?,?,?,?,?)", (uid, kind, entity, json.dumps(details), now()))

    def issue_session(con, uid, response, request, shared_device=False):
        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        lifetime = timedelta(hours=2) if shared_device else timedelta(days=SESSION_DAYS)
        con.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, (datetime.now(timezone.utc) + lifetime).isoformat()))
        response.set_cookie("mm_session", token, httponly=True, samesite="strict", secure=request.url.scheme == "https" or os.getenv("MARKET_MEMORY_SECURE_COOKIE") == "1", max_age=None if shared_device else SESSION_MAX_AGE_SECONDS)

    def password_hash(password, salt=None):
        salt = salt or secrets.token_hex(16)
        return salt + ":" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_HASH_ITERATIONS).hex()

    def auth_budget(request, username):
        ip = request.client.host if request.client else "unknown"
        keys = [hashlib.sha256(("ip:" + ip).encode()).hexdigest(), hashlib.sha256(("user:" + username.lower()).encode()).hexdigest()]
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=AUTH_WINDOW_MINUTES)).isoformat()
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM auth_attempts WHERE recorded_at<?", (cutoff,))
            blocked = any(con.execute("SELECT COUNT(*) FROM auth_attempts WHERE key=?", (key,)).fetchone()[0] >= limit for key, limit in zip(keys, (AUTH_IP_ATTEMPTS, AUTH_USER_ATTEMPTS)))
            if not blocked:
                con.executemany("INSERT INTO auth_attempts VALUES(?,?)", [(key, now()) for key in keys])
        if blocked:
            raise HTTPException(429, "Too many authentication attempts; retry in five minutes")

    @app.post("/api/register", status_code=201)
    def register(payload: RegistrationCredentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        with db() as con:
            try:
                uid = con.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (payload.username.lower(), password_hash(payload.password))).lastrowid
            except IntegrityErrors:
                raise HTTPException(409, "Username unavailable")
            issue_session(con, uid, response, request)
        return {"username": payload.username.lower()}

    class LoginCredentials(Credentials):
        shared_device: bool = False

    @app.post("/api/login")
    def login(payload: LoginCredentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        with db() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (payload.username.lower(),)).fetchone()
            # Use equivalent password work even for unknown usernames.
            stored = row["password_hash"] if row else "0" * 32 + ":" + "0" * 64
            candidate = password_hash(payload.password, stored.split(":")[0])
            if not row or not hmac.compare_digest(candidate, stored):
                raise HTTPException(401, "Invalid username or password")
            issue_session(con, row["id"], response, request, payload.shared_device)
        return {"username": row["username"]}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, uid=Depends(user)):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(request.cookies["mm_session"].encode()).hexdigest(),))
        response.delete_cookie("mm_session")
        return {"status": "signed_out"}

    @app.get("/api/auth/session")
    def session_status(uid=Depends(user)):
        with db() as con:
            row = con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        return {"authenticated": True, "username": row["username"]}

    @app.post("/api/auth/logout-all")
    def logout_all(response: Response, uid=Depends(user)):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(con, uid, "logout_all", None, {})
        response.delete_cookie("mm_session")
        return {"status": "all_sessions_revoked"}

    @app.post("/api/auth/change-password")
    def change_password(payload: PasswordChange, response: Response, uid=Depends(user)):
        if payload.current_password == payload.new_password:
            raise HTTPException(422, "New password must be different")
        with db() as con:
            row = con.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
            stored = row["password_hash"]
            if not hmac.compare_digest(password_hash(payload.current_password, stored.split(":")[0]), stored):
                raise HTTPException(401, "Current password is incorrect")
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(payload.new_password), uid))
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(con, uid, "password_changed", None, {})
        response.delete_cookie("mm_session")
        return {"status": "password_changed", "reauthentication_required": True}

    def stats(con, strategy_id):
        row = con.execute("SELECT SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) AS wins,COUNT(outcome) AS completed,COUNT(*) AS total FROM decisions WHERE strategy_id=?", (strategy_id,)).fetchone()
        wins, completed = row["wins"] or 0, row["completed"]
        return {"wins": wins, "completed": completed, "total": row["total"], "win_rate": round(wins / completed * 100, 2) if completed else None, "eligible": completed >= MIN_REVIEWS and wins * 100 >= completed * MIN_WIN_RATE_PERCENT}

    def latest(con, uid, symbol, currency=None):
        if currency:
            return con.execute("SELECT * FROM quotes WHERE user_id=? AND symbol=? AND currency=? ORDER BY id DESC LIMIT 1", (uid, symbol, currency)).fetchone()
        return con.execute("SELECT * FROM quotes WHERE user_id=? AND symbol=? ORDER BY id DESC LIMIT 1", (uid, symbol)).fetchone()

    def matches(rule, price):
        threshold = rule["trigger_price"] if "trigger_price" in rule.keys() else rule["target"]
        return price >= threshold if rule["condition"] == "above" else price <= threshold

    def fresh(quote):
        return quote and (datetime.now(timezone.utc) - datetime.fromisoformat(quote["recorded_at"])).total_seconds() <= QUOTE_FRESHNESS_SECONDS

    def evaluate(con, uid, quote):
        for alert in con.execute("SELECT * FROM alerts WHERE user_id=? AND symbol=? AND currency=? AND active=1", (uid, quote["symbol"], quote["currency"])).fetchall():
            if matches(alert, quote["price"]):
                con.execute("UPDATE alerts SET active=0,triggered_at=?,quote_id=? WHERE id=?", (now(), quote["id"], alert["id"]))
                audit(con, uid, "alert_triggered", alert["id"], {"quote_id": quote["id"]})
        for strategy in con.execute("SELECT * FROM strategies WHERE user_id=? AND symbol=? AND currency=?", (uid, quote["symbol"], quote["currency"])).fetchall():
            score = stats(con, strategy["id"])
            matching = matches(strategy, quote["price"]) and score["eligible"] and fresh(quote)
            if not matching:
                con.execute("UPDATE opportunities SET status='expired',decided_at=? WHERE strategy_id=? AND status='pending'", (now(), strategy["id"]))
            if matching and not strategy["was_matching"]:
                episode = strategy["episode"] + 1
                con.execute("UPDATE strategies SET episode=? WHERE id=?", (episode, strategy["id"]))
                oid = con.execute("INSERT INTO opportunities(user_id,strategy_id,quote_id,episode,wins,completed,recorded_at) VALUES(?,?,?,?,?,?,?)", (uid, strategy["id"], quote["id"], episode, score["wins"], score["completed"], now())).lastrowid
                audit(con, uid, "approval_requested", oid, {"quote_id": quote["id"], "win_rate": score["win_rate"]})
            con.execute("UPDATE strategies SET was_matching=? WHERE id=?", (int(matching), strategy["id"]))

    @app.post("/api/quotes", status_code=201)
    def record_quote(payload: Quote, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            qid = con.execute("INSERT INTO quotes(user_id,symbol,price,currency,recorded_at) VALUES(?,?,?,?,?)", (uid, payload.symbol, payload.price, payload.currency, now())).lastrowid
            quote = con.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
            evaluate(con, uid, quote)
        return dict(quote)

    def snapshot_row(con, uid, quote, note, kind, visit_id=None):
        return con.execute("INSERT INTO snapshots(user_id,symbol,price,currency,quote_id,note,kind,visit_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?)", (uid, quote["symbol"], quote["price"], quote["currency"], quote["id"], note, kind, visit_id, now())).lastrowid

    @app.post("/api/snapshots", status_code=201)
    def manual_snapshot(payload: Snapshot, uid=Depends(user)):
        with db() as con:
            quote = latest(con, uid, payload.symbol.upper())
            if not quote:
                raise HTTPException(409, "Record a price for this asset first")
            sid = snapshot_row(con, uid, quote, payload.note, "manual")
        return {"id": sid}

    @app.post("/api/visits")
    def record_visit(payload: Visit, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT id FROM visits WHERE user_id=? AND event_id=?", (uid, payload.event_id)).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            vid = con.execute("INSERT INTO visits(user_id,event_id,kind,recorded_at) VALUES(?,?,?,?)", (uid, payload.event_id, payload.kind, now())).lastrowid
            quotes = con.execute("SELECT * FROM quotes WHERE id IN (SELECT MAX(id) FROM quotes WHERE user_id=? GROUP BY symbol,currency)", (uid,)).fetchall()
            for quote in quotes:
                snapshot_row(con, uid, quote, "Last recorded user price; not a new market quote", payload.kind, vid)
        return {"id": vid, "captured": len(quotes)}

    @app.post("/api/decisions", status_code=201)
    def record_decision(payload: Decision, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT d.*,s.symbol,s.currency,s.setup,s.side,s.condition,s.trigger_price FROM decisions d JOIN strategies s ON d.strategy_id=s.id WHERE d.user_id=? AND d.request_id=?", (uid, payload.request_id)).fetchone()
            if existing:
                expected = (payload.symbol, payload.currency, payload.setup.casefold(), payload.side, payload.condition, payload.trigger_price, payload.price, payload.note)
                actual = tuple(existing[key] for key in ("symbol", "currency", "setup", "side", "condition", "trigger_price", "price", "note"))
                if actual != expected:
                    raise HTTPException(409, "This request ID belongs to a different decision")
                return {"id": existing["id"], "duplicate": True}
            key = (uid, payload.symbol, payload.currency, payload.setup.casefold(), payload.side, payload.condition, payload.trigger_price)
            con.execute("INSERT OR IGNORE INTO strategies(user_id,symbol,currency,setup,side,condition,trigger_price) VALUES(?,?,?,?,?,?,?)", key)
            strategy = con.execute("SELECT id FROM strategies WHERE user_id=? AND symbol=? AND currency=? AND setup=? AND side=? AND condition=? AND trigger_price=?", key).fetchone()
            did = con.execute("INSERT INTO decisions(user_id,strategy_id,price,note,recorded_at,request_id) VALUES(?,?,?,?,?,?)", (uid, strategy["id"], payload.price, payload.note, now(), payload.request_id)).lastrowid
            audit(con, uid, "decision_recorded", did, {"strategy_id": strategy["id"]})
        return {"id": did, "strategy_id": strategy["id"]}

    @app.post("/api/decisions/{decision_id}/review")
    def review_decision(decision_id: int, payload: Review, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            decision = con.execute("SELECT * FROM decisions WHERE id=? AND user_id=?", (decision_id, uid)).fetchone()
            if not decision:
                raise HTTPException(404, "Decision not found")
            if decision["outcome"]:
                if decision["outcome"] == payload.outcome and decision["lesson"] == payload.lesson:
                    return {"status": "reviewed"}
                raise HTTPException(409, "Completed outcomes cannot be rewritten")
            con.execute("UPDATE decisions SET outcome=?,lesson=?,reviewed_at=? WHERE id=?", (payload.outcome, payload.lesson, now(), decision_id))
            audit(con, uid, "outcome_reviewed", decision_id, {"outcome": payload.outcome})
            rule = con.execute("SELECT * FROM strategies WHERE id=?", (decision["strategy_id"],)).fetchone()
            quote = latest(con, uid, rule["symbol"], rule["currency"])
            if quote:
                evaluate(con, uid, quote)
        return {"status": "reviewed"}

    @app.post("/api/alerts", status_code=201)
    def create_alert(payload: Alert, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            aid = con.execute("INSERT INTO alerts(user_id,symbol,currency,condition,target) VALUES(?,?,?,?,?)", (uid, payload.symbol.upper(), payload.currency, payload.condition, payload.target)).lastrowid
            quote = latest(con, uid, payload.symbol.upper(), payload.currency)
            if fresh(quote):
                evaluate(con, uid, quote)
        return {"id": aid}

    class Approval(BaseModel):
        action: Literal["approve", "reject"]
        quantity: float = Field(default=1, gt=0, le=1000000, allow_inf_nan=False)
        expected_quote_id: int | None = Field(default=None, gt=0)

    @app.post("/api/opportunities/{opportunity_id}/approval")
    def approval(opportunity_id: int, payload: Approval, uid=Depends(user)):
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            opportunity = con.execute("SELECT * FROM opportunities WHERE id=? AND user_id=?", (opportunity_id, uid)).fetchone()
            if not opportunity:
                raise HTTPException(404, "Opportunity not found")
            if opportunity["status"] == "approved" and payload.action == "approve":
                order = con.execute("SELECT * FROM paper_orders WHERE opportunity_id=?", (opportunity_id,)).fetchone()
                if order["quantity"] != payload.quantity:
                    raise HTTPException(409, "Already approved with a different quantity")
                return {"status": "approved", "mode": "paper", "order": dict(order)}
            if opportunity["status"] == "rejected" and payload.action == "reject":
                return {"status": "rejected"}
            if opportunity["status"] != "pending":
                raise HTTPException(409, "Opportunity is no longer pending")
            if payload.action == "reject":
                con.execute("UPDATE opportunities SET status='rejected',decided_at=? WHERE id=?", (now(), opportunity_id))
                audit(con, uid, "permission_rejected", opportunity_id, {})
                return {"status": "rejected"}
            rule = con.execute("SELECT * FROM strategies WHERE id=?", (opportunity["strategy_id"],)).fetchone()
            quote = latest(con, uid, rule["symbol"], rule["currency"])
            if not fresh(quote) or not matches(rule, quote["price"]) or not stats(con, rule["id"])["eligible"]:
                raise HTTPException(409, "Evidence or price changed; record a fresh matching price and reassess")
            if payload.expected_quote_id != quote["id"]:
                raise HTTPException(409, "Price changed since this proposal was displayed; refresh before approving")
            con.execute("UPDATE opportunities SET status='approved',decided_at=? WHERE id=?", (now(), opportunity_id))
            oid = con.execute("INSERT INTO paper_orders(user_id,opportunity_id,quantity,reference_price,recorded_at) VALUES(?,?,?,?,?)", (uid, opportunity_id, payload.quantity, quote["price"], now())).lastrowid
            audit(con, uid, "paper_execution_approved", opportunity_id, {"quantity": payload.quantity, "quote_id": quote["id"], "paper_order_id": oid})
            order = con.execute("SELECT * FROM paper_orders WHERE id=?", (oid,)).fetchone()
        return {"status": "approved", "mode": "paper", "order": dict(order)}

    @app.get("/api/state")
    def state(uid=Depends(user)):
        with db() as con:
            strategies = []
            for row in con.execute("SELECT * FROM strategies WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall():
                strategies.append({**dict(row), **stats(con, row["id"])})
            queries = {
                "quotes": "SELECT * FROM quotes WHERE id IN (SELECT MAX(id) FROM quotes WHERE user_id=? GROUP BY symbol,currency) ORDER BY id DESC",
                "snapshots": "SELECT s.*,q.recorded_at AS quote_recorded_at FROM snapshots s LEFT JOIN quotes q ON s.quote_id=q.id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 200",
                "visits": "SELECT * FROM visits WHERE user_id=? ORDER BY id DESC LIMIT 50",
                "decisions": "SELECT d.*,s.symbol,s.currency,s.setup,s.side FROM decisions d JOIN strategies s ON d.strategy_id=s.id WHERE d.user_id=? ORDER BY d.id DESC LIMIT 200",
                "alerts": "SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC LIMIT 200",
                "opportunities": "SELECT o.*,s.symbol,s.currency,s.setup,s.side,s.condition,s.trigger_price,q.price FROM opportunities o JOIN strategies s ON o.strategy_id=s.id JOIN quotes q ON o.quote_id=q.id WHERE o.user_id=? ORDER BY o.id DESC LIMIT 100",
                "paper_orders": "SELECT p.*,s.symbol,s.currency,s.side FROM paper_orders p JOIN opportunities o ON p.opportunity_id=o.id JOIN strategies s ON o.strategy_id=s.id WHERE p.user_id=? ORDER BY p.id DESC LIMIT 100",
                "audit": "SELECT * FROM audit_events WHERE user_id=? ORDER BY id DESC LIMIT 100",
            }
            result = {key: [dict(row) for row in con.execute(sql, (uid,)).fetchall()] for key, sql in queries.items()}
            result.update(username=con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()[0], strategies=strategies, minimum_reviews=MIN_REVIEWS, execution_mode="paper")
        return result


    class LabIdea(BaseModel):
        title: str = Field(min_length=3, max_length=120)
        hypothesis: str = Field(min_length=10, max_length=5000)
        symbol: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9.^_-]+$")
        timeframe: Literal["15m", "1h", "4h", "1d", "1w"] = "4h"

    class LabNote(BaseModel):
        content: str = Field(min_length=1, max_length=5000)

    @app.get("/api/lab")
    def lab_list(uid=Depends(user)):
        with db() as con:
            ideas = [dict(r) for r in con.execute("SELECT * FROM lab_ideas WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,)).fetchall()]
            notes = [dict(r) for r in con.execute("SELECT * FROM lab_notes WHERE user_id=? ORDER BY id DESC LIMIT 300", (uid,)).fetchall()]
        return {"ideas": ideas, "notes": notes, "mode": "research_only"}

    @app.post("/api/lab", status_code=201)
    def lab_create(payload: LabIdea, uid=Depends(user)):
        with db() as con:
            idea_id = con.execute("INSERT INTO lab_ideas(user_id,title,hypothesis,symbol,timeframe,created_at) VALUES(?,?,?,?,?,?)",
                (uid,payload.title.strip(),payload.hypothesis.strip(),payload.symbol.upper(),payload.timeframe,now())).lastrowid
            audit(con, uid, "lab_idea_created", idea_id, {"symbol":payload.symbol.upper()})
        return {"id": idea_id, "status": "draft"}

    @app.post("/api/lab/{idea_id}/notes", status_code=201)
    def lab_add_note(idea_id: int, payload: LabNote, uid=Depends(user)):
        with db() as con:
            idea = con.execute("SELECT id FROM lab_ideas WHERE id=? AND user_id=?", (idea_id,uid)).fetchone()
            if not idea: raise HTTPException(404,"Strategy draft not found")
            note_id = con.execute("INSERT INTO lab_notes(idea_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (idea_id,uid,"user",payload.content.strip(),now())).lastrowid
            audit(con,uid,"lab_note_added",idea_id,{"note_id":note_id})
        return {"id":note_id}

    @app.get("/api/lab/{idea_id}/evidence")
    def lab_evidence(idea_id: int, uid=Depends(user)):
        # Transparent lexical baseline. No fabricated embeddings, LLM, or backtest claims.
        with db() as con:
            idea=con.execute("SELECT * FROM lab_ideas WHERE id=? AND user_id=?", (idea_id,uid)).fetchone()
            if not idea: raise HTTPException(404,"Strategy draft not found")
            decisions=con.execute("""SELECT d.id,d.note,d.outcome,d.lesson,s.setup,s.symbol
                FROM decisions d JOIN strategies s ON s.id=d.strategy_id
                WHERE d.user_id=? AND s.symbol=? ORDER BY d.id DESC LIMIT 100""",
                (uid,idea["symbol"])).fetchall()
        # Keep this endpoint as an explicit evidence retriever, not a second AI analyst.
        # The shared LLM engine can interpret these records after retrieval.
        return {"method": "symbol-filtered recent evidence",
                "evidence": [dict(row) for row in decisions[:10]],
                "limitations": "Recent records only; not ranked for relevance or statistically validated."}


    app.include_router(make_quant_router(user))

    app.include_router(make_markets_router(user))

    app.include_router(make_intelligence_router(user, db, now))

    @app.get("/health/ready")
    def ready():
        with db() as con:
            con.execute("SELECT 1 FROM users LIMIT 1").fetchall()
        return {"status": "ready", "database": "reachable", "execution_mode": "paper"}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app


app = create_app()
