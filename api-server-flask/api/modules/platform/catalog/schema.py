# -*- encoding: utf-8 -*-
"""
catalog module — table DDL (registered with the schema registry).

`sku_batch` is catalog-owned but referenced by most of the inventory model
(`transferin_info`, `fc_entity_stock`, `fc_entity_stock_ledger`,
`fc_entity_recommendation` all carry `batch_id` = `sku_batch.id`).

Batch identity is DERIVED, not sequential: `batch_hash` is a unique hash over
`batch_params`, so receiving the same SKU twice with the same parameters resolves to the
SAME batch rather than creating a duplicate. This is what lets fc_entity_stock's unique
key accumulate stock correctly across two GRNs.

`batch_params` carries MRP alongside expiry and source — so MRP is part of batch identity:
two MRPs mean two batches, and stock bought at different prices never silently merges.
The placement engine also reads these params (expiry -> FEFO) when recommending bins.

See modules/inventory/GRN_STACKING_DESIGN.md §4.11.
"""

from api.shared.schema_registry import register_table

register_table("sku_batch", """
CREATE TABLE IF NOT EXISTS sku_batch (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    sku_id       INT UNSIGNED NOT NULL,
    batch_hash   CHAR(64) DEFAULT NULL,
    batch_params JSON DEFAULT NULL,
    algorithm_id INT UNSIGNED NOT NULL DEFAULT 0,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_batch_hash (batch_hash),
    KEY idx_sku_id (sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=10)


# Product category tree (product.category_id points here). Self-referencing via parent_id;
# no FK on parent_id so a category can be inserted before its parent. DDL matches
# migration_v2_api.sql so an already-migrated deployment is a no-op.
register_table("categories", """
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
""", order=11)


# ── Packaging, pricing and per-industry attributes ───────────────────────────────
#
# Three tables, none of them specific to any company. Between them they replace what
# would otherwise be a column per industry on `product` — the mistake `litres_per_unit`
# already represents, sitting empty on 60k parts to serve one oil target.
#
# Nothing here changes how an existing product behaves. A product with no product_uom
# rows is implicitly single-unit (factor 1), which is exactly what every Hero part is,
# so the readers fall back to today's behaviour without a special case.

# The shared vocabulary of unit names. Deliberately NOT a conversion table: "1 kg =
# 1000 g" is universal, but "1 box = 30 strips" is true only of one product, so the
# factors live in product_uom and this table only names the units.
register_table("uom", """
CREATE TABLE IF NOT EXISTS uom (
    uom_code  VARCHAR(16) NOT NULL,
    name      VARCHAR(64) NOT NULL,
    uom_type  VARCHAR(16) NOT NULL DEFAULT 'count',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uom_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=12)


# One row per rung of a product's packaging ladder: TAB -> STRIP -> BOX -> CASE for a
# pharma tablet, a single PCS row for an auto part.
#
# `factor_to_base` is ABSOLUTE (a case of 66 boxes of 30 strips of 10 tabs = 19800), not
# relative to the rung below, so any conversion is one multiply and no code has to walk
# the ladder. The three flags carry what would otherwise be special-case logic: a rung can
# be informational (tablets are counted but never ordered), the one the price is quoted
# against, and the one stock is counted in — and they are independent.
register_table("product_uom", """
CREATE TABLE IF NOT EXISTS product_uom (
    product_uom_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id     INT NOT NULL,
    uom_code       VARCHAR(16) NOT NULL,
    factor_to_base DECIMAL(18,6) NOT NULL DEFAULT 1,
    -- Weight of THIS rung's packaging, excluding the stock inside it. Packing reads it
    -- to weight-check a sealed supplier carton, whose tare cannot be measured — you
    -- would have to empty it. The rung is identified by matching the scanned quantity
    -- against factor_to_base, which works because the printed codes carry no pack-level
    -- field. See fulfillment/packing/PACKING_DESIGN.md §6.8.1.
    pack_tare_kg   DECIMAL(12,3) NULL,
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
""", order=13)


# NOTE: there is deliberately NO price table here.
#
# Price is not catalogue data in this system — it belongs to the stock it was paid for,
# and `fc_sku_price_details` (owned by inventory.ingestion) already holds it at the right
# grain: one row per (company, sku, batch), carrying landing_price, cn_rate, mrp, gst_rate
# and the uom the supplier billed in. A price table here would be a second answer to
# "what does this cost", with nothing to say which one wins.
#
# What catalogue DOES own is the conversion — product_uom above — which is what lets an
# order placed in cases be turned into the strips that price is quoted per. See
# catalog/product_pack.py for how a rate list is loaded as a batch-less rate.


# Everything that is real for one industry and meaningless for the others — composition
# and shelf life for pharma, whatever the next supplier brings. An admin defines a new
# attribute by inserting a row here, not by shipping a migration.
register_table("attribute_def", """
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
""", order=15)


# The values. Typed columns rather than one text blob so a numeric attribute can be
# filtered and indexed as a number.
register_table("product_attribute", """
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
""", order=16)
