"""Authentication endpoints and session security (cookie based)."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from app.database import IntegrityErrors
from app.locking import lock_scopes
from app.models import Credentials, RegistrationCredentials, PasswordChange, EmailVerificationToken, ResendVerification
from app.email_delivery import delivery_ready, verification_required, send_verification_email
from app.config import (
    SESSION_DAYS, SESSION_MAX_AGE_SECONDS, PASSWORD_HASH_ITERATIONS,
    AUTH_WINDOW_MINUTES, AUTH_IP_ATTEMPTS, AUTH_USER_ATTEMPTS,
)

def make_auth_router(db, user, audit, now):
    router = APIRouter(tags=["authentication"])
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
            lock_scopes(con, *(f"auth:{key}" for key in keys))
            con.execute("DELETE FROM auth_attempts WHERE recorded_at<?", (cutoff,))
            blocked = any(con.execute("SELECT COUNT(*) FROM auth_attempts WHERE key=?", (key,)).fetchone()[0] >= limit for key, limit in zip(keys, (AUTH_IP_ATTEMPTS, AUTH_USER_ATTEMPTS)))
            if not blocked:
                con.executemany("INSERT INTO auth_attempts VALUES(?,?)", [(key, now()) for key in keys])
        if blocked:
            raise HTTPException(429, "Too many authentication attempts; retry in five minutes")

    def new_email_token(con, uid):
        token = secrets.token_urlsafe(32)
        stamp = datetime.now(timezone.utc)
        con.execute("DELETE FROM email_verifications WHERE user_id=?", (uid,))
        con.execute(
            "INSERT INTO email_verifications(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), uid, stamp.isoformat(),
             (stamp + timedelta(minutes=30)).isoformat()),
        )
        return token

    @router.post("/api/register", status_code=201)
    def register(payload: RegistrationCredentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        required = verification_required()
        if required and not payload.email:
            raise HTTPException(422, "Email address is required")
        if required and not delivery_ready():
            raise HTTPException(503, "Account creation is temporarily unavailable; email delivery is not configured")
        with db() as con:
            try:
                uid = con.execute(
                    "INSERT INTO users(username,password_hash,email,email_verified) VALUES(?,?,?,?)",
                    (payload.username.lower(), password_hash(payload.password), payload.email, not required),
                ).lastrowid
            except IntegrityErrors:
                raise HTTPException(409, "Account details unavailable")
            if required:
                token = new_email_token(con, uid)
                try:
                    send_verification_email(payload.email, token)
                except Exception as exc:
                    # Do not create unusable accounts when the SMTP provider fails.
                    raise HTTPException(503, "Verification email could not be sent; try again later") from exc
            else:
                issue_session(con, uid, response, request)
        return {"username": payload.username.lower(), "verification_required": required,
                "message": "Check your email for a verification link" if required else "Account created"}

    @router.post("/api/auth/verify-email")
    def verify_email(payload: EmailVerificationToken, request: Request):
        auth_budget(request, "verify-email:" + (request.client.host if request.client else "unknown"))
        digest = hashlib.sha256(payload.token.encode()).hexdigest()
        with db() as con:
            lock_scopes(con, f"email-token:{digest}")
            row = con.execute(
                "SELECT user_id FROM email_verifications WHERE token_hash=? AND expires_at>?",
                (digest, now()),
            ).fetchone()
            if not row:
                raise HTTPException(400, "Verification link is invalid or expired")
            con.execute("UPDATE users SET email_verified=TRUE WHERE id=?", (row["user_id"],))
            con.execute("DELETE FROM email_verifications WHERE user_id=?", (row["user_id"],))
            audit(con, row["user_id"], "email_verified", None, {})
        return {"status": "verified", "message": "Email verified. You can now sign in."}

    @router.post("/api/auth/resend-verification", status_code=202)
    def resend_verification(payload: ResendVerification, request: Request):
        auth_budget(request, payload.username)
        # The same response for unknown, verified and pending accounts.
        generic = {"status": "accepted", "message": "If verification is pending, check your inbox"}
        if not verification_required() or not delivery_ready():
            return generic
        with db() as con:
            lock_scopes(con, f"email-resend:{payload.username.lower()}")
            row = con.execute(
                "SELECT id FROM users WHERE username=? AND email=? AND email_verified=FALSE",
                (payload.username.lower(), payload.email),
            ).fetchone()
            if not row:
                return generic
            last = con.execute(
                "SELECT created_at FROM email_verifications WHERE user_id=?", (row["id"],)
            ).fetchone()
            if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds() < 60:
                return generic
            token = new_email_token(con, row["id"])
            try:
                send_verification_email(payload.email, token)
            except Exception as exc:
                raise HTTPException(503, "Verification email could not be sent; try again later") from exc
        return generic

    class LoginCredentials(Credentials):
        shared_device: bool = False

    @router.post("/api/login")
    def login(payload: LoginCredentials, response: Response, request: Request):
        auth_budget(request, payload.username)
        with db() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (payload.username.lower(),)).fetchone()
            # Use equivalent password work even for unknown usernames.
            stored = row["password_hash"] if row else "0" * 32 + ":" + "0" * 64
            candidate = password_hash(payload.password, stored.split(":")[0])
            if not row or not hmac.compare_digest(candidate, stored):
                raise HTTPException(401, "Invalid username or password")
            if not row["email_verified"]:
                raise HTTPException(403, "Verify your email address before signing in")
            issue_session(con, row["id"], response, request, payload.shared_device)
        return {"username": row["username"]}

    @router.post("/api/logout")
    def logout(request: Request, response: Response, uid=Depends(user)):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(request.cookies["mm_session"].encode()).hexdigest(),))
        response.delete_cookie("mm_session")
        return {"status": "signed_out"}

    @router.get("/api/auth/session")
    def session_status(uid=Depends(user)):
        with db() as con:
            row = con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        return {"authenticated": True, "username": row["username"]}

    @router.post("/api/auth/logout-all")
    def logout_all(response: Response, uid=Depends(user)):
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(con, uid, "logout_all", None, {})
        response.delete_cookie("mm_session")
        return {"status": "all_sessions_revoked"}

    @router.post("/api/auth/change-password")
    def change_password(payload: PasswordChange, response: Response, uid=Depends(user)):
        if payload.current_password == payload.new_password:
            raise HTTPException(422, "New password must be different")
        with db() as con:
            lock_scopes(con, f"user:{uid}")
            row = con.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
            stored = row["password_hash"]
            if not hmac.compare_digest(password_hash(payload.current_password, stored.split(":")[0]), stored):
                raise HTTPException(401, "Current password is incorrect")
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(payload.new_password), uid))
            con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            audit(con, uid, "password_changed", None, {})
        response.delete_cookie("mm_session")
        return {"status": "password_changed", "reauthentication_required": True}

    return router
