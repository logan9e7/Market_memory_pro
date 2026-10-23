#!/usr/bin/env bash
set -euo pipefail
# Explicit, versioned migration process before the web process starts.
python -m app.migrations apply
export MARKET_MEMORY_MIGRATIONS_AT_STARTUP=0
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
