# -*- encoding: utf-8 -*-
"""Tables owned by procurement.po_builder — drafting purchase orders to the supplier
(Ebco) with live scheme-slab tracking.

Master data (admin uploads, versioned — an upload never edits an older version):
  dms_sku_master           one row per SKU-master upload (the supplier's DMS SKU export)
  dms_sku_master_item      the SKUs of one upload: full code, MRP, GST, SPU, UOM, DMS id
  dms_scheme               one scheme upload; the latest one is in force until the next
                           upload replaces it (no validity dates)
  dms_scheme_group         its scheme groups (SG1, SG2, ...) and their basis (QTY / VALUE)
  dms_scheme_slab          slabs per group: min threshold -> discount %
  dms_scheme_sku           SKU -> group, exactly as the scheme file says
  pob_settings             per-company discounts

Purchase orders:
  pob_po                   header; ties the PO to the SKU master it was drafted against
  pob_po_line              one line per SKU (same SKU added twice merges into one line);
                           MRP/GST/SPU are COPIED from the master when the line is added,
                           so a later master upload never reprices an existing PO
  pob_po_line_source       where a line's qty came from — the line qty is always the sum
                           of its sources, so provenance survives inline edits
  pob_import / _row        bulk imports and every row of them, including the ones that
                           did not match — those are listed on the PO page until each is
                           added under the right SKU or dismissed

Why prices are copied onto lines but scheme groups are not: a draft follows the scheme in
force (the latest upload), and only finalising freezes the scheme group and % onto each
line — so a new scheme reprices open drafts but never a finalised PO.
"""

from api.shared.schema_registry import register_table


register_table("pob_settings", """
CREATE TABLE IF NOT EXISTS pob_settings (
    company_id            INT NOT NULL,
    dtr_discount_pct      DECIMAL(6,3) NOT NULL DEFAULT 51.200,
    std_discount_pct      DECIMAL(6,3) NOT NULL DEFAULT 12.000,
    show_case_helper      TINYINT(1) NOT NULL DEFAULT 0,
    updated_by            VARCHAR(255) NOT NULL DEFAULT 'system',
    updated_on            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=90)


register_table("dms_sku_master", """
CREATE TABLE IF NOT EXISTS dms_sku_master (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id            INT NOT NULL,
    name                  VARCHAR(255) NOT NULL DEFAULT '',
    filename              VARCHAR(255) NOT NULL DEFAULT '',
    row_count             INT NOT NULL DEFAULT 0,
    active_count          INT NOT NULL DEFAULT 0,
    uploaded_by           VARCHAR(255) NOT NULL DEFAULT 'system',
    uploaded_on           DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_pob_master_company (company_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=90)


register_table("dms_sku_master_item", """
CREATE TABLE IF NOT EXISTS dms_sku_master_item (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    master_id             BIGINT UNSIGNED NOT NULL,
    sku_code              VARCHAR(128) NOT NULL,
    dms_sku_id            VARCHAR(32)  NOT NULL DEFAULT '',
    description           VARCHAR(500) NOT NULL DEFAULT '',
    category              VARCHAR(128) NOT NULL DEFAULT '',
    finish                VARCHAR(16)  NOT NULL DEFAULT '',
    mrp                   DECIMAL(14,4) NOT NULL DEFAULT 0,
    gst_pct               DECIMAL(6,2)  NOT NULL DEFAULT 0,
    hsn_code              VARCHAR(20)  NOT NULL DEFAULT '',
    spu                   DECIMAL(14,3) NOT NULL DEFAULT 1,
    uom                   VARCHAR(16)  NOT NULL DEFAULT '',
    is_active             TINYINT(1) NOT NULL DEFAULT 1,
    raw                   JSON NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_pob_item (master_id, sku_code),
    KEY idx_pob_item_desc (master_id, description(64))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=91)


register_table("dms_scheme", """
CREATE TABLE IF NOT EXISTS dms_scheme (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id            INT NOT NULL,
    name                  VARCHAR(255) NOT NULL,
    filename              VARCHAR(255) NOT NULL DEFAULT '',
    group_count           INT NOT NULL DEFAULT 0,
    sku_count             INT NOT NULL DEFAULT 0,
    uploaded_by           VARCHAR(255) NOT NULL DEFAULT 'system',
    uploaded_on           DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_dms_scheme_company (company_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=90)


register_table("dms_scheme_group", """
CREATE TABLE IF NOT EXISTS dms_scheme_group (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    scheme_id             BIGINT UNSIGNED NOT NULL,
    scheme_no             VARCHAR(32)  NOT NULL,
    name                  VARCHAR(1000) NOT NULL DEFAULT '',
    category              VARCHAR(128) NOT NULL DEFAULT '',
    basis                 VARCHAR(8)   NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_pob_group (scheme_id, scheme_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=91)


register_table("dms_scheme_slab", """
CREATE TABLE IF NOT EXISTS dms_scheme_slab (
    scheme_group_id       BIGINT UNSIGNED NOT NULL,
    slab_no               TINYINT NOT NULL,
    min_threshold         DECIMAL(16,3) NOT NULL,
    discount_pct          DECIMAL(6,3)  NOT NULL,
    PRIMARY KEY (scheme_group_id, slab_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=92)


register_table("dms_scheme_sku", """
CREATE TABLE IF NOT EXISTS dms_scheme_sku (
    scheme_id             BIGINT UNSIGNED NOT NULL,
    sku_code              VARCHAR(128) NOT NULL,
    scheme_group_id       BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (scheme_id, sku_code),
    KEY idx_pob_ss_group (scheme_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=92)


register_table("pob_po", """
CREATE TABLE IF NOT EXISTS pob_po (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id            INT NOT NULL,
    po_no                 VARCHAR(32)  NOT NULL DEFAULT '',
    po_date               DATE NOT NULL,
    title                 VARCHAR(255) NOT NULL DEFAULT '',
    remarks               VARCHAR(255) NOT NULL DEFAULT '',
    status                VARCHAR(16)  NOT NULL DEFAULT 'draft',
    sku_master_id         BIGINT UNSIGNED NOT NULL,
    -- Frozen at finalise: the settings the PO was priced with and its totals.
    frozen_settings       JSON NULL,
    frozen_totals         JSON NULL,
    created_by            VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on            DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    finalised_by          VARCHAR(255) NULL,
    finalised_on          DATETIME NULL,
    PRIMARY KEY (id),
    KEY idx_pob_po_company (company_id, status, po_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=93)


register_table("pob_po_line", """
CREATE TABLE IF NOT EXISTS pob_po_line (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    po_id                 BIGINT UNSIGNED NOT NULL,
    sku_code              VARCHAR(128) NOT NULL,
    qty                   DECIMAL(14,3) NOT NULL DEFAULT 0,
    dms_sku_id            VARCHAR(32)  NOT NULL DEFAULT '',
    description           VARCHAR(500) NOT NULL DEFAULT '',
    category              VARCHAR(128) NOT NULL DEFAULT '',
    finish                VARCHAR(16)  NOT NULL DEFAULT '',
    mrp                   DECIMAL(14,4) NOT NULL DEFAULT 0,
    gst_pct               DECIMAL(6,2)  NOT NULL DEFAULT 0,
    spu                   DECIMAL(14,3) NOT NULL DEFAULT 1,
    uom                   VARCHAR(16)  NOT NULL DEFAULT '',
    -- Set only when the PO is finalised (a draft follows the scheme mapping live).
    scheme_no             VARCHAR(32)  NULL,
    scheme_name           VARCHAR(1000) NULL,
    scheme_basis          VARCHAR(8)   NULL,
    scheme_pct            DECIMAL(6,3) NULL,
    created_on            DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_pob_line (po_id, sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=94)


# `qty` is a signed delta: an inline edit from 10 to 8 is recorded as a -2 "Manual edit".
register_table("pob_po_line_source", """
CREATE TABLE IF NOT EXISTS pob_po_line_source (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    po_line_id            BIGINT UNSIGNED NOT NULL,
    po_id                 BIGINT UNSIGNED NOT NULL,
    source_tag            VARCHAR(255) NOT NULL,
    import_id             BIGINT UNSIGNED NULL,
    qty                   DECIMAL(14,3) NOT NULL,
    created_by            VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on            DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_pob_src_line (po_line_id),
    KEY idx_pob_src_po (po_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=94)


register_table("pob_import", """
CREATE TABLE IF NOT EXISTS pob_import (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    po_id                 BIGINT UNSIGNED NOT NULL,
    source_tag            VARCHAR(255) NOT NULL,
    filename              VARCHAR(255) NOT NULL DEFAULT '',
    sheet_name            VARCHAR(128) NOT NULL DEFAULT '',
    columns_used          VARCHAR(500) NOT NULL DEFAULT '',
    row_count             INT NOT NULL DEFAULT 0,
    status                VARCHAR(16) NOT NULL DEFAULT 'review',
    created_by            VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on            DATETIME DEFAULT CURRENT_TIMESTAMP,
    applied_on            DATETIME NULL,
    PRIMARY KEY (id),
    KEY idx_pob_import_po (po_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=94)


register_table("pob_import_row", """
CREATE TABLE IF NOT EXISTS pob_import_row (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    import_id             BIGINT UNSIGNED NOT NULL,
    row_no                INT NOT NULL,
    raw_code              VARCHAR(255) NOT NULL DEFAULT '',
    raw_finish            VARCHAR(64)  NOT NULL DEFAULT '',
    raw_desc              VARCHAR(500) NOT NULL DEFAULT '',
    qty                   DECIMAL(14,3) NOT NULL DEFAULT 0,
    -- exact | finish_added | base_single | needs_choice | fuzzy | unmatched | bad_qty | dismissed
    match_status          VARCHAR(16)  NOT NULL,
    match_note            VARCHAR(255) NOT NULL DEFAULT '',
    candidates            JSON NULL,
    resolved_sku_code     VARCHAR(128) NULL,
    applied               TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_pob_irow_import (import_id, row_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=95)
