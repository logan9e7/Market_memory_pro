# Market Memory Pro

User-driven market memory: **observe → record → review → identify → ask → paper execute**.

This is an original, runnable development foundation. It does not copy the implementation of Market_memory_new. It uses a same-origin web UI, FastAPI and SQLite so the initial workflow can run without cloud credentials, external market providers or an AI subscription.

For hosted deployment, set `DATABASE_URL` to use Supabase PostgreSQL. TLS certificate/hostname verification is enforced. The responsive frontend and API deploy together to Render using `render.yaml`; see [DEPLOYMENT.md](DEPLOYMENT.md) for database configuration, private table access and secure settings.

## Run

Requires Python 3.12. From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The cloud environment also has `bash scripts/start.sh`. It uses the existing checkout under `/workspace/Market_memory_pro`; no extra worktree is needed. Set `MARKET_MEMORY_PORT` for a different port. The app serves its own HTML, CSS and JavaScript; no frontend compilation is necessary.

Create a username/password account in the app. Record a price, save a snapshot, journal a decision and later review its win/loss with a lesson. Use the same asset, currency, setup name, action, condition and exact trigger price for comparable decisions.

## Implemented behavior

- Authenticated, owner-scoped persistent data. Passwords use salted PBKDF2; sessions use hashed random tokens with HttpOnly, SameSite cookies and a seven-day expiry. Authentication attempts are limited in persistent storage.
- Open/close captures preserve the latest user-recorded prices and their original timestamps. Browser visibility changes and pagehide request close capture with keepalive; browser termination can still prevent delivery.
- Manual snapshots freeze a recorded price and observation. Prices include currency and are explicitly labelled user-recorded.
- Alerts evaluate when a new price is recorded, and immediately on creation if a recent matching price exists. Triggered alerts appear in the app; no push/email delivery or continuous feed is connected.
- Structured decision records are grouped into strategies. Only completed win/loss reviews count. A strategy qualifies at **70% or higher with at least 10 completed outcomes**; pending decisions are excluded. Completed outcomes cannot be rewritten through the API.
- A deterministic detector proposes an opportunity when a qualified price rule matches. Repeated matching prices do not create repeated proposals; leaving the condition and re-entering starts a new episode. Lowering the success rate below the requirement expires pending proposals.
- Every opportunity requires its own approval and quantity. Approval rechecks current evidence, currency, rule and price freshness (15-minute maximum). Rejection cannot turn into approval. Approval retries and simultaneous submissions create exactly one paper order.
- The audit trail records decisions, reviews, triggers, proposals and permissions.

Historical win rate is self-reported journal evidence, not a guaranteed success probability. Ten reviews are a minimum evidence gate, not statistical proof. Rule grouping is structured extraction, not an AI interpretation of free text. Changing the exact trigger level creates a separate strategy.

## Validation

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
```

The regression suite uses real disposable SQLite databases and HTTP API requests. It covers ownership, 70% eligibility, stale quotes, declining win rates, visit retries, immutable snapshots, currency-specific alerts, rejected approvals and concurrent once-only execution. `/health/ready` makes an actual database query.

Optional browser test: `python tests/browser_smoke.py` from an environment with Playwright installed and Chromium at `/usr/bin/chromium` (override with `CHROMIUM_PATH`). It starts a separate server on port 8001 with disposable data. The browser workflow validates account creation, user text escaping, journal reviews, 70% qualification, approval, alert triggering, close capture and a mobile viewport. Browser-test dependencies are not required to run the application.

## Persistence and deployment limits

Default data lives in ignored `.data/memory.sqlite3`; set `MARKET_MEMORY_DB` for a persistent volume. Reinstalling dependencies never resets user data. Use SQLite's backup API for a consistent backup while the application is running; test restoration before deployment. The current schema is an initial version, not a general schema-migration system.

Keep this development service on loopback until deployment hardening is complete. For an HTTPS deployment, set `MARKET_MEMORY_ORIGIN` to the exact web origin and `MARKET_MEMORY_SECURE_COOKIE=1`, configure trusted proxy handling, durable storage, backups, resource limits and monitoring. Account recovery/export/deletion, pagination beyond the recent-history views and native app delivery remain future work. The app is intended for one server with a local database, not distributed replicas.

No real broker execution exists. Connecting one requires a chosen broker, sandbox validation, account authorization, explicit symbol mapping, order type/quantity/notional limits, risk controls, fresh provider quotes and broker-side idempotency. A historical win rate alone is not an execution rule.

The next product step is connecting a market provider to visit capture and opportunity checks while retaining the distinction between current provider data and a user's recorded observation. Free-text strategy assistance can then propose editable rules that the user confirms before detection.
