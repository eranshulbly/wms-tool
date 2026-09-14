# -*- encoding: utf-8 -*-
"""
order module — DDL for the mobile app's OWN order store.

The mobile app used to write its orders into potential_order / potential_order_product —
the same tables the warehouse app works from. These tables fork that store so the two
systems no longer share it: potential_order stays the warehouse app's; the app reads and
writes only the submitted_* tables below.

Deliberately NOT partitioned and with a plain single-column PK (unlike potential_order,
which is RANGE-partitioned by created_at with a composite PK) — app order volume doesn't
need partitioning, and a simple PK is far easier to reference from the child tables.

Master/reference data (dealer, product, company, warehouse, categories, users, roles, …)
is shared and unchanged; these tables reference it by plain id, no cross-table FK.
"""

from api.shared.schema_registry import register_table

register_table("submitted_orders", """
CREATE TABLE IF NOT EXISTS submitted_orders (
    submitted_order_id     INT AUTO_INCREMENT PRIMARY KEY,
    order_number           VARCHAR(50),
    dealer_id              INT NOT NULL,
    company_id             INT,
    warehouse_id           INT,
    status                 VARCHAR(30) NOT NULL DEFAULT 'submitted',
    source                 VARCHAR(20) DEFAULT 'itemised',   -- 'itemised' | 'photo'
    -- DMS-input workflow stage (web-side; independent of `status`, which the mobile app owns):
    --   submitted / re_submitted -> Submitted Orders tab (awaiting part-convertor upload)
    --   ready / done             -> Download DMS input file tab (ready / already downloaded)
    dms_status             VARCHAR(20) NOT NULL DEFAULT 'submitted',
    reject_note            TEXT,   -- reason shown when an order is rejected back to Submitted
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
    INDEX idx_so_status (status),
    INDEX idx_so_dms_status (dms_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=5)

register_table("submitted_order_products", """
CREATE TABLE IF NOT EXISTS submitted_order_products (
    submitted_order_product_id INT AUTO_INCREMENT PRIMARY KEY,
    submitted_order_id         INT NOT NULL,
    product_id                 INT,
    sku_code                   VARCHAR(100),
    product_name               VARCHAR(255),   -- snapshot at order time
    uom                        VARCHAR(20),
    quantity                   INT NOT NULL,
    mrp                        DECIMAL(10,2),
    -- What the DMS file actually asked for, once stock had been allocated against it
    -- (NULL until the file is first built). Kept so a re-download reproduces the file
    -- byte-for-byte instead of re-allocating: the second run would otherwise deduct the
    -- same stock twice and, reading the now-lower quantities, emit a smaller file than
    -- the one already handed to the DMS.
    dms_quantity               INT,
    created_at                 DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at                 DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_sop_order (submitted_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=6)

register_table("submitted_order_attachments", """
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
""", order=7)

# Stock on hand, as of the last spreadsheet the DMS operator uploaded. Deliberately a
# scratch table, not an inventory system: it is replaced wholesale on every upload and is
# only consulted while a DMS file is being built.
#
# Keyed on `part_number`, NOT on product_id. The brief asked for both, but they cannot
# both be the key and part_number is the one that works: the parts on these sheets
# routinely name items the catalogue has never heard of (the part-convertor upload
# tolerates exactly this, storing product_id NULL), and the order lines this stock is
# matched against carry sku_code always and product_id often NULL. Keying on product_id
# would silently drop stock for every uncatalogued part and fail to match most lines.
# product_id is still resolved and stored where the part IS known, so the row can be
# joined to the catalogue — it just isn't what identifies the row.
#
# `uploaded_at` exists separately from `updated_at` on purpose. The 30-minute freshness
# rule has to measure the last time a HUMAN uploaded stock; `updated_at` also moves when a
# download deducts, so a download would keep refreshing its own deadline and the rule
# would never bite.
register_table("temp_inventory", """
CREATE TABLE IF NOT EXISTS temp_inventory (
    temp_inventory_id INT AUTO_INCREMENT PRIMARY KEY,
    part_number       VARCHAR(100) NOT NULL,
    product_id        INT,
    quantity          INT NOT NULL DEFAULT 0,
    uploaded_at       DATETIME,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_temp_inv_part (part_number),
    INDEX idx_temp_inv_product (product_id),
    -- The freshness banner reads MAX(uploaded_at) on every page load; indexed so that
    -- stays a single index lookup instead of scanning tens of thousands of rows.
    INDEX idx_temp_inv_uploaded (uploaded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=8)

register_table("submitted_order_status_history", """
CREATE TABLE IF NOT EXISTS submitted_order_status_history (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    submitted_order_id INT NOT NULL,
    status             VARCHAR(30) NOT NULL,   -- the status string directly (no state_id)
    changed_by         INT,
    changed_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sosh_order (submitted_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=8)


# What an admin deleted, and why.
#
# The delete is a HARD delete — the order, its lines, its history and any invoice all go.
# That is what "wrongly uploaded" needs: a soft-deleted order still occupies its order
# number, so the corrected upload of the same challan would be refused as a duplicate.
#
# But a hard delete with no trace is worse than the problem it solves: an order that was
# on the system yesterday and is gone today, with nobody able to say who removed it or
# what it contained. So the identifying facts are copied here first — enough to answer
# "what was order 12246 and who deleted it", without keeping the rows that would block
# re-uploading it.
register_table("deleted_order_log", """
CREATE TABLE IF NOT EXISTS deleted_order_log (
    deleted_order_log_id INT AUTO_INCREMENT PRIMARY KEY,
    potential_order_id   INT NOT NULL,
    original_order_id    VARCHAR(100) NULL,
    order_type           VARCHAR(50) NULL,
    status_at_deletion   VARCHAR(30) NULL,
    company_id           INT NULL,
    warehouse_id         INT NULL,
    dealer_id            INT NULL,
    purchaser_name       VARCHAR(255) NULL,
    line_count           INT NOT NULL DEFAULT 0,
    total_quantity       INT NOT NULL DEFAULT 0,
    invoice_numbers      VARCHAR(500) NULL,
    reason               VARCHAR(500) NULL,
    deleted_by           INT NULL,
    deleted_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dol_order  (original_order_id),
    INDEX idx_dol_when   (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=9)
