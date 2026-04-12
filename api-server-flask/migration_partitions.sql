-- =============================================================================
-- Migration: Convert growing tables to monthly RANGE COLUMNS partitions
-- Target DB : warehouse_management
-- Safe to run on a live database (uses SET FOREIGN_KEY_CHECKS=0 so it won't
-- block on FK references during structural changes).
--
-- Run order matters — child tables are converted after their parents.
--
-- Usage:
--   mysql -u root -p warehouse_management < migration_partitions.sql
--
-- After running:
--   python -m api.partition_manager list     ← verify partitions
--   python -m api.partition_manager ensure   ← make sure current month exists
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;
SET SQL_MODE = '';

-- ─────────────────────────────────────────────────────────────────────────────
-- Helper procedure: drops all FK constraints on a given table.
-- We cannot inline DROP FOREIGN KEY without knowing generated constraint names,
-- so we use INFORMATION_SCHEMA to discover and drop them dynamically.
-- ─────────────────────────────────────────────────────────────────────────────

DROP PROCEDURE IF EXISTS drop_all_fks;
DROP PROCEDURE IF EXISTS drop_idx_if_exists;

DELIMITER $$

-- Drops all FK constraints on a given table dynamically
CREATE PROCEDURE drop_all_fks(IN p_table VARCHAR(64))
BEGIN
    DECLARE done  INT DEFAULT 0;
    DECLARE fk    VARCHAR(128);
    DECLARE cur   CURSOR FOR
        SELECT CONSTRAINT_NAME
        FROM   information_schema.TABLE_CONSTRAINTS
        WHERE  TABLE_SCHEMA    = DATABASE()
          AND  TABLE_NAME      = p_table
          AND  CONSTRAINT_TYPE = 'FOREIGN KEY';
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;

    OPEN cur;
    read_loop: LOOP
        FETCH cur INTO fk;
        IF done THEN LEAVE read_loop; END IF;
        SET @sql = CONCAT('ALTER TABLE `', p_table, '` DROP FOREIGN KEY `', fk, '`');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END LOOP;
    CLOSE cur;
END$$

-- Drops a named index only if it exists (safe for re-runs)
CREATE PROCEDURE drop_idx_if_exists(IN p_table VARCHAR(64), IN p_index VARCHAR(64))
BEGIN
    DECLARE cnt INT DEFAULT 0;
    SELECT COUNT(*) INTO cnt
    FROM   information_schema.STATISTICS
    WHERE  TABLE_SCHEMA = DATABASE()
      AND  TABLE_NAME   = p_table
      AND  INDEX_NAME   = p_index;
    IF cnt > 0 THEN
        SET @sql = CONCAT('ALTER TABLE `', p_table, '` DROP INDEX `', p_index, '`');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$

DELIMITER ;

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 1: Drop ALL foreign keys across every affected table FIRST.
-- SET FOREIGN_KEY_CHECKS=0 does not bypass the restriction on DROP PRIMARY KEY
-- when other tables hold FK references to it — FKs on child tables must be
-- explicitly dropped before the parent PK can be changed.
-- ─────────────────────────────────────────────────────────────────────────────

-- Child tables that reference potential_order
CALL drop_all_fks('potential_order_product');
CALL drop_all_fks('order_state_history');
CALL drop_all_fks('box_product');
CALL drop_all_fks('invoice');
CALL drop_all_fks('order');

-- Child tables that reference `order`
CALL drop_all_fks('order_box');
CALL drop_all_fks('order_product');

-- Tables with FKs to reference data (warehouse, company, dealer, users)
CALL drop_all_fks('upload_batches');
CALL drop_all_fks('potential_order');

-- ─────────────────────────────────────────────────────────────────────────────
-- PHASE 2: Restructure PKs and add partitions table by table.
-- All dates use current window: archive < 2025-12-01, active window Dec 25–Apr 26.
-- Update partition dates if running in a different month.
-- ─────────────────────────────────────────────────────────────────────────────

-- ══════════════════════════════════════════════════════════════════════════════
-- 1. potential_order
-- ══════════════════════════════════════════════════════════════════════════════

-- Drop unique index on original_order_id (can't coexist with partition key not in it)
CALL drop_idx_if_exists('potential_order', 'idx_original_order_id');

-- Rebuild primary key to include partition column
ALTER TABLE potential_order
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (potential_order_id, created_at);

-- Add partition
ALTER TABLE potential_order
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 2. potential_order_product
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE potential_order_product
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (potential_order_product_id, created_at);

ALTER TABLE potential_order_product
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 3. `order`  (backticks required — reserved word)
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE `order`
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (order_id, created_at);

ALTER TABLE `order`
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 4. order_state_history  (partition column: changed_at)
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE order_state_history
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (order_state_history_id, changed_at);

ALTER TABLE order_state_history
    PARTITION BY RANGE COLUMNS (changed_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 5. order_box
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE order_box
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (box_id, created_at);

ALTER TABLE order_box
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 6. order_product
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE order_product
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (order_product_id, created_at);

ALTER TABLE order_product
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 7. box_product
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE box_product
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (box_product_id, created_at);

ALTER TABLE box_product
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 8. invoice
-- ══════════════════════════════════════════════════════════════════════════════

-- Drop index on invoice_number before restructuring
CALL drop_idx_if_exists('invoice', 'idx_invoice_number');

ALTER TABLE invoice
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (invoice_id, created_at);

ALTER TABLE invoice
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- Re-add as a regular (non-unique) index so lookups by invoice_number still work
ALTER TABLE invoice
    ADD INDEX idx_invoice_number (invoice_number);

-- ══════════════════════════════════════════════════════════════════════════════
-- 9. upload_batches  (partition column: uploaded_at)
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE upload_batches
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (id, uploaded_at);

ALTER TABLE upload_batches
    PARTITION BY RANGE COLUMNS (uploaded_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ══════════════════════════════════════════════════════════════════════════════
-- 10. jwt_token_blocklist
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE jwt_token_blocklist
    DROP PRIMARY KEY,
    ADD  PRIMARY KEY (id, created_at);

ALTER TABLE jwt_token_blocklist
    PARTITION BY RANGE COLUMNS (created_at) (
        PARTITION p_archive  VALUES LESS THAN ('2025-12-01'),
        PARTITION p_2025_12  VALUES LESS THAN ('2026-01-01'),
        PARTITION p_2026_01  VALUES LESS THAN ('2026-02-01'),
        PARTITION p_2026_02  VALUES LESS THAN ('2026-03-01'),
        PARTITION p_2026_03  VALUES LESS THAN ('2026-04-01'),
        PARTITION p_2026_04  VALUES LESS THAN ('2026-05-01'),
        PARTITION p_future   VALUES LESS THAN (MAXVALUE)
    );

-- ─────────────────────────────────────────────────────────────────────────────
-- Cleanup
-- ─────────────────────────────────────────────────────────────────────────────

DROP PROCEDURE IF EXISTS drop_all_fks;
DROP PROCEDURE IF EXISTS drop_idx_if_exists;

SET FOREIGN_KEY_CHECKS = 1;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verify: show partition counts for all converted tables
-- ─────────────────────────────────────────────────────────────────────────────

SELECT
    TABLE_NAME,
    PARTITION_NAME,
    TABLE_ROWS,
    PARTITION_DESCRIPTION AS upper_bound
FROM information_schema.PARTITIONS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
      'potential_order','potential_order_product','order',
      'order_state_history','order_box','order_product',
      'box_product','invoice','upload_batches','jwt_token_blocklist'
  )
  AND PARTITION_NAME IS NOT NULL
ORDER BY TABLE_NAME, PARTITION_ORDINAL_POSITION;
