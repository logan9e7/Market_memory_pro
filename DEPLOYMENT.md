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
5. The initial migration, `migrations/001_postgres.sql`, is applied at startup
   inside a transaction with a migration advisory lock. Subsequent schema
   changes require new migration files and a deliberate migration runner.

This application requires an application-private database/schema access model.
The migration revokes access by Supabase's anon/authenticated roles and disables
public Data API access through RLS with no public policies on its tables. Use a
database credential that can perform the initial migration, then review moving
DDL privileges into a deployment-only migration role. Do not give application
database credentials to the browser. Supabase public JS keys are unnecessary.

## Render

Create a Blueprint from `logan9e7/Market_memory_pro` on branch `main` using
`render.yaml`. It defines a paid Starter web service to avoid free-service
sleep affecting app visits. Review the service's price in Render before creating
it. No paid resource is created by adding this file to Git.

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
