# -*- encoding: utf-8 -*-
"""picklist module — DDL. This module owns these tables.

Deliberately NOT partitioned, following the submitted_* precedent: pick-list volume
tracks order volume but each row is referenced by a plain id from a QR code on a
sheet of paper that may be scanned weeks later. A composite PK containing a date
column would make that lookup need the date, which the QR does not carry.
"""

from api.shared.schema_registry import register_table

# `meta` is the only JSON column in the schema. It holds everything needed to redraw
# the page: the distributor header block (which has no home elsewhere — `warehouse`
# carries only name and location, no GSTIN, state code or contact), the order block,
# and one entry per printed line including the fields potential_order_product has no
# column for (bin location, HSN, MOQ, stock on hand, allocated qty).
#
# meta.v is the payload version. pdf.py branches on it, so an extractor change that
# alters the shape does not silently break the reprint of every older pick list.
#
# picklist_code is NOT NULL DEFAULT '' rather than nullable for the same reason
# dealer_target.scheme is: it sits in uq_picklist_order_code, and MySQL treats every
# NULL in a UNIQUE index as distinct — a nullable column would let the key wave
# through the duplicates it exists to block.
register_table("order_picklist", """
CREATE TABLE IF NOT EXISTS order_picklist (
    picklist_id        INT AUTO_INCREMENT PRIMARY KEY,
    potential_order_id INT NOT NULL,
    original_order_id  VARCHAR(100) NOT NULL,
    picklist_code      VARCHAR(100) NOT NULL DEFAULT '',
    picklist_date      DATETIME NULL,
    -- 16 Crockford-base32 chars = 80 bits from secrets. Never derived from the order
    -- id: a guessable token would make the printed sheet forgeable, which is the whole
    -- reason the QR carries a token alongside the order number it also prints.
    qr_token           VARCHAR(16) NOT NULL,
    line_count         INT NOT NULL DEFAULT 0,
    meta               JSON NOT NULL,
    warehouse_id       INT NULL,
    company_id         INT NULL,
    upload_batch_id    INT NULL,
    created_by         INT NULL,
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_picklist_token (qr_token),
    -- Re-uploading the same document updates the row in place and KEEPS the token, so
    -- sheets already printed and hanging on a picking trolley keep resolving.
    UNIQUE KEY uq_picklist_order_code (potential_order_id, picklist_code),
    INDEX idx_picklist_order (potential_order_id),
    INDEX idx_picklist_orig (original_order_id),
    INDEX idx_picklist_company (company_id),
    INDEX idx_picklist_batch (upload_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=80)

# Every scan, including the ones that change nothing.
#
# order_state_history records successful transitions only, so without this table a
# scan that is rejected — unknown token, a payload whose order number does not match
# the token's row, an illegal transition — leaves no trace at all. Those are exactly
# the scans someone reports as "the QR doesn't work", and qr_payload is what separates
# a creased symbol misread from a hand-built code.
register_table("order_picklist_scan", """
CREATE TABLE IF NOT EXISTS order_picklist_scan (
    scan_id     INT AUTO_INCREMENT PRIMARY KEY,
    picklist_id INT NULL,                      -- NULL when the token resolved to nothing
    qr_payload  VARCHAR(255) NULL,
    scanned_by  INT NULL,
    device_id   VARCHAR(64) NULL,
    from_status VARCHAR(50) NULL,
    to_status   VARCHAR(50) NULL,
    -- ok | unknown_token | mismatch | illegal_transition | duplicate | bad_payload | no_access
    result      VARCHAR(32) NOT NULL,
    reason      VARCHAR(500) NULL,
    scanned_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pls_picklist (picklist_id),
    INDEX idx_pls_result (result),
    INDEX idx_pls_scanned (scanned_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=81)
