-- =============================================================================
-- Migration: Invoice Bypass Order Types + Invoice-Submitted Flag
-- =============================================================================
-- Run against warehouse_management database.
-- Safe to run on a fresh DB or an existing one.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- STEP 1: Add invoice_submitted flag to potential_order
--   • invoice_submitted = 1 means an invoice file was uploaded for this order
--     but the order was NOT in an eligible state (Packed) at the time, so the
--     invoice record was not yet created.  When the user later moves the order
--     to Packed, the backend auto-transitions it to Invoiced and clears the flag.
-- -----------------------------------------------------------------------------
ALTER TABLE potential_order
    ADD COLUMN invoice_submitted TINYINT(1) NOT NULL DEFAULT 0 AFTER status,
    ADD INDEX  idx_po_invoice_submitted (invoice_submitted);

-- -----------------------------------------------------------------------------
-- STEP 2: Create invoice_processing_config table
--   Generic key-value config table for invoice processing rules.
--   Designed for extensibility: add new config_keys in the future without
--   schema changes.
--
--   Current keys:
--     bypass_order_type  — order_type values that skip the Packed prerequisite
--                          and move directly to Invoiced on invoice upload.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_processing_config (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    config_key   VARCHAR(50)  NOT NULL COMMENT 'Rule category, e.g. bypass_order_type',
    config_value VARCHAR(100) NOT NULL COMMENT 'Rule value, e.g. ZGOI',
    description  TEXT         NULL,
    is_active    TINYINT(1)   NOT NULL DEFAULT 1,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_config_key_value (config_key, config_value),
    INDEX        idx_config_key_active (config_key, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- STEP 3: Seed initial bypass order type
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO invoice_processing_config (config_key, config_value, description)
VALUES (
    'bypass_order_type',
    'ZGOI',
    'ZGOI orders bypass the Packed prerequisite — invoice upload moves them directly to Invoiced regardless of current state.'
);
