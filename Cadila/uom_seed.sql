-- ==========================================================================
-- uom seed -- the unit vocabulary used by product_uom
--
--   mysql -u <user> -p <schema> < uom_seed.sql
--
-- Idempotent: INSERT IGNORE adds missing codes and never overwrites or removes
-- an existing row, so it is safe to run any number of times -- including after
-- the backend has already seeded the table on boot (db_manager.seed_default_uoms).
--
-- Creates the table too, with the same definition the app registers
-- (catalog/schema.py), so it also works on a database the app has never started
-- against.
-- ==========================================================================

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS uom (
    uom_code   VARCHAR(16) NOT NULL,
    name       VARCHAR(64) NOT NULL,
    uom_type   VARCHAR(16) NOT NULL DEFAULT 'count',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uom_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO uom (uom_code, name, uom_type) VALUES
  ('BOTTLE', 'Bottle', 'count'),
  ('BOX', 'Box', 'count'),
  ('CASE', 'Case', 'count'),
  ('PCS', 'Pieces', 'count'),
  ('SACHET', 'Sachet', 'count'),
  ('STRIP', 'Strip', 'count'),
  ('TAB', 'Tablet', 'count'),
  ('TUBE', 'Tube', 'count'),
  ('UNIT', 'Unit', 'count'),
  ('VIAL', 'Vial', 'count');

-- Verification -- expect 10 rows
SELECT uom_code, name, uom_type FROM uom ORDER BY uom_code;
