-- =============================================================================
-- Migration: drop the app-only columns from potential_order.
--
-- The mobile app used to store its orders in potential_order and stamped these
-- columns on them. App orders now live in their own submitted_* tables (see
-- migration_v2_api.sql), so potential_order belongs solely to the warehouse app,
-- which never used these columns — it identifies orders by original_order_id and
-- keeps order numbers on the separate `order` table.
--
--   order_number  (+ its lookup index idx_po_order_number)
--   created_by
--
-- Idempotent and guarded (drops only what exists), so it is safe to re-run and safe
-- on a fresh DB where migration_v2_api.sql never added these columns.
--
-- Note: potential_order is RANGE-partitioned by created_at, but neither column is in
-- the primary key or the partitioning expression, so DROP COLUMN is unaffected.
-- =============================================================================

DROP PROCEDURE IF EXISTS _drop_col;
DROP PROCEDURE IF EXISTS _drop_idx;
DELIMITER //
CREATE PROCEDURE _drop_idx(IN tbl VARCHAR(64), IN idx VARCHAR(64))
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND INDEX_NAME = idx) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP INDEX `', idx, '`');
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
CREATE PROCEDURE _drop_col(IN tbl VARCHAR(64), IN col VARCHAR(64))
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` DROP COLUMN `', col, '`');
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
DELIMITER ;

-- Drop the index before its column.
CALL _drop_idx('potential_order', 'idx_po_order_number');
CALL _drop_col('potential_order', 'order_number');
CALL _drop_col('potential_order', 'created_by');

DROP PROCEDURE IF EXISTS _drop_col;
DROP PROCEDURE IF EXISTS _drop_idx;
