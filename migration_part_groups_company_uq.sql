-- =============================================================================
-- part_groups: widen uq_period_part onto company_id
-- =============================================================================
-- The key was (time_period, part_number), but the monthly upload replaces a period
-- with:
--
--     DELETE FROM part_groups WHERE time_period = ? AND company_id = ?
--
-- Those two grains disagree. One company loading a period it has never uploaded
-- before still collides with ANOTHER company's rows for the same period and part,
-- and its own scoped delete cannot clear them because they are not its rows. The
-- symptom is a duplicate-key error on a period the operator knows they never
-- loaded:
--
--     (1062, "Duplicate entry '2026-08-01-K40405AACNB00S'
--             for key 'part_groups.uq_period_part'")
--
-- Keying on company_id puts the constraint at the same grain the loader replaces at.
--
-- The app applies this automatically on boot via _migrate_part_groups_company_uq()
-- in api/shared/db_manager.py. This file is the manual equivalent, for running
-- against a database by hand.
--
-- Adding a column to a unique key only ever relaxes it, so every row the old key
-- accepted is still accepted — this cannot fail on existing data.
--
-- Rows predating the tenant column have company_id NULL. MySQL treats every NULL in
-- a unique index as distinct, so those legacy rows fall out of this key. That is
-- consistent with the loader, whose company-scoped delete cannot see them either;
-- they want a one-off cleanup rather than a constraint. To find them:
--
--     SELECT time_period, COUNT(*) FROM part_groups
--      WHERE company_id IS NULL GROUP BY time_period;
--
-- Requires MySQL 8.0+. Both statements are guarded, so re-running this file is a
-- no-op, and it is skipped entirely until company_id exists (added by
-- _migrate_company_id / the _COMPANY_ID_TABLES manifest).
-- =============================================================================

SET @db := DATABASE();

-- Drop the narrow key, but only when company_id exists, the key is present, and it
-- is not already widened.
SET @sql := (
    SELECT IF(
        (SELECT COUNT(*) FROM information_schema.COLUMNS
          WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
            AND COLUMN_NAME = 'company_id') = 1
        AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
            AND INDEX_NAME = 'uq_period_part') > 0
        AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
            AND INDEX_NAME = 'uq_period_part' AND COLUMN_NAME = 'company_id') = 0,
        'ALTER TABLE part_groups DROP INDEX uq_period_part',
        'SELECT ''part_groups.uq_period_part: nothing to drop'' AS note')
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Re-add it keyed on the company. Guarded on the key being absent, which is true
-- either because the statement above just dropped it or because a previous run got
-- this far and stopped.
SET @sql := (
    SELECT IF(
        (SELECT COUNT(*) FROM information_schema.COLUMNS
          WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
            AND COLUMN_NAME = 'company_id') = 1
        AND (SELECT COUNT(*) FROM information_schema.STATISTICS
          WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
            AND INDEX_NAME = 'uq_period_part') = 0,
        'ALTER TABLE part_groups ADD UNIQUE KEY uq_period_part (company_id, time_period, part_number)',
        'SELECT ''part_groups.uq_period_part already in place'' AS note')
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
