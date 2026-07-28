-- =============================================================================
-- Migration: DMS-input two-stage workflow on submitted_orders.
--
-- Splits the app-order → DMS pipeline into two tabs, driven by a new dms_status
-- column (independent of `status`, which the mobile app keys on):
--
--   submitted / re_submitted  -> "Submitted Orders" tab (awaiting part-convertor upload)
--   ready / done              -> "Download DMS input file" tab (ready / already downloaded)
--
-- reject_note holds the reason shown when an order is rejected back to Submitted.
-- Idempotent and guarded — safe to re-run.
-- =============================================================================

DROP PROCEDURE IF EXISTS _add_col;
DROP PROCEDURE IF EXISTS _add_idx;
DELIMITER //
CREATE PROCEDURE _add_col(IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl TEXT)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND COLUMN_NAME = col) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN `', col, '` ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
CREATE PROCEDURE _add_idx(IN tbl VARCHAR(64), IN idx VARCHAR(64), IN ddl TEXT)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl AND INDEX_NAME = idx) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
DELIMITER ;

CALL _add_col('submitted_orders', 'dms_status',  "VARCHAR(20) NOT NULL DEFAULT 'submitted'");
CALL _add_col('submitted_orders', 'reject_note', 'TEXT NULL');
CALL _add_idx('submitted_orders', 'idx_so_dms_status', 'INDEX idx_so_dms_status (dms_status)');

DROP PROCEDURE IF EXISTS _add_col;
DROP PROCEDURE IF EXISTS _add_idx;

-- Backfill: an order that already has line items is ready to download (itemised orders,
-- or photo orders whose part convertor was uploaded earlier); the rest await upload.
-- Only touches rows still at the default 'submitted' so it won't clobber progress on re-run.
UPDATE submitted_orders so
SET dms_status = 'ready'
WHERE dms_status = 'submitted'
  AND EXISTS (SELECT 1 FROM submitted_order_products p
              WHERE p.submitted_order_id = so.submitted_order_id);
