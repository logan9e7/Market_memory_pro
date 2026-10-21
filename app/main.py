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

from app.models import Credentials, RegistrationCredentials, PasswordChange, Quote, Snapshot, Visit, Decision, Review, Alert
from app.config import MIN_REVIEWS, MIN_WIN_RATE_PERCENT, QUOTE_FRESHNESS_SECONDS
from app.api_auth import make_auth_router
from app.api_journal import make_journal_router
from app.database import IntegrityErrors, PostgresConnection
from app.schema import SCHEMA

ROOT = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat()


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

    app.include_router(make_auth_router(db, user, audit, now))

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

    app.include_router(make_journal_router(db, user, now, audit, evaluate, latest))

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

    REPORT_HISTORY_LIMIT = 10

    @app.post("/api/intelligence/analyze")
    async def intelligence_analyze(uid=Depends(user)):
        """Analyze only this user's recent evidence; never send passwords or tokens."""
        with db() as con:
            evidence = load_evidence(con, uid)
        if not any(evidence.values()):
            raise HTTPException(409, "Record a journal entry or price snapshot before analysis")
        try:
            report = await analyze_evidence(evidence)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception:
            # Do not expose model provider credentials or user journal text in errors.
            raise HTTPException(502, "Analysis provider unavailable or returned invalid data")
        with db() as con:
            report_id = con.execute(
                "INSERT INTO analysis_reports(user_id,model,report_json,created_at) VALUES(?,?,?,?)",
                (uid, os.getenv("LLM_MODEL", "gpt-4o-mini"), report.model_dump_json(), now())
            ).lastrowid
        return {"id": report_id, "analysis": report.model_dump(), "source_counts": {k: len(v) for k,v in evidence.items()}}

    @app.get("/api/intelligence/history")
    def intelligence_history(uid=Depends(user)):
        with db() as con:
            rows = con.execute(
                "SELECT id,model,report_json,created_at FROM analysis_reports WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, REPORT_HISTORY_LIMIT)
            ).fetchall()
        return {"reports": [{"id": r["id"], "model": r["model"], "created_at": r["created_at"],
                             "analysis": json.loads(r["report_json"])} for r in rows]}

    @app.get("/api/intelligence/evolution")
    def intelligence_evolution(uid=Depends(user)):
        """Compare evidence-backed parameter observations across the last two reports."""
        with db() as con:
            rows = con.execute(
                "SELECT id,report_json,created_at FROM analysis_reports WHERE user_id=? ORDER BY id DESC LIMIT 2",
                (uid,)).fetchall()
        if len(rows) < 2:
            return {"status": "insufficient_history", "required_reports": 2, "available": len(rows)}
        recent, previous = (json.loads(row["report_json"]) for row in rows)
        levels = ("level_1_evidence", "level_2_quantitative", "level_3_behavior", "level_5_adaptation")
        def parameters(report):
            return {(level, item["parameter"]): item for level in levels
                    for item in report.get(level, []) if item.get("parameter")}
        current, prior = parameters(recent), parameters(previous)
        keys = current.keys() | prior.keys()
        return {
            "status": "compared",
            "current_report_id": rows[0]["id"],
            "previous_report_id": rows[1]["id"],
            "added": [{"level": k[0], **current[k]} for k in sorted(keys) if k in current and k not in prior],
            "missing": [{"level": k[0], **prior[k]} for k in sorted(keys) if k in prior and k not in current],
            "revisited": [{"level": k[0], "parameter": k[1],
                           "previous": prior[k]["observation"], "current": current[k]["observation"]}
                          for k in sorted(keys) if k in prior and k in current
                          and prior[k]["observation"] != current[k]["observation"]],
            "notice": "Changes in LLM descriptions are not proof of behavior change. Verify against source records."
        }

    @app.get("/api/account/retention")
    def retention_settings(uid=Depends(user)):
        return {"raw_days": RETENTION.raw_days, "summary_days": RETENTION.summary_days,
                "deletion_mode": RETENTION.deletion_mode,
                "preserve_active_strategy_evidence": RETENTION.preserve_active_strategy_evidence,
                "deletion_enabled": RETENTION.deletion_enabled,
                "notice": "Retention is configured; no data will be deleted until verified archival and approval are implemented."}

    @app.get("/api/account/retention/preview")
    def retention_candidates(uid=Depends(user)):
        with db() as con:
            return retention_preview(con, uid, RETENTION.raw_days)

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
