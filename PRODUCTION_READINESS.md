# Production readiness — Market Memory Pro

## Status and release policy

- **Operational:** Render HTTPS service, verified PostgreSQL TLS, C++17/pybind11,
  signed-off paper-only execution, authentication and per-user ownership,
  structured logs, API no-store, secure cookies, CSP and browser smoke.
- **Automated release tests:** native C++ and API tests, PostgreSQL TLS
  workflow, real Chromium end-to-end, disposable pg_dump/pg_restore, and
  disposable age-encrypted dump/restore.
- **Migration safety:** production web startup checks the ledger and checksums
  without implicitly applying DDL. /health/ready verifies the same before
  returning schema=current. For future migrations, apply migrations in an
  explicit controlled step before deployment.
- **Not yet complete until configured:** offsite encrypted backup, real
  production-data restore drill, Render native health-check path and automated
  deploy integration, and a production uptime decision (Render Free sleeps).

## Encrypted backups on Supabase Free

Supabase's official Database Backups guide states that Free projects should
regularly export their own data; automatic daily provider backups are on paid
plans: https://supabase.com/docs/guides/platform/backups

The repository includes a **disabled until explicitly configured** scheduled
GitHub Actions workflow: .github/workflows/production-backup.yml.
It runs daily at 01:17 UTC once enabled, uses PostgreSQL 17 pg_dump with
sslmode=verify-full and an explicit CA, and pipes the public application schema
directly to **age** public-key encryption. The private decryption key never
enters GitHub. Only encrypted files and SHA-256 checksums are uploaded to a
14-day-retention GitHub Actions artifact. GitHub artifacts are not a substitute
for durable, independent offsite backup storage: export copies elsewhere.

### One-time operator setup

1. On a trusted computer, install age and generate a unique key:
   \`age-keygen -o market-memory-backup-identity.txt\`
   Store the identity file offline, encrypted, with an additional recovery
   copy. **Never paste it into chat, commit it, or upload it to GitHub.**
2. Run \`age-keygen -y market-memory-backup-identity.txt\` to obtain the
   **public** age recipient (starts with age1).
3. In GitHub repository Settings > Secrets and variables > Actions, create
   repository **variables**:
   \`MARKET_MEMORY_BACKUP_AGE_RECIPIENT\` (public recipient) and
   \`MARKET_MEMORY_BACKUP_ENABLED=true\`.
4. Create repository **secrets**:
   \`MARKET_MEMORY_BACKUP_DATABASE_URL\` (ideally a dedicated read-only
   PostgreSQL account with SELECT on application tables, not the browser's
   anon key) and \`MARKET_MEMORY_BACKUP_DB_CA_PEM\` (trusted PEM certificate).
   Use a session-pooler/direct PostgreSQL connection and a PostgreSQL URL
   that does not override sslmode=verify-full or sslrootcert. Never expose
   database passwords in a public variable or commit.
5. Run GitHub Actions > Encrypted offsite database backup > Run workflow.
   Confirm the artifact is present, encrypted, and contains only .age and
   .sha256 files. Review failures; a skipped job means **no backup**.
6. Copy the encrypted artifact and its checksum to a separately controlled
   location before its 14-day GitHub retention expires. Check the backup
   daily; missed runs increase data-loss exposure.

### Restore drill (required before public launch)

Use an isolated, empty **local** PostgreSQL 17 instance. Never restore into
the live Supabase project. With the encrypted artifact, its checksum and the
offline age private key:

\`\`\`bash
sha256sum -c market-memory-public-*.dump.age.sha256
age -d -i market-memory-backup-identity.txt \
  market-memory-public-YYYYMMDDTHHMMSSZ.dump.age |
  pg_restore --exit-on-error --no-owner --no-acl \
    --dbname='postgresql://postgres@127.0.0.1:55433/mm_restore_test'
\`\`\`

Create \`mm_restore_test\` first in an isolated local database; never point the
restore URL to Supabase or production. Verify all application tables, all
migration ledger versions, and sample journal/alert counts against a
contemporaneous read-only production count. Log the restore timestamp and
elapsed time, and keep proof without exposing user records.

**Recovery goals (initial targets, not achieved guarantees):**
- RPO: 24 hours, *only after* the daily encrypted backup is enabled,
  completes reliably, and an offsite copy is retained.
- RTO: to be measured in a real restore drill, including database connection
  rotation, DNS/Render changes, and verification.

Backups contain password hashes, journal entries, and session hashes. Treat
encrypted artifacts as sensitive; keep decryption identities offline. Rotate
sessions and database credentials after a real compromise.

## Render operator controls

Existing service:
https://dashboard.render.com/web/srv-db9thc7avr4c73fc1qr0

- Health check path: set \`/health/ready\`. The external GitHub monitor is
  not a substitute for Render's internal readiness-based rollout gating.
- Start command: \`bash scripts/start-production.sh\` is the preferred
  explicit migration process. Until dashboard configuration is changed,
  the default Uvicorn command is safe because production startup is
  check-only and refuses pending migrations.
- Auto-deploy: actual service reports autoDeploy=yes, but prior merges
  required explicit deploys. Verify GitHub installation/branch and test
  that a successful merge triggers a new deploy. The production monitor
  checks that the **actual deployed SHA matches the merged main SHA**.
- Free Render instances can sleep, delaying the first request. Choose a
  paid always-on tier if uptime/SLA is required. Do not advertise 24/7
  reliability based on scheduled smoke checks alone.

## Release sign-off checklist

- [ ] App CI, C++ CI, Chromium CI and disposable PostgreSQL TLS tests green
- [ ] Live monitor shows the latest main SHA, cpp-pybind11, schema=current,
      database=reachable, execution_mode=paper, private API 401, assets OK
- [ ] Encrypted backup workflow enabled and first *real* backup produced
- [ ] Real encrypted backup restored into isolated PostgreSQL 17 and validated
- [ ] Render health check path configured
- [ ] Automatic deploy verified or explicit manual release procedure approved
- [ ] RPO/RTO recorded and responsible operator assigned
- [ ] Free-tier downtime limitations accepted or upgraded

Do not mark all checkboxes until independently verified. No real-money broker
execution is implemented; this release is paper-only.
