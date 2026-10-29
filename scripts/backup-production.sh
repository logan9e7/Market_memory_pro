#!/usr/bin/env bash
# Encrypted, read-only logical backup of the app's public PostgreSQL schema.
# Plaintext pg_dump bytes stream directly into age: no unencrypted dump file.
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set a backup-only PostgreSQL connection URL}"
: "${DATABASE_SSL_ROOT_CERT:?Set the trusted PostgreSQL CA certificate PEM}"
: "${BACKUP_AGE_RECIPIENT:?Set an age public recipient (never a private key)}"

python3 - <<'PY'
import os
from urllib.parse import urlsplit, parse_qs
u = urlsplit(os.environ["DATABASE_URL"])
if u.scheme not in ("postgresql", "postgres") or not u.hostname or u.path in ("", "/"):
    raise SystemExit("Invalid backup PostgreSQL URL")
options = parse_qs(u.query)
if options.get("sslmode", ["verify-full"]) != ["verify-full"] or "sslrootcert" in options:
    raise SystemExit("Backup URL must use sslmode=verify-full and no sslrootcert override")
pem = os.environ["DATABASE_SSL_ROOT_CERT"].replace("\\n", "\n")
if "-----BEGIN CERTIFICATE-----" not in pem or "-----END CERTIFICATE-----" not in pem:
    raise SystemExit("Backup CA certificate is not a valid PEM envelope")
PY

if ! command -v age >/dev/null 2>&1; then
  echo "age encryption CLI not installed; refusing unencrypted backup" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker required for pinned PostgreSQL pg_dump client" >&2
  exit 1
fi

output_dir="${BACKUP_OUTPUT_DIR:-backups}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
filename="market-memory-public-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
target="$output_dir/$filename"
image="${BACKUP_PG_IMAGE:-postgres:17-alpine}"

cleanup() {
  if [ "${backup_complete:-0}" != 1 ]; then
    rm -f "$target" "$target.sha256"
  fi
}
trap cleanup EXIT

# Never echo connection strings, user rows, password hashes, or session tokens.
# --network host is used on Linux GitHub runners; the server is still verified
# against the pinned PEM and hostname (PGSSLMODE=verify-full).
docker run --rm --network host \
  -e DATABASE_URL -e DATABASE_SSL_ROOT_CERT "$image" sh -ceu '
    umask 077
    printf "%b\n" "$DATABASE_SSL_ROOT_CERT" > /tmp/market-memory-ca.crt
    chmod 600 /tmp/market-memory-ca.crt
    export PGSSLROOTCERT=/tmp/market-memory-ca.crt
    export PGSSLMODE=verify-full
    exec pg_dump --dbname="$DATABASE_URL" --format=custom \
      --schema=public --no-owner --no-acl
  ' | age -r "$BACKUP_AGE_RECIPIENT" -o "$target"

if [ ! -s "$target" ] || [ "$(wc -c < "$target")" -lt 200 ]; then
  echo "Encrypted backup is empty or unexpectedly small" >&2
  exit 1
fi
sha256sum "$target" > "$target.sha256"
backup_complete=1
echo "Encrypted backup created: $filename (public schema; age recipient; SHA-256 recorded)"
