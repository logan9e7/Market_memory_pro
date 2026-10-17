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

ROOT = Path(__file__).resolve().parent.parent
MIN_REVIEWS = 10


def now():
    return datetime.now(timezone.utc).isoformat()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=10, max_length=256)


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


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(key TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS auth_attempts_key ON auth_attempts(key,recorded_at);
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), symbol TEXT NOT NULL, price REAL NOT NULL CHECK(price>0), currency TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user', recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS quote_owner_symbol ON quotes(user_id,symbol,id DESC);
CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,kind TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(user_id,event_id));
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,price REAL,currency TEXT,quote_id INTEGER REFERENCES quotes(id),note TEXT NOT NULL,kind TEXT NOT NULL,visit_id INTEGER REFERENCES visits(id),recorded_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshot_no_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'Snapshots are immutable'); END;
CREATE TABLE IF NOT EXISTS strategies(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,setup TEXT NOT NULL,side TEXT NOT NULL,condition TEXT NOT NULL,trigger_price REAL NOT NULL,was_matching INTEGER NOT NULL DEFAULT 0,episode INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,symbol,currency,setup,side,condition,trigger_price));
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),strategy_id INTEGER NOT NULL REFERENCES strategies(id),price REAL NOT NULL,note TEXT NOT NULL,outcome TEXT,lesson TEXT,reviewed_at TEXT,recorded_at TEXT NOT NULL,request_id TEXT NOT NULL,UNIQUE(user_id,request_id));
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,condition TEXT NOT NULL,target REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1,triggered_at TEXT,quote_id INTEGER REFERENCES quotes(id));
CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),strategy_id INTEGER NOT NULL REFERENCES strategies(id),quote_id INTEGER NOT NULL REFERENCES quotes(id),episode INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',wins INTEGER NOT NULL,completed INTEGER NOT NULL,recorded_at TEXT NOT NULL,decided_at TEXT,UNIQUE(strategy_id,episode));
CREATE TABLE IF NOT EXISTS paper_orders(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id),quantity REAL NOT NULL CHECK(quantity>0),reference_price REAL NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,entity_id INTEGER,details TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_owner ON decisions(user_id,id DESC);
CREATE INDEX IF NOT EXISTS snapshots_owner ON snapshots(user_id,id DESC);
"""


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
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            expected = os.getenv("MARKET_MEMORY_ORIGIN") or str(request.base_url).rstrip("/")
            if origin != expected:
                return Response("Cross-origin write rejected", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
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

    def issue_session(con, uid, response, request):
        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        con.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()))
        response.set_cookie("mm_session", token, httponly=True, samesite="strict", secure=request.url.scheme == "https" or os.getenv("MARKET_MEMORY_SECURE_COOKIE") == "1", max_age=604800)

    def password_hash(password, salt=None):
        salt = salt or secrets.token_hex(16)
        return salt + ":" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()

    def auth_budget(request, username):
        ip = request.client.host if request.client else "unknown"
        keys = [hashlib.sha256(("ip:" + ip).encode()).hexdigest(), hashlib.sha256(("user:" + username.lower()).encode()).hexdigest()]
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM auth_attempts WHERE recorded_at<?", (cutoff,))
            blocked = any(con.execute("SELECT COUNT(*) FROM auth_attempts WHERE key=?", (key,)).fetchone()[0] >= limit for key, limit in zip(keys, (30, 10)))
            if not blocked:
                con.executemany("INSERT INTO auth_attempts VALUES(?,?)", [(key, now()) for key in keys])
        if blocked:
            raise HTTPException(429, "Too many authentication attempts; retry in five minutes")

    @app.post("/api/register", status_code=201)
    def register(payload: Credentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        with db() as con:
            try:
                uid = con.execute("INSERT INTO users(username,password_hash) VALUES(?,?)", (payload.username.lower(), password_hash(payload.password))).lastrowid
            except IntegrityErrors:
                raise HTTPException(409, "Username unavailable")
            issue_session(con, uid, response, request)
        return {"username": payload.username.lower()}

    @app.post("/api/login")
    def login(payload: Credentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        with db() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (payload.username.lower(),)).fetchone()
            # Use equivalent password work even for unknown usernames.
            stored = row["password_hash"] if row else "0" * 32 + ":" + "0" * 64
            candidate = password_hash(payload.password, stored.split(":")[0])
            if not row or not hmac.compare_digest(candidate, stored):
                raise HTTPException(401, "Invalid username or password")
            issue_session(con, row["id"], response, request)
        return {"username": row["username"]}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, uid=Depends(user)):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(request.cookies["mm_session"].encode()).hexdigest(),))
        response.delete_cookie("mm_session")
        return {"status": "signed_out"}

    def stats(con, strategy_id):
        row = con.execute("SELECT SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) AS wins,COUNT(outcome) AS completed,COUNT(*) AS total FROM decisions WHERE strategy_id=?", (strategy_id,)).fetchone()
        wins, completed = row["wins"] or 0, row["completed"]
        return {"wins": wins, "completed": completed, "total": row["total"], "win_rate": round(wins / completed * 100, 2) if completed else None, "eligible": completed >= MIN_REVIEWS and wins * 100 >= completed * 70}

    def latest(con, uid, symbol, currency=None):
        if currency:
            return con.execute("SELECT * FROM quotes WHERE user_id=? AND symbol=? AND currency=? ORDER BY id DESC LIMIT 1", (uid, symbol, currency)).fetchone()
        return con.execute("SELECT * FROM quotes WHERE user_id=? AND symbol=? ORDER BY id DESC LIMIT 1", (uid, symbol)).fetchone()

    def matches(rule, price):
        threshold = rule["trigger_price"] if "trigger_price" in rule.keys() else rule["target"]
        return price >= threshold if rule["condition"] == "above" else price <= threshold

    def fresh(quote):
        return quote and (datetime.now(timezone.utc) - datetime.fromisoformat(quote["recorded_at"])).total_seconds() <= 900

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


    # Strategy Lab: persistent user-owned research drafts. No automated trade execution.
    lab_id_type = "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if postgres_url else "INTEGER PRIMARY KEY"
    with db() as con:
        con.execute(f"""CREATE TABLE IF NOT EXISTS lab_ideas(
            id {lab_id_type}, user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, hypothesis TEXT NOT NULL, symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'private',
            status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL)""")
        con.execute(f"""CREATE TABLE IF NOT EXISTS lab_notes(
            id {lab_id_type}, idea_id INTEGER NOT NULL REFERENCES lab_ideas(id),
            user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL)""")

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
        words=set(w.lower() for w in (idea["title"]+" "+idea["hypothesis"]).split() if len(w)>3)
        ranked=sorted((dict(d) for d in decisions),key=lambda d:sum(w in (d["note"]+" "+d["setup"]).lower() for w in words),reverse=True)
        return {"method":"symbol-filtered lexical retrieval","evidence":ranked[:10],
                "limitations":"Not semantic RAG, not a backtest, and not a predictive success rate."}


    # Read-only research endpoints. Credentials stay server-side; never execute orders.
    class TradeSample(BaseModel):
        returns: list[float] = Field(min_length=1,max_length=10000)
        @field_validator("returns")
        @classmethod
        def valid_returns(cls, values):
            if any(not -1 < x < 1000 for x in values):
                raise ValueError("Returns must be finite decimal fractions greater than -100%")
            return values

    class OptionModel(BaseModel):
        spot: float = Field(gt=0,allow_inf_nan=False)
        strike: float = Field(gt=0,allow_inf_nan=False)
        years: float = Field(gt=0,le=30,allow_inf_nan=False)
        rate: float = Field(ge=-1,le=2,allow_inf_nan=False)
        volatility: float = Field(gt=0,le=10,allow_inf_nan=False)
        kind: Literal["call","put"]

    @app.post("/api/quant/trades")
    def quant_trades(payload: TradeSample, uid=Depends(user)):
        from app.quant import trade_stats
        return trade_stats(payload.returns)

    @app.post("/api/quant/option")
    def quant_option(payload: OptionModel, uid=Depends(user)):
        from app.quant import black_scholes
        return black_scholes(**payload.model_dump())

    @app.get("/api/markets/providers")
    def market_providers(uid=Depends(user)):
        return {"markets":[
            {"market":"crypto_spot","provider":"binance","available":True,"authentication":"public"},
            {"market":"india_equities_and_fo","provider":"upstox","available":bool(os.getenv("UPSTOX_ACCESS_TOKEN")),"authentication":"server_token"},
            {"market":"us_equities","provider":"alpaca","available":bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")),"authentication":"server_keys"}],
            "execution":"disabled","notice":"Provider entitlements, geographic availability and data licensing apply."}

    @app.get("/api/markets/crypto/candles")
    async def crypto_candles(symbol: str="BTCUSDT", interval: Literal["15m","1h","4h","1d"]="4h", limit: int=100, uid=Depends(user)):
        import re
        import httpx
        if not re.fullmatch(r"[A-Z0-9]{3,20}",symbol) or not 1<=limit<=500:
            raise HTTPException(422,"Invalid symbol or limit")
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response=await client.get("https://data-api.binance.vision/api/v3/klines",
                    params={"symbol":symbol,"interval":interval,"limit":limit})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503,"Crypto market provider temporarily unavailable")
        return {"provider":"binance","market":"crypto_spot","symbol":symbol,"interval":interval,
            "candles":[{"timestamp_ms":r[0],"open":float(r[1]),"high":float(r[2]),
                        "low":float(r[3]),"close":float(r[4]),"volume":float(r[5])} for r in response.json()],
            "notice":"Exchange-provided data, not investment advice."}


    @app.get("/api/markets/india/candles")
    async def india_candles(instrument_key: str, unit: Literal["minutes","hours","days"]="days",
        interval: int=1, to_date: str="", from_date: str="", uid=Depends(user)):
        import re
        import httpx
        token=os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token: raise HTTPException(503,"Upstox credentials not configured")
        if not re.fullmatch(r"[A-Z_]+\\|[A-Za-z0-9 ._-]{1,90}",instrument_key):
            raise HTTPException(422,"Invalid instrument key")
        if not (1<=interval<=300) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}",to_date) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}",from_date):
            raise HTTPException(422,"Invalid interval or date")
        from urllib.parse import quote
        url=f"https://api.upstox.com/v3/historical-candle/{quote(instrument_key,safe='')}/{unit}/{interval}/{to_date}/{from_date}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get(url,headers={"Authorization":f"Bearer {token}","Accept":"application/json"})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Upstox market data unavailable or access denied")
        return {"provider":"upstox","instrument_key":instrument_key,"data":response.json().get("data",{}),
            "notice":"Check instrument entitlements and market data redistribution rights."}

    @app.get("/api/markets/india/option-chain")
    async def india_option_chain(instrument_key: str, expiry_date: str, uid=Depends(user)):
        import re
        import httpx
        token=os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token: raise HTTPException(503,"Upstox credentials not configured")
        if not re.fullmatch(r"[A-Z_]+\\|[A-Za-z0-9 ._-]{1,90}",instrument_key) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}",expiry_date):
            raise HTTPException(422,"Invalid option-chain query")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get("https://api.upstox.com/v2/option/chain",
                    params={"instrument_key":instrument_key,"expiry_date":expiry_date},
                    headers={"Authorization":f"Bearer {token}","Accept":"application/json"})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Upstox option chain unavailable or access denied")
        return {"provider":"upstox","data":response.json().get("data",[]),
            "notice":"Option Greeks and POP are vendor estimates, not guaranteed probabilities."}

    @app.get("/api/markets/us/candles")
    async def us_candles(symbol: str="AAPL", timeframe: Literal["1Hour","1Day"]="1Day",
        limit: int=100, uid=Depends(user)):
        import re
        import httpx
        key=os.getenv("ALPACA_API_KEY")
        secret=os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret: raise HTTPException(503,"Alpaca market data credentials not configured")
        if not re.fullmatch(r"[A-Z.]{1,12}",symbol) or not 1<=limit<=500:
            raise HTTPException(422,"Invalid symbol or limit")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                    params={"timeframe":timeframe,"limit":limit,"feed":"iex"},
                    headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret})
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502,"Alpaca market data unavailable or access denied")
        return {"provider":"alpaca","feed":"iex","symbol":symbol,"data":response.json(),
            "notice":"Free IEX feed is not a consolidated US market feed."}

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
