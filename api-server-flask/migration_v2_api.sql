-- =============================================================================
-- Migration: support the ported wms-v2-backend API (/api/v1/*) on this schema.
--
-- See docs/V2_API_PORT.md for the full design. Everything here is ADDITIVE and
-- IDEMPOTENT (safe to re-run) — no column is renamed or dropped, so the existing
-- web app is unaffected.
--
--   1. Unified RBAC        : permissions, role_permissions, user_roles, refresh_tokens
--   2. Catalog             : categories + SKU columns on product
--   3. Dealer / warehouse   : the extra fields v2 exposes
--   4. Orders              : v2 order fields + line snapshots (ONE shared lifecycle)
--   5. Seeds               : new order states, permission vocabulary, role/user grants
-- =============================================================================

-- ---- helpers: idempotent DDL (MySQL has no ADD COLUMN IF NOT EXISTS) --------
DROP PROCEDURE IF EXISTS _add_col;
DROP PROCEDURE IF EXISTS _add_idx;
DROP PROCEDURE IF EXISTS _add_fk;
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
-- A FK reuses an existing covering index instead of creating one under its own name,
-- so _add_idx (which checks STATISTICS) can't guard it. Check TABLE_CONSTRAINTS instead.
CREATE PROCEDURE _add_fk(IN tbl VARCHAR(64), IN fk VARCHAR(64), IN ddl TEXT)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
                     AND CONSTRAINT_NAME = fk AND CONSTRAINT_TYPE = 'FOREIGN KEY') THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
DELIMITER ;

-- ---- 1. Unified RBAC --------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    permission_id INT AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(100) NOT NULL UNIQUE,
    description   VARCHAR(255) NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    INDEX idx_rp_permission (permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- a user may hold several roles (e.g. a web role AND a mobile role)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     INT NOT NULL,
    role_id     INT NOT NULL,
    assigned_by INT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    INDEX idx_ur_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  VARCHAR(255) NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    revoked_at  DATETIME NULL,
    user_agent  VARCHAR(255) NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_refresh_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---- 2. Catalog ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    parent_id   INT NULL,
    description VARCHAR(255) NULL,
    is_active   TINYINT(1) NOT NULL DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_categories_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- product == v2 "SKU"; product_string is the sku_code identity
CALL _add_col('product', 'nickname',    'VARCHAR(200) NULL');
CALL _add_col('product', 'category_id', 'INT NULL');
CALL _add_col('product', 'uom',         'VARCHAR(20) NULL');
CALL _add_col('product', 'size',        'VARCHAR(100) NULL');
CALL _add_col('product', 'weight',      'DECIMAL(10,3) NULL');
CALL _add_col('product', 'barcode',     'VARCHAR(100) NULL');
CALL _add_col('product', 'hsn_code',    'VARCHAR(20) NULL');
CALL _add_col('product', 'is_active',   'TINYINT(1) NOT NULL DEFAULT 1');
CALL _add_idx('product', 'uq_product_string',  'UNIQUE INDEX uq_product_string (product_string)');
CALL _add_idx('product', 'uq_product_barcode', 'UNIQUE INDEX uq_product_barcode (barcode)');

-- ---- 3. Dealer / warehouse -------------------------------------------------
CALL _add_col('dealer', 'email',   'VARCHAR(255) NULL');
CALL _add_col('dealer', 'phone',   'VARCHAR(32) NULL');
CALL _add_col('dealer', 'town',    'VARCHAR(100) NULL');
CALL _add_col('dealer', 'address', 'TEXT NULL');
CALL _add_col('dealer', 'gstin',   'VARCHAR(20) NULL');
CALL _add_col('dealer', 'status',  "VARCHAR(20) NOT NULL DEFAULT 'active'");
-- Geo pin for the dealer (same DECIMAL(9,6) convention as potential_order lat/long).
CALL _add_col('dealer', 'latitude',  'DECIMAL(9,6) NULL');
CALL _add_col('dealer', 'longitude', 'DECIMAL(9,6) NULL');
-- Date the dealer became active (i.e. was onboarded). Added without a default so
-- existing rows can be backfilled from created_at; the default is set immediately
-- after so every future insert auto-stamps it.
CALL _add_col('dealer', 'activated_on', 'DATETIME NULL');
UPDATE dealer SET activated_on = created_at WHERE activated_on IS NULL;
-- MODIFY (not ALTER COLUMN SET DEFAULT — MySQL rejects a function there). Preserves
-- existing values; only sets the default so future inserts auto-stamp.
ALTER TABLE dealer MODIFY COLUMN activated_on DATETIME NULL DEFAULT CURRENT_TIMESTAMP;

CALL _add_col('warehouse', 'code',      'VARCHAR(20) NULL');
CALL _add_col('warehouse', 'is_active', 'TINYINT(1) NOT NULL DEFAULT 1');
CALL _add_idx('warehouse', 'uq_warehouse_code', 'UNIQUE INDEX uq_warehouse_code (code)');
UPDATE warehouse SET code = CONCAT('WH', warehouse_id) WHERE code IS NULL OR code = '';

-- ---- 4. Orders (one shared lifecycle; no separate status column) -----------
-- order_number / created_by are NOT added here: they belonged to the app's orders,
-- which now live in their own submitted_* tables. potential_order is the warehouse
-- app's alone; those two columns are dropped by migration_drop_po_app_columns.sql.
CALL _add_col('potential_order', 'approved_by',            'INT NULL');
CALL _add_col('potential_order', 'approved_at',            'DATETIME NULL');
CALL _add_col('potential_order', 'rejection_reason',       'VARCHAR(255) NULL');
CALL _add_col('potential_order', 'submitted_at',           'DATETIME NULL');
CALL _add_col('potential_order', 'expected_delivery_date', 'DATE NULL');
CALL _add_col('potential_order', 'notes',                  'TEXT NULL');

CALL _add_col('potential_order_product', 'sku_code',           'VARCHAR(100) NULL');
CALL _add_col('potential_order_product', 'product_name',       'VARCHAR(255) NULL');
CALL _add_col('potential_order_product', 'uom',                'VARCHAR(20) NULL');
CALL _add_col('potential_order_product', 'quantity_fulfilled', 'INT NULL');
CALL _add_col('potential_order_product', 'item_status',        "VARCHAR(30) NOT NULL DEFAULT 'pending'");

-- ---- 5. Seeds --------------------------------------------------------------
-- New order state: app orders land at 'submitted', then enter the chain at 'Open'.
-- App orders land at `submitted`, then enter the warehouse chain at Open via the
-- DMS-output upload (there is no approve/reject step).
INSERT INTO order_state (state_name, description)
SELECT * FROM (SELECT 'submitted' AS n, 'Order submitted from the mobile app, awaiting warehouse entry' AS d) t
WHERE NOT EXISTS (SELECT 1 FROM order_state WHERE state_name = 'submitted');

-- Permission vocabulary: v2 codes + the web app's existing concepts.
INSERT IGNORE INTO permissions (code, description) VALUES
    ('user:read',           'View users'),
    ('user:manage',         'Create/modify users'),
    ('dealer:read',         'View dealers'),
    ('dealer:manage',       'Create/modify dealers'),
    ('catalog:read',        'View catalog (SKUs/categories)'),
    ('catalog:manage',      'Create/modify catalog'),
    ('order:read',          'View orders'),
    ('order:write',         'Create/modify orders'),
    ('order:approve',       'Approve or reject orders'),
    ('inventory:read',      'View stock, ledger and picklists'),
    ('inventory:pick',      'Complete picklists (pick stock)'),
    ('inventory:pack',      'Pack orders'),
    ('inventory:stack',     'Stack/putaway received stock'),
    ('inventory:putaway',   'Putaway stock'),
    ('inventory:move',      'Receive/adjust/move stock'),
    ('assignment:read',     'View work assignments'),
    ('assignment:manage',   'Manage work assignments'),
    ('report:view',         'View reports'),
    ('warehouse:all',       'Access all warehouses (scope override)'),
    ('company:all',         'Access all companies (scope override)'),
    -- web-app specific
    ('eway:fill',           'Fill e-way bills'),
    ('eway:admin',          'Administer e-way bill routes/config'),
    ('supply_sheet:view',   'Generate supply sheets'),
    ('upload:orders',       'Upload order files'),
    ('upload:invoices',     'Upload invoice files'),
    ('upload:products',     'Upload product files');

-- Grant permissions to the existing roles so current web behaviour is preserved.
-- admin: everything.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r CROSS JOIN permissions p WHERE r.name = 'admin';

-- manager
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p
  ON p.code IN ('user:read','user:manage','dealer:read','dealer:manage','catalog:read','catalog:manage',
                'order:read','order:write','order:approve','inventory:read','inventory:stack','inventory:move',
                'assignment:read','assignment:manage','report:view','warehouse:all','company:all',
                'upload:orders','upload:invoices','upload:products','supply_sheet:view')
WHERE r.name = 'manager';

-- warehouse_staff
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p
  ON p.code IN ('order:read','inventory:read','inventory:pick','inventory:pack','assignment:read','catalog:read')
WHERE r.name = 'warehouse_staff';

-- dispatcher
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p
  ON p.code IN ('order:read','order:write','order:approve','inventory:read','inventory:move',
                'assignment:read','catalog:read','dealer:read')
WHERE r.name = 'dispatcher';

-- viewer
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p
  ON p.code IN ('user:read','dealer:read','catalog:read','order:read','inventory:read',
                'assignment:read','report:view')
WHERE r.name = 'viewer';

-- Fold each role's existing feature flags into explicit permissions.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p ON p.code = 'warehouse:all'     WHERE r.all_warehouses = 1;
-- Roles that see every warehouse also see every company (keeps admin/manager unscoped).
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p ON p.code = 'company:all'       WHERE r.all_warehouses = 1;
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p ON p.code = 'eway:admin'        WHERE r.eway_bill_admin = 1;
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p ON p.code = 'eway:fill'         WHERE r.eway_bill_filling = 1;
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.role_id, p.permission_id FROM roles r JOIN permissions p ON p.code = 'supply_sheet:view' WHERE r.supply_sheet = 1;

-- Fold role_uploads into upload:* permissions.
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT ru.role_id, p.permission_id FROM role_uploads ru
JOIN permissions p ON p.code = CONCAT('upload:', ru.upload_type);

-- Seed user_roles from the existing single users.role string.
INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id, r.role_id FROM users u JOIN roles r ON r.name = u.role;

-- ---------------------------------------------------------------------------
-- Company scoping for master data.
--
-- Orders/invoices already carried company_id; product and dealer did not, so the
-- New Order pickers showed every company's records to every user. NULL means
-- "unassigned" and is hidden from company-scoped users (same rule as orders) —
-- only holders of company:all still see those rows.
-- ---------------------------------------------------------------------------
CALL _add_col('product', 'company_id', 'INT NULL');
CALL _add_col('dealer',  'company_id', 'INT NULL');
CALL _add_idx('product', 'idx_product_company', 'INDEX idx_product_company (company_id)');
CALL _add_idx('dealer',  'idx_dealer_company',  'INDEX idx_dealer_company (company_id)');
CALL _add_fk('product', 'fk_product_company',
             'CONSTRAINT fk_product_company FOREIGN KEY (company_id) REFERENCES company(company_id)');
CALL _add_fk('dealer',  'fk_dealer_company',
             'CONSTRAINT fk_dealer_company FOREIGN KEY (company_id) REFERENCES company(company_id)');

-- Backfill from this deployment's SKU/dealer code prefixes (HRO-/EBC-/CAD-).
-- Re-running is harmless; rows already assigned keep their value.
UPDATE product p JOIN company c ON c.name = 'Hero'   SET p.company_id = c.company_id
  WHERE p.company_id IS NULL AND p.product_string LIKE 'HRO-%';
UPDATE product p JOIN company c ON c.name = 'Ebco'   SET p.company_id = c.company_id
  WHERE p.company_id IS NULL AND p.product_string LIKE 'EBC-%';
UPDATE product p JOIN company c ON c.name = 'Cadila' SET p.company_id = c.company_id
  WHERE p.company_id IS NULL AND p.product_string LIKE 'CAD-%';
UPDATE dealer d JOIN company c ON c.name = 'Hero'   SET d.company_id = c.company_id
  WHERE d.company_id IS NULL AND d.dealer_code LIKE 'HRO-%';
UPDATE dealer d JOIN company c ON c.name = 'Ebco'   SET d.company_id = c.company_id
  WHERE d.company_id IS NULL AND d.dealer_code LIKE 'EBC-%';
UPDATE dealer d JOIN company c ON c.name = 'Cadila' SET d.company_id = c.company_id
  WHERE d.company_id IS NULL AND d.dealer_code LIKE 'CAD-%';

-- Where the rep stood when the order was raised. Required by the mobile
-- POST /api/v1/orders; NULL on rows created before this, and on web uploads.
CALL _add_col('potential_order', 'latitude',             'DECIMAL(10,7) NULL');
CALL _add_col('potential_order', 'longitude',            'DECIMAL(10,7) NULL');
CALL _add_col('potential_order', 'location_accuracy_m',  'FLOAT NULL');
CALL _add_col('potential_order', 'location_captured_at', 'DATETIME NULL');

-- ---------------------------------------------------------------------------
-- Paper-order capture.
--
-- Some companies' reps take orders on paper and photograph them instead of
-- picking products in the app. Such an order is a real potential_order in
-- `submitted` with a photo but no line items; the back office transcribes it.
-- Guards in service_v1 refuse to approve an order with no lines, so it can't
-- reach the warehouse before it's entered.
-- ---------------------------------------------------------------------------
CALL _add_col('company', 'order_capture_mode', "VARCHAR(20) NOT NULL DEFAULT 'itemised'");

-- Grant visibility of the app-entry states to every role that already sees any
-- order states, so role-filtered views (e.g. the Order Tracking dashboard) show
-- app orders instead of silently dropping them.
INSERT IGNORE INTO role_order_states (role_id, state_name)
SELECT DISTINCT ros.role_id, 'submitted'
FROM role_order_states ros;

-- ---------------------------------------------------------------------------
-- App-submitted orders live in their own tables.
--
-- The mobile app used to write into potential_order / potential_order_product,
-- which it shared with the warehouse app. Those tables now belong solely to the
-- warehouse app; the mobile app reads and writes only the submitted_* tables
-- below. Plain single-column PKs (not partitioned like potential_order).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS submitted_orders (
    submitted_order_id     INT AUTO_INCREMENT PRIMARY KEY,
    order_number           VARCHAR(50),
    dealer_id              INT NOT NULL,
    company_id             INT,
    warehouse_id           INT,
    status                 VARCHAR(30) NOT NULL DEFAULT 'submitted',
    source                 VARCHAR(20) DEFAULT 'itemised',   -- 'itemised' | 'photo'
    created_by             INT,
    requested_by           INT,
    notes                  TEXT,
    expected_delivery_date DATE,
    latitude               DECIMAL(10,7),
    longitude              DECIMAL(10,7),
    location_accuracy_m    FLOAT,
    location_captured_at   DATETIME,
    submitted_at           DATETIME,
    created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_so_company (company_id),
    INDEX idx_so_dealer (dealer_id),
    INDEX idx_so_created_by (created_by),
    INDEX idx_so_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS submitted_order_products (
    submitted_order_product_id INT AUTO_INCREMENT PRIMARY KEY,
    submitted_order_id         INT NOT NULL,
    product_id                 INT,
    sku_code                   VARCHAR(100),
    product_name               VARCHAR(255),   -- snapshot at order time
    uom                        VARCHAR(20),
    quantity                   INT NOT NULL,
    mrp                        DECIMAL(10,2),
    created_at                 DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_sop_order (submitted_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS submitted_order_attachments (
    attachment_id      INT AUTO_INCREMENT PRIMARY KEY,
    submitted_order_id INT NOT NULL,
    file_path          VARCHAR(255) NOT NULL,   -- relative to MEDIA_ROOT
    mime_type          VARCHAR(64),
    size_bytes         INT,
    uploaded_by        INT,
    uploaded_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_soa_order (submitted_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS submitted_order_status_history (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    submitted_order_id INT NOT NULL,
    status             VARCHAR(30) NOT NULL,   -- status string, no order_state FK
    changed_by         INT,
    changed_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sosh_order (submitted_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- One-time backfill: copy every `submitted` order (and its lines, photos and
-- history) out of potential_order into the app's tables. Idempotent — skips any
-- order_number already present, so re-running the migration does not duplicate.
INSERT INTO submitted_orders
    (order_number, dealer_id, company_id, warehouse_id, status, created_by, requested_by,
     notes, expected_delivery_date, latitude, longitude, location_accuracy_m,
     location_captured_at, submitted_at, created_at, updated_at)
SELECT
     po.order_number, po.dealer_id, po.company_id, po.warehouse_id, po.status,
     po.created_by, po.requested_by, po.notes, po.expected_delivery_date,
     po.latitude, po.longitude, po.location_accuracy_m, po.location_captured_at,
     po.submitted_at, po.created_at, po.updated_at
FROM potential_order po
WHERE po.status = 'submitted'
  AND NOT EXISTS (SELECT 1 FROM submitted_orders so WHERE so.order_number = po.order_number);

INSERT INTO submitted_order_products
    (submitted_order_id, product_id, sku_code, product_name, uom, quantity, mrp, created_at, updated_at)
SELECT so.submitted_order_id, pop.product_id, pop.sku_code, pop.product_name, pop.uom,
       pop.quantity, pop.mrp, pop.created_at, pop.updated_at
FROM potential_order_product pop
JOIN potential_order po ON po.potential_order_id = pop.potential_order_id AND po.status = 'submitted'
JOIN submitted_orders so ON so.order_number = po.order_number
WHERE NOT EXISTS (
    SELECT 1 FROM submitted_order_products x
    WHERE x.submitted_order_id = so.submitted_order_id AND x.sku_code = pop.sku_code);

INSERT INTO submitted_order_status_history
    (submitted_order_id, status, changed_by, changed_at)
SELECT so.submitted_order_id, os.state_name, h.changed_by, h.changed_at
FROM order_state_history h
JOIN order_state os ON os.state_id = h.state_id
JOIN potential_order po ON po.potential_order_id = h.potential_order_id AND po.status = 'submitted'
JOIN submitted_orders so ON so.order_number = po.order_number
WHERE NOT EXISTS (
    SELECT 1 FROM submitted_order_status_history x
    WHERE x.submitted_order_id = so.submitted_order_id
      AND x.status = os.state_name AND x.changed_at = h.changed_at);

-- Every submitted order is now copied into the submitted_* tables, so remove the
-- copied rows from the shared potential_order store — the app no longer shares it
-- with the warehouse app. Children first, then headers. Idempotent: after the first
-- run there are no submitted rows left to match.
DELETE pop FROM potential_order_product pop
JOIN potential_order po ON po.potential_order_id = pop.potential_order_id
WHERE po.status = 'submitted';

DELETE h FROM order_state_history h
JOIN potential_order po ON po.potential_order_id = h.potential_order_id
WHERE po.status = 'submitted';

DELETE FROM potential_order WHERE status = 'submitted';

-- Retire the shared order_attachment table. The app now stores paper-order photos in
-- submitted_order_attachments; on the live DB the legacy rows were already moved there.
-- No fresh install populates order_attachment, so nothing is lost by dropping it.
DROP TABLE IF EXISTS order_attachment;

-- ---------------------------------------------------------------------------
-- Salesperson dealer visits: check-in when the rep reaches a dealer, check-out
-- when they leave. Time + location are captured at both ends. One visit is
-- 'active' until checked out; a rep can only have one active visit at a time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dealer_visits (
    visit_id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id              INT NOT NULL,
    dealer_id            INT NOT NULL,
    company_id           INT,
    check_in_at          DATETIME NOT NULL,
    check_in_latitude    DECIMAL(10,7),
    check_in_longitude   DECIMAL(10,7),
    check_in_accuracy_m  FLOAT,
    check_out_at         DATETIME,
    check_out_latitude   DECIMAL(10,7),
    check_out_longitude  DECIMAL(10,7),
    check_out_accuracy_m FLOAT,
    status               VARCHAR(20) NOT NULL DEFAULT 'active',  -- active | checked_out
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_dv_user (user_id),
    INDEX idx_dv_dealer (dealer_id),
    INDEX idx_dv_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP PROCEDURE IF EXISTS _add_col;
DROP PROCEDURE IF EXISTS _add_idx;
DROP PROCEDURE IF EXISTS _add_fk;
