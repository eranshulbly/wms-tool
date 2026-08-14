-- =============================================================================
-- Product packaging ladder, dated pricing, and per-industry attributes.
--
-- Run once:  mysql -h <host> -u <user> -p <db> < migration_product_uom_pricing.sql
-- Safe to re-run: every statement is guarded, so a second run is a no-op.
--
-- This migration is ADDITIVE ONLY. It creates five tables and adds one nullable
-- column; it alters no existing data and drops nothing. A product with no
-- product_uom rows keeps behaving as a single-unit product, which is what every
-- row in `product` is today — so running this changes no behaviour on its own.
--
-- The application performs the same steps at boot (schema registry + the
-- _migrate_product_gst_percent / seed_default_uoms functions in
-- api/shared/db_manager.py). This file exists so the change can be applied and
-- reviewed ahead of a deploy, on a server where the app has not restarted yet.
-- =============================================================================

-- ── 1. Unit vocabulary ───────────────────────────────────────────────────────
-- Names only. NOT a conversion table: "1 kg = 1000 g" is universal, but
-- "1 box = 30 strips" is true of one product, so factors live in product_uom.
CREATE TABLE IF NOT EXISTS uom (
    uom_code   VARCHAR(16) NOT NULL,
    name       VARCHAR(64) NOT NULL,
    uom_type   VARCHAR(16) NOT NULL DEFAULT 'count',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uom_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO uom (uom_code, name, uom_type) VALUES
    ('PCS',    'Pieces', 'count'),
    ('UNIT',   'Unit',   'count'),
    ('TAB',    'Tablet', 'count'),
    ('STRIP',  'Strip',  'count'),
    ('BOX',    'Box',    'count'),
    ('CASE',   'Case',   'count'),
    ('BOTTLE', 'Bottle', 'count'),
    ('VIAL',   'Vial',   'count'),
    ('TUBE',   'Tube',   'count'),
    ('SACHET', 'Sachet', 'count');

-- ── 2. The packaging ladder ──────────────────────────────────────────────────
-- One row per rung. factor_to_base is ABSOLUTE (a case of 66 boxes of 30 strips
-- of 10 tabs stores 19800), so any conversion is a single multiply and nothing
-- has to walk the ladder. The three flags are independent: a rung can be
-- counted but never ordered (tablets), be the one prices are quoted against,
-- and be the one stock is held in.
CREATE TABLE IF NOT EXISTS product_uom (
    product_uom_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id     INT NOT NULL,
    uom_code       VARCHAR(16) NOT NULL,
    factor_to_base DECIMAL(18,6) NOT NULL DEFAULT 1,
    level_no       TINYINT NOT NULL DEFAULT 0,
    label          VARCHAR(64) NULL,
    is_order_unit  TINYINT(1) NOT NULL DEFAULT 0,
    is_price_unit  TINYINT(1) NOT NULL DEFAULT 0,
    is_stock_unit  TINYINT(1) NOT NULL DEFAULT 0,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_product_uom (product_id, uom_code),
    INDEX idx_puom_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 3. Dated prices ──────────────────────────────────────────────────────────
-- price_type is a ROW, not a column, so a company needing a fifth kind of price
-- adds rows rather than a migration. Dating is not optional: the supplier's file
-- is titled "PRICE LIST - JUNE'26", and prices held on `product` would mean
-- uploading July silently re-prices every order already placed.
CREATE TABLE IF NOT EXISTS product_price (
    product_price_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id     INT NOT NULL,
    company_id     INT NOT NULL,
    price_uom_code VARCHAR(16) NOT NULL,
    price_type     VARCHAR(16) NOT NULL,
    amount         DECIMAL(12,4) NOT NULL,
    price_list     VARCHAR(32) NULL,
    effective_from DATE NOT NULL,
    effective_to   DATE NULL,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_product_price (product_id, company_id, price_uom_code, price_type, effective_from),
    INDEX idx_pprice_lookup (product_id, effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 4. Per-industry attributes ───────────────────────────────────────────────
-- What is real for one industry and meaningless for another (composition, shelf
-- life). Defined as data so a new attribute never needs a schema change — the
-- alternative is another `litres_per_unit`: one company's column sitting NULL on
-- every other company's products.
CREATE TABLE IF NOT EXISTS attribute_def (
    attribute_id  INT AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(48) NOT NULL,
    label         VARCHAR(96) NOT NULL,
    data_type     VARCHAR(16) NOT NULL DEFAULT 'text',
    company_id    INT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_attribute_def (code, company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_attribute (
    product_id   INT NOT NULL,
    attribute_id INT NOT NULL,
    value_text   VARCHAR(512) NULL,
    value_num    DECIMAL(18,6) NULL,
    value_date   DATE NULL,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (product_id, attribute_id),
    INDEX idx_pattr_attr (attribute_id, value_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 5. product.gst_percent ───────────────────────────────────────────────────
-- A core column, not an attribute: every company selling in India has a GST rate,
-- and it belongs beside hsn_code, which determines it. MySQL has no
-- "ADD COLUMN IF NOT EXISTS", so this is guarded through information_schema to
-- keep the script re-runnable.
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME   = 'product'
       AND COLUMN_NAME  = 'gst_percent');

SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE product ADD COLUMN gst_percent DECIMAL(5,2) NULL AFTER hsn_code',
    'SELECT ''product.gst_percent already present — skipped'' AS note');

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 6. Verification ──────────────────────────────────────────────────────────
SELECT 'uom'               AS table_name, COUNT(*) AS rows_present FROM uom
UNION ALL SELECT 'product_uom',       COUNT(*) FROM product_uom
UNION ALL SELECT 'product_price',     COUNT(*) FROM product_price
UNION ALL SELECT 'attribute_def',     COUNT(*) FROM attribute_def
UNION ALL SELECT 'product_attribute', COUNT(*) FROM product_attribute;

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
  FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE()
   AND TABLE_NAME   = 'product'
   AND COLUMN_NAME  = 'gst_percent';

-- ── Rollback (only while the tables are still empty) ─────────────────────────
-- DROP TABLE IF EXISTS product_attribute, attribute_def, product_price, product_uom, uom;
-- ALTER TABLE product DROP COLUMN gst_percent;
