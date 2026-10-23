-- Additive query-performance indexes only; no existing data is modified.
CREATE INDEX IF NOT EXISTS mm_quotes_owner_currency_latest
  ON quotes(user_id, symbol, currency, id DESC);
CREATE INDEX IF NOT EXISTS mm_decisions_strategy_outcome
  ON decisions(strategy_id, outcome);
CREATE INDEX IF NOT EXISTS mm_alerts_active_owner_symbol
  ON alerts(user_id, symbol, currency) WHERE active = 1;
CREATE INDEX IF NOT EXISTS mm_opportunities_owner_status_latest
  ON opportunities(user_id, status, id DESC);
CREATE INDEX IF NOT EXISTS mm_sessions_owner
  ON sessions(user_id);
CREATE INDEX IF NOT EXISTS mm_auth_attempts_recorded_at
  ON auth_attempts(recorded_at);

-- Foreign-key covering indexes identified during the read-only Supabase audit.
CREATE INDEX IF NOT EXISTS mm_alerts_user_fk ON alerts(user_id);
CREATE INDEX IF NOT EXISTS mm_alerts_quote_fk ON alerts(quote_id);
CREATE INDEX IF NOT EXISTS mm_audit_events_owner_latest ON audit_events(user_id, id DESC);
CREATE INDEX IF NOT EXISTS mm_opportunities_quote_fk ON opportunities(quote_id);
CREATE INDEX IF NOT EXISTS mm_paper_orders_owner_fk ON paper_orders(user_id);
CREATE INDEX IF NOT EXISTS mm_snapshots_quote_fk ON snapshots(quote_id);
CREATE INDEX IF NOT EXISTS mm_snapshots_visit_fk ON snapshots(visit_id);
