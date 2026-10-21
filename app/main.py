"""FastAPI composition root: auth, security middleware and registered routers."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api_auth import make_auth_router
from app.api_journal import make_journal_router
from app.api_strategy import make_strategy_router
from app.api_lab import make_lab_router
from app.api_quant import make_quant_router
from app.api_markets import make_markets_router
from app.api_intelligence import make_intelligence_router
from app.db_runtime import create_database
from app.strategy_engine import make_strategy_engine

ROOT = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat()


def create_app(db_path=None):
    db = create_database(ROOT, db_path)

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

    stats, latest, matches, fresh, evaluate = make_strategy_engine(now, audit)

    app.include_router(make_journal_router(db, user, now, audit, evaluate, latest))

    app.include_router(make_strategy_router(db, user, now, audit, latest, fresh, matches, stats, evaluate))

    app.include_router(make_lab_router(db, user, now, audit))

    app.include_router(make_quant_router(user))

    app.include_router(make_markets_router(user))

    app.include_router(make_intelligence_router(user, db, now))

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        try:
            with db() as con:
                con.execute("SELECT 1 FROM users LIMIT 1").fetchall()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ready", "database": "reachable", "execution_mode": "paper"}

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app


app = create_app()
