"""Send account-verification email via Resend's HTTPS API.

Render Free blocks outbound SMTP ports 25/465/587, so production must use
a TLS-verified HTTPS transactional email API. No secret or raw token is logged.
"""
import hashlib
import json
import os
import ssl
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

RESEND_EMAIL_ENDPOINT = "https://api.resend.com/emails"


def verification_required():
    # Production can never opt out of email verification.
    return os.getenv("MARKET_MEMORY_PRODUCTION") == "1" or os.getenv("MARKET_MEMORY_EMAIL_VERIFICATION_REQUIRED") == "1"


def delivery_ready():
    origin = os.getenv("MARKET_MEMORY_ORIGIN", "").strip()
    parts = urlsplit(origin)
    key = os.getenv("MARKET_MEMORY_RESEND_API_KEY", "").strip()
    sender = os.getenv("MARKET_MEMORY_EMAIL_FROM", "").strip()
    return bool(
        key and sender and "@" in sender and not any(c in sender for c in "\r\n")
        and parts.scheme == "https" and parts.netloc
        and not parts.username and not parts.password and parts.path in ("", "/")
        and not parts.query and not parts.fragment
    )


def send_verification_email(recipient, token):
    if not delivery_ready():
        raise RuntimeError("Transactional email delivery is not configured")
    origin = os.environ["MARKET_MEMORY_ORIGIN"].rstrip("/")
    url = f"{origin}/#verify-email={token}"
    message = {
        "from": os.environ["MARKET_MEMORY_EMAIL_FROM"],
        "to": [recipient],
        "subject": "Verify your Market Memory Pro email",
        "text": (
            "Confirm your email address to activate your Market Memory Pro account.\n\n"
            f"{url}\n\n"
            "This link expires in 30 minutes and can be used once. "
            "If you did not create an account, ignore this message.\n"
        ),
    }
    request = Request(
        RESEND_EMAIL_ENDPOINT,
        data=json.dumps(message).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + os.environ["MARKET_MEMORY_RESEND_API_KEY"].strip(),
            "Content-Type": "application/json",
            "Idempotency-Key": "verify-" + hashlib.sha256(token.encode()).hexdigest(),
        },
        method="POST",
    )
    # urllib uses certificate and hostname verification with this context.
    with urlopen(request, timeout=10, context=ssl.create_default_context()) as response:
        if response.status not in (200, 201, 202):
            raise RuntimeError("Email provider rejected the request")
        receipt = json.loads(response.read(4096).decode("utf-8"))
        if not isinstance(receipt, dict) or not receipt.get("id"):
            raise RuntimeError("Email provider did not confirm acceptance")
