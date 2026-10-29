#!/usr/bin/env python3
"""Read-only production probe. Never creates accounts or modifies user data.

Usage: python scripts/verify-production.py
Optional env: MARKET_MEMORY_URL (HTTPS origin), EXPECTED_REVISION (short SHA),
EXPECTED_NATIVE (default cpp-pybind11).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

ORIGIN = os.getenv("MARKET_MEMORY_URL", "https://market-memory-pro.onrender.com").rstrip("/")
EXPECTED_NATIVE = os.getenv("EXPECTED_NATIVE", "cpp-pybind11")
EXPECTED_REVISION = os.getenv("EXPECTED_REVISION", "").strip()

def request(path):
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(ORIGIN + path, headers={"User-Agent":"MarketMemoryReleaseProbe/1"}),
                timeout=30
            ) as response:
                return response.status, {k.lower():v for k,v in response.headers.items()}, response.read(250000)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return 401, {k.lower():v for k,v in exc.headers.items()}, exc.read(250000)
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        if attempt < 3:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{path} unavailable after retries: {type(last).__name__}")

def verify():
    url = urlparse(ORIGIN)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise RuntimeError("Production probe requires a clean HTTPS origin")
    live_status, _, live_body = request("/health/live")
    ready_status, _, ready_body = request("/health/ready")
    assert live_status == ready_status == 200, f"Health failure: live={live_status}, ready={ready_status}"
    live = json.loads(live_body)
    ready = json.loads(ready_body)
    assert live["status"] == "alive" and ready["status"] == "ready", "Invalid health payload"
    assert ready["database"] == "reachable" and ready["execution_mode"] == "paper", "Wrong database/execution mode"
    assert live["quant_engine"] == ready["quant_engine"] == EXPECTED_NATIVE, "Native engine mismatch"
    assert ready["revision"] and ready["revision"] != "unknown", "Deployment revision unavailable"
    if EXPECTED_REVISION:
        assert ready["revision"].startswith(EXPECTED_REVISION[:12]), "Unexpected deployed commit"
    index_status, headers, html = request("/")
    assert index_status == 200 and b"MARKET MEMORY" in html, "Landing page not served"
    assert headers.get("x-frame-options", "").upper() == "DENY", "Frame protection missing"
    assert "default-src 'self'" in headers.get("content-security-policy", ""), "CSP missing"
    for asset in ("/static/app.js", "/static/style.css"):
        code, _, body = request(asset)
        assert code == 200 and len(body) > 100, f"Static asset missing: {asset}"
    private_status, private_headers, _ = request("/api/state")
    assert private_status == 401, "Unauthenticated account state exposed"
    assert private_headers.get("cache-control") == "no-store", "Private API caching not disabled"
    print(json.dumps({"status":"passed","revision":ready["revision"],
                      "quant_engine":ready["quant_engine"],"database":"reachable",
                      "execution_mode":"paper","private_api":"401","assets":"ok"}))

def verify_with_revision_wait():
    """Wait only for the expected commit; never hide other production failures."""
    wait_seconds = int(os.getenv("WAIT_FOR_REVISION_SECONDS", "0"))
    if wait_seconds < 0 or wait_seconds > 900:
        raise ValueError("WAIT_FOR_REVISION_SECONDS must be between 0 and 900")
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return verify()
        except AssertionError as exc:
            if ("Unexpected deployed commit" not in str(exc)
                    or not EXPECTED_REVISION or time.monotonic() >= deadline):
                raise
            time.sleep(min(20, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    try:
        verify_with_revision_wait()
    except Exception as exc:
        print(f"Production verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
