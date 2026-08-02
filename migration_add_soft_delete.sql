-- Run this ONCE against your existing Supabase/Postgres database.
-- app.main.startup() only calls Base.metadata.create_all(), which creates
-- NEW tables but does NOT add new columns to tables that already exist.
-- These two columns are required for the soft-delete bug fix in
-- sites.py and expenses.py.

ALTER TABLE sites ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
ALTER TABLE expenses ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;

-- Backfill safety (in case DEFAULT FALSE didn't apply to old rows on some PG versions)
UPDATE sites SET is_deleted = FALSE WHERE is_deleted IS NULL;
UPDATE expenses SET is_deleted = FALSE WHERE is_deleted IS NULL;
