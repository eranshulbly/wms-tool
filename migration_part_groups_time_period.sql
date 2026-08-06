-- =============================================================================
-- part_groups: drop `month`, rename `period` -> `time_period`
-- =============================================================================
-- `month` stored the period's name ('July') next to `period` = 2026-07-01, so it
-- duplicated a value the date already carries and nothing read it back.
--
-- The app applies this automatically on boot via _migrate_part_groups_period() in
-- api/shared/db_manager.py. This file is the manual equivalent, for running against
-- a database by hand.
--
-- RENAME COLUMN rewrites uq_period_part and idx_period onto the new column name by
-- itself. The index names are intentionally left unchanged so a migrated database
-- matches what a fresh install builds from the registry DDL.
--
-- Requires MySQL 8.0+ (RENAME COLUMN). Both statements are guarded, so re-running
-- this file is a no-op.
-- =============================================================================

SET @db := DATABASE();

-- Drop `month` only if it is still there.
SET @sql := (
    SELECT IF(COUNT(*) > 0,
              'ALTER TABLE part_groups DROP COLUMN `month`',
              'SELECT ''part_groups.month already dropped'' AS note')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups' AND COLUMN_NAME = 'month'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Rename only when `period` exists and `time_period` does not, so a half-applied
-- or repeated run does nothing.
SET @sql := (
    SELECT IF(
        SUM(COLUMN_NAME = 'period') = 1 AND SUM(COLUMN_NAME = 'time_period') = 0,
        'ALTER TABLE part_groups RENAME COLUMN `period` TO `time_period`',
        'SELECT ''part_groups.time_period already in place'' AS note')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'part_groups'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
