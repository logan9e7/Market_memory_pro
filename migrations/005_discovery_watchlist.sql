CREATE TABLE IF NOT EXISTS watchlist(user_id INTEGER NOT NULL REFERENCES users(id), symbol TEXT NOT NULL, PRIMARY KEY(user_id,symbol));
ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON watchlist FROM PUBLIC;
DO $mm_revoke$
DECLARE role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
      EXECUTE format('REVOKE ALL ON watchlist FROM %I', role_name);
    END IF;
  END LOOP;
END $mm_revoke$;
