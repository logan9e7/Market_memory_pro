-- Email verification for NEW registrations; existing accounts are grandfathered.
-- Never change existing user passwords or invalidate existing sessions.
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS mm_users_email_unique ON users(email) WHERE email IS NOT NULL;
CREATE TABLE IF NOT EXISTS email_verifications (
  token_hash TEXT PRIMARY KEY,
  user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mm_email_verifications_expiry ON email_verifications(expires_at);
ALTER TABLE email_verifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE email_verifications FROM PUBLIC;
DO $mm_email_privileges$
DECLARE role_name TEXT;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      EXECUTE format('REVOKE ALL ON TABLE email_verifications FROM %I', role_name);
    END IF;
  END LOOP;
END $mm_email_privileges$;
