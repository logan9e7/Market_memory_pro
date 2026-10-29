# Supabase PostgreSQL and Render

The frontend and API are one same-origin Render web service. This preserves
HttpOnly session cookies without CORS or cross-site-cookie complexity. The
database is PostgreSQL hosted by Supabase; Supabase Auth is not used in this
version. Existing application accounts remain in the application's users table.

## Database

1. Create a Supabase project and choose a region near the Render service.
2. Use Supabase's **Connect** panel to obtain the PostgreSQL **session pooler**
   connection string (typically port 5432) if the hosting runtime is IPv4-only.
   Transaction pooling is not the configured/tested connection mode.
3. Download the project's database CA certificate using the official Supabase
   dashboard. Put it in a Render secret file such as `/etc/secrets/supabase-ca.crt`.
4. Set `DATABASE_URL` as a Render secret environment variable and
   `PGSSLROOTCERT=/etc/secrets/supabase-ca.crt`. Never put the URL/password in Git
   or chat. The driver enforces `sslmode=verify-full`; certificate and hostname
   verification are retained. Neon can also be used with its official verified
   PostgreSQL connection string and appropriate CA trust configuration.
5. Migrations are numbered in `migrations/` and protected by checksums,
   a ledger table, and a transaction-scoped PostgreSQL advisory lock. Run
   `python -m app.migrations check` to verify and
   `python -m app.migrations apply` to apply pending additions.
   In production, the default web startup is now a **read-only migration
   checksum/ledger check**; it never implicitly applies pending DDL.
   A dedicated `python -m app.migrations apply` step or the
   `scripts/start-production.sh` script must apply new migrations before
   a new app version can start. Previously applied SQL is never replayed.
   When a separate migration deploy step becomes available, set
   `MARKET_MEMORY_MIGRATIONS_AT_STARTUP=0` and migrate before deploying.

This application requires an application-private database/schema access model.
The migration revokes access by Supabase's anon/authenticated roles and disables
public Data API access through RLS with no public policies on its tables. Use a
database credential that can perform the initial migration, then review moving
DDL privileges into a deployment-only migration role. Do not give application
database credentials to the browser. Supabase public JS keys are unnecessary.

## Render

Create a Blueprint from `logan9e7/Market_memory_pro` on branch `main` using
`render.yaml`. It specifies a free-tier web service. An existing service's
dashboard settings may override the Blueprint; inspect the actual Render
start command and branch before relying on these settings.
Free instances can sleep after inactivity.

Set the secrets above plus `MARKET_MEMORY_ORIGIN` to the exact HTTPS service
origin, without a trailing slash. `MARKET_MEMORY_SECURE_COOKIE=1` is supplied by
the Blueprint. Render supplies `PORT`; Uvicorn serves the responsive frontend
and API on the same origin. No local filesystem data is required when
DATABASE_URL is set.

After deployment, check `/health/ready`, create a test account, record a quote
and decision, reload, and verify persisted data. Repeat the two-user ownership
test and approval tests against staging before admitting real user data.
Enable database backups and test restoration. Production provider/broker
integrations are still outside this paper-execution release.

## Development and verification

Local SQLite is still the default. Existing SQLite data is not automatically
migrated to PostgreSQL; do not point an existing installation at an empty
cloud database and claim that its data was transferred.

`tests/postgres_smoke.py` runs the full application workflow suite against a
disposable PostgreSQL database when `TEST_DATABASE_URL` and verified TLS trust
are configured. Never use a production database: the test drops its tables.
See the script for the explicit disposable-database guard.

For an automatic local PostgreSQL/TLS test, use `bash scripts/test-postgres.sh`
with Docker available. It creates and removes its own container and temporary
test certificate, runs the suite, and keeps verification enabled. CI runs this
alongside the SQLite suite. Set `MM_TEST_PORT` if 55432 is already occupied.

## Operational readiness and logging

Each request receives an `X-Request-ID` response header and a JSON-line
access log including its method, templated route, status, and latency.
Headers, cookies, queries, bodies and journal text are **not logged**.
`GET /health/live` confirms the process is responsive, while
`GET /health/ready` confirms database access. Both include a short
`RENDER_GIT_COMMIT` revision when Render supplies it.

The Blueprint's start script applies **only pending versioned migrations**
in a separate process and then runs Uvicorn with a read-only startup migration
check. Older dashboard-configured services can use the safe read-only startup
migration preflight in production. Pending migrations cause startup to fail
until a separate migration process runs. Never disable both migration paths.

If Render's autodeploy is not delivering GitHub main commits, investigate the
GitHub-Render installation and actual branch settings. An old successful
compile is not proof that the current commit is deployed.

Before production release, test a backup restoration in an isolated database.
Avoid any destructive schema change or retention deletion until backups,
preflight verification, approval, and rollback procedures are established.

## Native C++ deployment (October 2026)

The existing Render dashboard uses `pip install --no-cache-dir -r requirements.lock`.
The lockfile now includes an editable installation of this repository (`-e .`).
The pinned `pyproject.toml` build requirements compile the
`app._quant_core` C++17/pybind11 extension automatically using `setup.py`.
A missing C++ compiler, failed build, or missing module fails CI/deployment
instead of silently treating an untested binary as ready.

Set `MARKET_MEMORY_REQUIRE_NATIVE_QUANT=1` for the Render service.
This makes application startup fail closed if the native extension is absent.
`GET /health/live` and `GET /health/ready` expose only a simple
`quant_engine` identifier: `cpp-pybind11` when native is active.
The Python fallback remains available in local development and tests if the
strict requirement is not configured.

The native code performs deterministic math only; HTTP, AI, Postgres,
ownership enforcement and paper-only approval stay in Python.

## Production fail-closed safeguards

Set `MARKET_MEMORY_PRODUCTION=1` on the deployed Render service to reject
accidental ephemeral SQLite startup if the PostgreSQL `DATABASE_URL` is
missing. The disposable SQLite test harness remains supported via an explicit
`db_path`. Keep `MARKET_MEMORY_REQUIRE_NATIVE_QUANT=1` to reject an
unavailable compiled C++ engine on startup and at readiness.

The numerical HTTP API rejects non-finite returns and bounds positive
option notionals. A production migration role should eventually be separated
from the runtime database role; never grant public Supabase API roles access.

**Manual Render dashboard items:** The currently deployed service has an
empty health-check path and uses `python -m uvicorn ...` rather than the
Blueprint's `scripts/start-production.sh`. Set the health check path to
`/health/ready` and start command to `bash scripts/start-production.sh`.
Do not disable startup migration compatibility before updating that command.

## Release gate (October 27, 2026)

CI includes a disposable real-Chromium end-to-end journey
(tests/browser_smoke.py) using a temporary SQLite database. It checks the
Research Desk welcome screen, modal account creation, authenticated overview,
capture, journal review, strategy qualification, paper-only approval,
triggered alert, mobile overflow, logout and re-login with persisted data.
This test never connects to production.

The scheduled GitHub workflow .github/workflows/production-monitor.yml
performs read-only checks of /health/live, /health/ready, native
cpp-pybind11, the paper execution mode, HTTPS headers, static assets
and a 401 response for an anonymous /api/state. It can be dispatched
manually and runs daily. Run it again after deployment and compare its
revision with the merged commit. It does not exercise authenticated
production writes.

Enable the release safeguards on the actual Render service by merging
MARKET_MEMORY_PRODUCTION=1, MARKET_MEMORY_REQUIRE_NATIVE_QUANT=1,
MARKET_MEMORY_SECURE_COOKIE=1, and
MARKET_MEMORY_ORIGIN=https://market-memory-pro.onrender.com with
existing secrets. Never replace database credentials.

Disaster recovery gate: database backup and separate restore verification
are still an operator/provider task. Do not restore over the live project
or run disposable PostgreSQL tests against the live database. Do not
claim full launch readiness without a verified restore and recovery plan.

The disposable PostgreSQL CI test now performs pg_dump followed by pg_restore
into a distinct mm_restore_test database, verifying user/decision counts,
public schema size and the versioned migration ledger. This validates the
restore mechanics without touching production. A real Supabase production
backup restore drill is still required before unrestricted launch.

## Readiness and backup (October 29, 2026)

The `/health/ready` endpoint now verifies the schema migration ledger,
migration checksums, and database connectivity before reporting `schema=current`.
The production web startup defaults to **check-only**, including when the
existing Render dashboard still runs Uvicorn directly. Apply future migrations
using the explicit migration command in a controlled deployment process.

Supabase's Free plan does **not** include provider-managed daily database
backups. See `PRODUCTION_READINESS.md` for the optional encrypted offsite
backup workflow, its GitHub configuration, and a separate real-data restore
drill. A synthetic CI restore is not evidence of a real production backup.

## Email verification for new accounts

New production accounts require a verified email before login. The registration
endpoint sends a single-use 30-minute verification link and creates **no
session** until verification is complete. Tokens are stored only as SHA-256
digests and appear in the email URL fragment (not HTTP query strings).
Resend has a 60-second cooldown and uses the existing authentication budget.
Existing accounts are grandfathered to preserve their data and access.

**Render Free blocks outbound SMTP ports 25, 465 and 587.** Therefore
registration emails are sent through Resend's HTTPS REST API, not SMTP.
Resend has a free email allowance (currently 3,000/month and 100/day).
Configure the following **Render environment secrets** (never commit keys):

- `MARKET_MEMORY_RESEND_API_KEY`: send-only API key from Resend.
- `MARKET_MEMORY_EMAIL_FROM`: sender address on a verified Resend domain.
- `MARKET_MEMORY_ORIGIN=https://market-memory-pro.onrender.com`

Verify your sending domain and DNS records with Resend before going live.
The backend verifies HTTPS certificates, sends requests to a fixed Resend API
endpoint, and checks the provider's returned email ID. The idempotency key
is derived from the verification token hash to avoid duplicate sends.

If these settings are missing, **new production registration returns 503**;
existing users can still sign in. Do not disable verification in production.
Do not paste the Resend API key into chat; set it directly in Render secrets.

**Deployment order:** apply additive PostgreSQL migration
`004_email_verification.sql` in an authorized, controlled migration step
**before** the new web process starts, or enable the controlled migration
runner for the release and return to check-only mode immediately afterward.
Production web startup normally checks migrations without modifying schema.
Then deploy, configure HTTPS email API secrets, and test a real inbox.
