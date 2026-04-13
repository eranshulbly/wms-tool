-- ============================================================
-- Supply Sheet Feature Migration
-- Run once against the target database.
-- ============================================================

-- 1. Add town column to dealer table
ALTER TABLE dealer
    ADD COLUMN town VARCHAR(100) DEFAULT NULL
    AFTER dealer_code;

-- 2. Supply sheet counter — one row per warehouse, auto-incremented per sheet
CREATE TABLE IF NOT EXISTS supply_sheet_counter (
    counter_id   INT          NOT NULL AUTO_INCREMENT,
    warehouse_id INT          NOT NULL,
    counter      INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (counter_id),
    UNIQUE KEY uq_warehouse (warehouse_id),
    CONSTRAINT fk_ssc_warehouse FOREIGN KEY (warehouse_id)
        REFERENCES warehouse (warehouse_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
