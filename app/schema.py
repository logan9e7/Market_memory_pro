"""SQLite schema; kept separate from request handling for maintainability."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS auth_attempts(key TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS auth_attempts_key ON auth_attempts(key,recorded_at);
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), symbol TEXT NOT NULL, price REAL NOT NULL CHECK(price>0), currency TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'user', recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS quote_owner_symbol ON quotes(user_id,symbol,id DESC);
CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),event_id TEXT NOT NULL,kind TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(user_id,event_id));
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,price REAL,currency TEXT,quote_id INTEGER REFERENCES quotes(id),note TEXT NOT NULL,kind TEXT NOT NULL,visit_id INTEGER REFERENCES visits(id),recorded_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshot_no_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'Snapshots are immutable'); END;
CREATE TABLE IF NOT EXISTS strategies(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,setup TEXT NOT NULL,side TEXT NOT NULL,condition TEXT NOT NULL,trigger_price REAL NOT NULL,was_matching INTEGER NOT NULL DEFAULT 0,episode INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,symbol,currency,setup,side,condition,trigger_price));
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),strategy_id INTEGER NOT NULL REFERENCES strategies(id),price REAL NOT NULL,note TEXT NOT NULL,outcome TEXT,lesson TEXT,reviewed_at TEXT,recorded_at TEXT NOT NULL,request_id TEXT NOT NULL,UNIQUE(user_id,request_id));
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,currency TEXT NOT NULL,condition TEXT NOT NULL,target REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1,triggered_at TEXT,quote_id INTEGER REFERENCES quotes(id));
CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),strategy_id INTEGER NOT NULL REFERENCES strategies(id),quote_id INTEGER NOT NULL REFERENCES quotes(id),episode INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',wins INTEGER NOT NULL,completed INTEGER NOT NULL,recorded_at TEXT NOT NULL,decided_at TEXT,UNIQUE(strategy_id,episode));
CREATE TABLE IF NOT EXISTS paper_orders(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id),quantity REAL NOT NULL CHECK(quantity>0),reference_price REAL NOT NULL,recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,entity_id INTEGER,details TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS decisions_owner ON decisions(user_id,id DESC);
CREATE INDEX IF NOT EXISTS snapshots_owner ON snapshots(user_id,id DESC);
CREATE TABLE IF NOT EXISTS analysis_reports(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),model TEXT NOT NULL,report_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS analysis_reports_owner ON analysis_reports(user_id,id DESC);
CREATE TABLE IF NOT EXISTS lab_ideas(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,hypothesis TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,visibility TEXT NOT NULL DEFAULT 'private',status TEXT NOT NULL DEFAULT 'draft',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lab_notes(id INTEGER PRIMARY KEY,idea_id INTEGER NOT NULL REFERENCES lab_ideas(id),user_id INTEGER NOT NULL REFERENCES users(id),role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
"""
