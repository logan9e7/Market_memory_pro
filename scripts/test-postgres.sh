#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test_python="${MM_TEST_PYTHON:-.venv/bin/python}"
test_port="${MM_TEST_PORT:-55432}"
container_name="mm-pg-test-$$"
cert_dir="$(mktemp -d)"
cleanup() {
  docker rm -f "$container_name" >/dev/null 2>&1 || true
  rm -rf "$cert_dir"
}
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -keyout "$cert_dir/server.key" -out "$cert_dir/server.crt" \
  -subj /CN=localhost -addext subjectAltName=DNS:localhost > "$cert_dir/openssl.log" 2>&1
docker run -d --name "$container_name" -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_DB=mm_test -p "127.0.0.1:$test_port:5432" postgres:16-alpine >/dev/null
# The official Postgres image briefly starts a temporary bootstrap server.
# Wait for initialization to finish and the final server to answer SQL queries.
ready=0
for attempt in {1..90}; do
  if docker logs "$container_name" 2>&1 | grep -q "PostgreSQL init process complete; ready for start up"; then
    if docker exec "$container_name" psql -U postgres -d mm_test -Atqc "SELECT 1" 2>/dev/null | grep -qx 1; then
      ready=1
      break
    fi
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  docker logs "$container_name" >&2
  echo "PostgreSQL did not complete initialization" >&2
  exit 1
fi
docker cp "$cert_dir/server.crt" "$container_name:/var/lib/postgresql/server.crt"
docker cp "$cert_dir/server.key" "$container_name:/var/lib/postgresql/server.key"
docker exec "$container_name" sh -c 'chown postgres:postgres /var/lib/postgresql/server.key /var/lib/postgresql/server.crt && chmod 600 /var/lib/postgresql/server.key'
docker exec "$container_name" psql -U postgres -d mm_test -c "ALTER SYSTEM SET ssl = on" >/dev/null
docker exec "$container_name" psql -U postgres -d mm_test -c "ALTER SYSTEM SET ssl_cert_file = '/var/lib/postgresql/server.crt'" >/dev/null
docker exec "$container_name" psql -U postgres -d mm_test -c "ALTER SYSTEM SET ssl_key_file = '/var/lib/postgresql/server.key'" >/dev/null
docker restart "$container_name" >/dev/null
ready=0
for attempt in {1..90}; do
  if docker exec "$container_name" psql -U postgres -d mm_test -Atqc "SELECT 1" 2>/dev/null | grep -qx 1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  docker logs "$container_name" >&2
  exit 1
fi
DATABASE_SSL_ROOT_CERT="$(cat "$cert_dir/server.crt")" PGSSLROOTCERT="$cert_dir/server.crt" \
  TEST_DATABASE_URL="postgresql://postgres@localhost:$test_port/mm_test" \
  MARKET_MEMORY_ALLOW_TEST_RESET=1 "$test_python" tests/postgres_smoke.py

# Exercise a real pg_dump/pg_restore in a SEPARATE disposable database.
# This is a test of the restore procedure, NOT a restore of production backups.
docker exec "$container_name" pg_dump -U postgres -Fc -d mm_test -f /tmp/mm_test.dump
docker exec "$container_name" createdb -U postgres mm_restore_test
docker exec "$container_name" pg_restore -U postgres --no-owner --no-acl -d mm_restore_test /tmp/mm_test.dump
source_counts="$(docker exec "$container_name" psql -U postgres -d mm_test -Atqc "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM decisions), (SELECT count(*) FROM mm_schema_migrations), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE')")"
restored_counts="$(docker exec "$container_name" psql -U postgres -d mm_restore_test -Atqc "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM decisions), (SELECT count(*) FROM mm_schema_migrations), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE')")"
if [ "$source_counts" != "$restored_counts" ]; then
  echo "Isolated restore validation failed: source and restored row/schema counts differ" >&2
  exit 1
fi
if [ "$(docker exec "$container_name" psql -U postgres -d mm_restore_test -Atqc "SELECT count(*) FROM mm_schema_migrations")" != 4 ]; then
  echo "Isolated restore validation failed: migration ledger missing" >&2
  exit 1
fi
echo "Disposable PostgreSQL backup/restore drill passed (row counts, schema and migration ledger)."

# End-to-end encrypted backup from a disposable TLS PostgreSQL database.
# This uses an ephemeral age identity; production keys never enter CI.
if command -v age >/dev/null 2>&1 && command -v age-keygen >/dev/null 2>&1; then
  age-keygen -o "$cert_dir/age-test-identity.txt" >/dev/null 2>&1
  recipient="$(age-keygen -y "$cert_dir/age-test-identity.txt")"
  mkdir -p "$cert_dir/encrypted-backups"
  DATABASE_URL="postgresql://postgres@localhost:$test_port/mm_test" \
    DATABASE_SSL_ROOT_CERT="$(cat "$cert_dir/server.crt")" \
    BACKUP_AGE_RECIPIENT="$recipient" BACKUP_PG_IMAGE=postgres:16-alpine \
    BACKUP_OUTPUT_DIR="$cert_dir/encrypted-backups" bash scripts/backup-production.sh
  encrypted_file="$(find "$cert_dir/encrypted-backups" -maxdepth 1 -name '*.dump.age' -print -quit)"
  test -n "$encrypted_file"
  sha256sum -c "$encrypted_file.sha256"
  docker exec "$container_name" createdb -U postgres mm_encrypted_restore_test
  # PostgreSQL creates public by default; the archive includes CREATE SCHEMA public.
  # Drop it ONLY in this newly created disposable restore database.
  docker exec "$container_name" psql -U postgres -d mm_encrypted_restore_test -c "DROP SCHEMA public CASCADE" >/dev/null
  age -d -i "$cert_dir/age-test-identity.txt" "$encrypted_file" | \
    docker exec -i "$container_name" pg_restore -U postgres --no-owner --no-acl \
      -d mm_encrypted_restore_test
  encrypted_counts="$(docker exec "$container_name" psql -U postgres -d mm_encrypted_restore_test -Atqc "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM decisions), (SELECT count(*) FROM mm_schema_migrations), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE')")"
  if [ "$source_counts" != "$encrypted_counts" ]; then
    echo "Encrypted backup restore mismatch" >&2
    exit 1
  fi
  echo "Encrypted age backup and isolated restore drill passed."
else
  echo "Skipping encrypted backup drill locally: age CLI not installed."
fi
