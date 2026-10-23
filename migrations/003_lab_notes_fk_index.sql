-- Index missing on newly created lab_notes table after the initial recovery.
-- Additive and safe on existing user research notes.
CREATE INDEX IF NOT EXISTS mm_lab_notes_idea_fk ON lab_notes(idea_id);
