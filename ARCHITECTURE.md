# Market Memory Pro — Backend architecture

## Boundaries
- `app/main.py`: FastAPI composition, browser security, cookie session dependency,
  audit event creation, liveness and readiness endpoints.
- `app/models.py`: shared validated HTTP request models.
- `app/config.py`: explicit domain defaults and authentication limits.
- `app/api_auth.py`: registration, sessions, login and password rotation.
- `app/api_journal.py`: quotes, immutable snapshots, visits, trade decisions and reviews.
- `app/api_strategy.py`: strategy states, alerts and **paper-only** approvals.
- `app/api_lab.py`: research ideas, notes and selected historical evidence.
- `app/api_quant.py`: authenticated deterministic math HTTP endpoints.
- `app/api_markets.py`: read-only remote market data integrations.
- `app/api_intelligence.py`: LLM evidence analysis, reports and read-only retention previews.
- `app/strategy_engine.py`: domain-level strategy evaluation and quote matching.
- `app/db_runtime.py`: connection lifecycle, rollback and existing schema initialization.
- `app/database.py`: PostgreSQL/SQLite query adapter and TLS setup.
- `app/quant_hybrid.py`: optional native C++ computations with Python fallback.
- `native/quant_math.hpp`: deterministic numerical functions; no I/O.
- `native/quant_core.cpp`: pybind11 bridge; packaged as `app._quant_core`.

## Security & data integrity
Server-side cookie sessions, parameterized SQL, owner-scoped queries and a read-only
paper execution mode. Completed reviews and immutable snapshots are preserved.
RLS is enabled in the initial PostgreSQL schema, but Supabase role permissions
must be separately verified. Do not claim that enabling RLS alone isolates data.

## Verification
```bash
pip install -r requirements.lock
python -m unittest discover -s tests -v
bash scripts/test-postgres.sh
```
Native compilation and parity checks run in GitHub Actions. The Render service
currently installs `requirements.lock` and uses Python fallback unless a native
extension is explicitly built and installed on its runtime.

## Important open work
- Replace execution of the initial PostgreSQL schema at every service startup
  with a separately versioned, permission-restricted migration procedure.
- Refine PostgreSQL write contention: a shared advisory lock is currently used.
- Add request correlation, structured operational logs and observability.
- A pgvector embedding/retrieval workflow is **not yet live**.
- Retention previews are read-only; deletion is disabled until evidence protection,
  safe archival, dependency checks and explicit approvals are implemented.
- No live order execution should be enabled without dedicated risk, audit,
  authorization, and regulatory reviews.
