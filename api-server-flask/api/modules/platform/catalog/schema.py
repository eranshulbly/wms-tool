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
