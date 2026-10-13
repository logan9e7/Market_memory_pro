#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Market_memory_pro
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${MARKET_MEMORY_PORT:-8000}"
