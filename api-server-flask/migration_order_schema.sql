-- =============================================================================
-- Migration: Unified Dealer Entity + New Order/Invoice Upload Format
-- Run against warehouse_management database IN THE ORDER LISTED BELOW.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- STEP 1: Clear old invoice data (old format is incompatible with new columns)
-- -----------------------------------------------------------------------------
DELETE FROM invoice;

-- -----------------------------------------------------------------------------
-- STEP 2: Add dealer_code to dealer table
-- -----------------------------------------------------------------------------
ALTER TABLE dealer
    ADD COLUMN dealer_code VARCHAR(50) NULL AFTER name,
    ADD UNIQUE INDEX idx_dealer_code (dealer_code);

-- -----------------------------------------------------------------------------
-- STEP 3: Migrate customer_route_mappings → dealer FK
--   a) Add dealer_id column
--   b) For each existing mapping, find or create a dealer record
--   c) Populate dealer_id, then drop old columns
-- -----------------------------------------------------------------------------

-- 3a. Add dealer_id column
ALTER TABLE customer_route_mappings
    ADD COLUMN dealer_id INT NULL AFTER mapping_id,
    ADD CONSTRAINT fk_crm_dealer FOREIGN KEY (dealer_id) REFERENCES dealer(dealer_id);

-- 3b. For each existing mapping, insert a dealer (or match by dealer_code)
--     and link it.
INSERT INTO dealer (name, dealer_code, created_at, updated_at)
SELECT DISTINCT
    customer_name,
    customer_code,
    NOW(),
    NOW()
FROM customer_route_mappings
WHERE customer_code NOT IN (SELECT dealer_code FROM dealer WHERE dealer_code IS NOT NULL)
  AND customer_code IS NOT NULL
  AND customer_code != '';

-- 3c. Populate dealer_id from the dealer table matched by dealer_code
UPDATE customer_route_mappings crm
JOIN dealer d ON d.dealer_code = crm.customer_code
SET crm.dealer_id = d.dealer_id
WHERE crm.dealer_id IS NULL;

-- 3d. Add UNIQUE constraint on dealer_id (one route mapping per dealer)
ALTER TABLE customer_route_mappings
    ADD UNIQUE INDEX idx_crm_dealer_id (dealer_id);

-- 3e. Drop old columns
ALTER TABLE customer_route_mappings
    DROP COLUMN customer_code,
    DROP COLUMN customer_name;

-- -----------------------------------------------------------------------------
-- STEP 4: Add new columns to potential_order + enforce unique order IDs
-- -----------------------------------------------------------------------------
ALTER TABLE potential_order
    ADD UNIQUE INDEX idx_original_order_id (original_order_id);

ALTER TABLE potential_order
    ADD COLUMN b2b_po_number    VARCHAR(100) NULL AFTER original_order_id,
    ADD COLUMN order_type       VARCHAR(20)  NULL AFTER b2b_po_number,
    ADD COLUMN vin_number       VARCHAR(100) NULL AFTER order_type,
    ADD COLUMN shipping_address TEXT         NULL AFTER vin_number,
    ADD COLUMN source_created_by VARCHAR(100) NULL AFTER shipping_address,
    ADD COLUMN purchaser_sap_code VARCHAR(50) NULL AFTER source_created_by,
    ADD COLUMN purchaser_name   VARCHAR(255) NULL AFTER purchaser_sap_code;

-- -----------------------------------------------------------------------------
-- STEP 5: Update invoice table — add dealer_id FK + new columns, drop old ones
-- -----------------------------------------------------------------------------

-- 5a. Add dealer_id FK
ALTER TABLE invoice
    ADD COLUMN dealer_id INT NULL AFTER company_id,
    ADD CONSTRAINT fk_invoice_dealer FOREIGN KEY (dealer_id) REFERENCES dealer(dealer_id);

-- 5b. Enforce unique invoice numbers
ALTER TABLE invoice
    ADD UNIQUE INDEX idx_invoice_number (invoice_number);

-- 5c. Add new columns from new invoice CSV format
ALTER TABLE invoice
    ADD COLUMN order_date                  DATETIME      NULL AFTER original_order_id,
    ADD COLUMN account_tin                 VARCHAR(50)   NULL AFTER order_date,
    ADD COLUMN cash_customer_name          VARCHAR(255)  NULL AFTER account_tin,
    ADD COLUMN contact_first_name          VARCHAR(100)  NULL AFTER cash_customer_name,
    ADD COLUMN contact_last_name           VARCHAR(100)  NULL AFTER contact_first_name,
    ADD COLUMN round_off_amount            DECIMAL(10,2) NULL AFTER contact_last_name,
    ADD COLUMN invoice_round_off_amount    DECIMAL(10,2) NULL AFTER round_off_amount,
    ADD COLUMN short_amount                DECIMAL(10,2) NULL AFTER invoice_round_off_amount,
    ADD COLUMN realized_amount             DECIMAL(10,2) NULL AFTER short_amount,
    ADD COLUMN hmcgl_card_no               VARCHAR(100)  NULL AFTER realized_amount,
    ADD COLUMN campaign                    VARCHAR(100)  NULL AFTER hmcgl_card_no,
    ADD COLUMN b2b_purchase_order_number   VARCHAR(100)  NULL AFTER campaign,
    ADD COLUMN b2b_order_type              VARCHAR(50)   NULL AFTER b2b_purchase_order_number,
    ADD COLUMN invoice_header_type         VARCHAR(50)   NULL AFTER b2b_order_type,
    ADD COLUMN packaging_forwarding_charges DECIMAL(10,2) NULL AFTER invoice_header_type,
    ADD COLUMN tax_on_pf                   DECIMAL(10,2) NULL AFTER packaging_forwarding_charges,
    ADD COLUMN type_of_tax_pf              VARCHAR(50)   NULL AFTER tax_on_pf,
    ADD COLUMN irn_number                  VARCHAR(100)  NULL AFTER type_of_tax_pf,
    ADD COLUMN irn_status                  VARCHAR(50)   NULL AFTER irn_number,
    ADD COLUMN ack_number                  VARCHAR(100)  NULL AFTER irn_status,
    ADD COLUMN ack_date                    DATETIME      NULL AFTER ack_number,
    ADD COLUMN credit_note_number          VARCHAR(100)  NULL AFTER ack_date,
    ADD COLUMN irn_cancel                  VARCHAR(100)  NULL AFTER credit_note_number,
    ADD COLUMN irn_status_cancel           VARCHAR(50)   NULL AFTER irn_cancel,
    ADD COLUMN ack_number_cancel           VARCHAR(100)  NULL AFTER irn_status_cancel,
    ADD COLUMN ack_date_cancel             DATETIME      NULL AFTER ack_number_cancel;

-- 5d. Drop old dealer/customer columns and location_code
ALTER TABLE invoice
    DROP FOREIGN KEY fk_invoice_dealer,  -- temporarily drop to allow column drops
    DROP COLUMN dealer_code,
    DROP COLUMN customer_code,
    DROP COLUMN customer_name,
    DROP COLUMN location_code;

-- Re-add FK after column drops
ALTER TABLE invoice
    ADD CONSTRAINT fk_invoice_dealer FOREIGN KEY (dealer_id) REFERENCES dealer(dealer_id);

-- -----------------------------------------------------------------------------
-- STEP 6: Rename order states + update potential_order.status values
-- Run Completed → Dispatch Ready FIRST to avoid collision
-- -----------------------------------------------------------------------------
UPDATE potential_order SET status = 'Dispatch Ready'  WHERE status = 'Completed';
UPDATE potential_order SET status = 'Invoice Ready'   WHERE status = 'Dispatch Ready'
  AND status != 'Dispatch Ready';  -- guard against double-update

-- Safer two-step via temp value:
UPDATE potential_order SET status = '_tmp_invoice_ready' WHERE status = 'Dispatch Ready';
UPDATE potential_order SET status = 'Invoice Ready'       WHERE status = '_tmp_invoice_ready';

UPDATE order_state
    SET state_name  = 'Invoice Ready',
        description = 'Order packed and ready for invoicing'
WHERE state_name = 'Dispatch Ready';

UPDATE order_state
    SET state_name  = 'Dispatch Ready',
        description = 'Invoices uploaded, order ready for physical dispatch'
WHERE state_name = 'Completed';

INSERT INTO order_state (state_name, description)
VALUES ('Completed', 'Order physically dispatched from warehouse');

-- Also update role_order_states table which stores state names
UPDATE role_order_states SET state_name = 'Invoice Ready'  WHERE state_name = 'Dispatch Ready';
UPDATE role_order_states SET state_name = 'Dispatch Ready' WHERE state_name = 'Completed';
-- Insert Completed for all roles that had Dispatch Ready (now Invoice Ready)
INSERT IGNORE INTO role_order_states (role_id, state_name)
SELECT role_id, 'Completed' FROM role_order_states WHERE state_name = 'Dispatch Ready';
