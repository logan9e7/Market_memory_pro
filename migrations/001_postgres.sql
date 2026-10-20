-- Initial application-private PostgreSQL schema. Repeatable; never resets data.

CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(key TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS auth_attempts_key ON auth_attempts(key,recorded_at);
CREATE TABLE IF NOT EXISTS quotes(id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), symbol TEXT NOT NULL, price DOUBLE PRECISION NOT NULL CHECK(price>0), currency TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user', recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS quote_owner_symbol ON quotes(user_id,symbol,id DESC);
CREATE TABLE IF NOT EXISTS visits(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,kind TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(user_id,event_id));
CREATE TABLE IF NOT EXISTS snapshots(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,price DOUBLE PRECISION,currency TEXT,quote_id BIGINT REFERENCES quotes(id),note TEXT NOT NULL,kind TEXT NOT NULL,visit_id BIGINT REFERENCES visits(id),recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS strategies(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,setup TEXT NOT NULL,side TEXT NOT NULL,condition TEXT NOT NULL,trigger_price DOUBLE PRECISION NOT NULL,was_matching INTEGER NOT NULL DEFAULT 0,episode INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,symbol,currency,setup,side,condition,trigger_price));
CREATE TABLE IF NOT EXISTS decisions(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),strategy_id BIGINT NOT NULL REFERENCES strategies(id),price DOUBLE PRECISION NOT NULL,note TEXT NOT NULL,outcome TEXT,lesson TEXT,reviewed_at TEXT,recorded_at TEXT NOT NULL,request_id TEXT NOT NULL,UNIQUE(user_id,request_id));
CREATE TABLE IF NOT EXISTS alerts(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,condition TEXT NOT NULL,target DOUBLE PRECISION NOT NULL,active INTEGER NOT NULL DEFAULT 1,triggered_at TEXT,quote_id BIGINT REFERENCES quotes(id));
CREATE TABLE IF NOT EXISTS opportunities(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),strategy_id BIGINT NOT NULL REFERENCES strategies(id),quote_id BIGINT NOT NULL REFERENCES quotes(id),episode INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',wins INTEGER NOT NULL,completed INTEGER NOT NULL,recorded_at TEXT NOT NULL,decided_at TEXT,UNIQUE(strategy_id,episode));
CREATE TABLE IF NOT EXISTS paper_orders(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id),quantity DOUBLE PRECISION NOT NULL CHECK(quantity>0),reference_price DOUBLE PRECISION NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),kind TEXT NOT NULL,entity_id INTEGER,details TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_owner ON decisions(user_id,id DESC);
CREATE INDEX IF NOT EXISTS snapshots_owner ON snapshots(user_id,id DESC);
CREATE TABLE IF NOT EXISTS analysis_reports(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),model TEXT NOT NULL,report_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS analysis_reports_owner ON analysis_reports(user_id,id DESC);
CREATE TABLE IF NOT EXISTS lab_ideas(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),title TEXT NOT NULL,hypothesis TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,visibility TEXT NOT NULL DEFAULT 'private',status TEXT NOT NULL DEFAULT 'draft',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lab_notes(id BIGSERIAL PRIMARY KEY,idea_id BIGINT NOT NULL REFERENCES lab_ideas(id),user_id BIGINT NOT NULL REFERENCES users(id),role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS lab_ideas_owner ON lab_ideas(user_id,id DESC);
CREATE INDEX IF NOT EXISTS lab_notes_owner ON lab_notes(user_id,id DESC);

CREATE OR REPLACE FUNCTION mm_prevent_snapshot_update() RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS 'BEGIN RAISE EXCEPTION ''Snapshots are immutable'' USING ERRCODE=''23514''; END';
DROP TRIGGER IF EXISTS snapshot_no_update ON snapshots;
CREATE TRIGGER snapshot_no_update BEFORE UPDATE ON snapshots FOR EACH ROW EXECUTE FUNCTION mm_prevent_snapshot_update();
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE visits ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_reports ENABLE ROW LEVEL SECURITY;
DO $$ DECLARE role_name text; table_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
   FOREACH table_name IN ARRAY ARRAY['users','sessions','auth_attempts','quotes','visits','snapshots','strategies','decisions','alerts','opportunities','paper_orders','audit_events','lab_ideas','lab_notes','analysis_reports'] LOOP
    EXECUTE format('REVOKE ALL ON TABLE %I FROM %I',table_name,role_name);
   END LOOP;
  END IF;
 END LOOP;
END $$;
