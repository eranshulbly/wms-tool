-- =============================================================================
-- Migration: the packing module (fulfillment cluster).
--
-- See api/modules/fulfillment/packing/PACKING_DESIGN.md and
--     api/modules/fulfillment/packing/PACKING_SCREEN_API_CONTRACTS.md
--
-- **Zero new tables.** Packing owns none: a packing job is an
-- `entity_movement_request` with movement_type='packing', and every box, every SKU
-- inside a box and every shortfall is an `entity_movement_details` row. Both tables
-- belong to the inventory module and are reused exactly as picking and stacking use
-- them.
--
-- Everything below is ADDITIVE and IDEMPOTENT (safe to re-run). Nothing is renamed
-- or dropped, so the existing web app and the picking/stacking scaffolds are
-- unaffected. The same changes are applied at boot by
-- `db_manager._migrate_packing_columns()`, so a fresh database and an existing one
-- converge on this shape; this file is for applying them ahead of a deploy.
--
--   1. entity_movement_details : entity_id -> VARCHAR(64), four weight columns,
--                                two indexes
--   2. product_uom             : pack_tare_kg (no-op unless the table exists —
--                                catalog/schema.py creates it empty at boot, so run
--                                this AFTER the deploy that carries that schema)
--   3. potential_order         : short_pack_reason (submit writes it)
--   4. Seeds                   : NONE. The packer role is deliberately not created —
--                                packing ships dark, reachable only by `admin`.
--                                See step 4 below for how to turn it on.
--
-- ⚠ RUN STEP 1 WHILE entity_movement_details IS STILL NEAR-EMPTY.
--   BIGINT -> VARCHAR is ALGORITHM=COPY: a full rebuild of every partition under a
--   metadata lock. It is effectively instant today because the movement write flows
--   are still NotImplementedError. Once picking starts writing to this table the
--   same statement becomes an outage-shaped migration.
-- =============================================================================

-- ---- helpers: idempotent DDL (MySQL has no ADD COLUMN IF NOT EXISTS) --------
DROP PROCEDURE IF EXISTS _pk_add_col;
DROP PROCEDURE IF EXISTS _pk_add_idx;
DROP PROCEDURE IF EXISTS _pk_modify_col;
DELIMITER //
CREATE PROCEDURE _pk_add_col(IN tbl VARCHAR(64), IN col VARCHAR(64), IN ddl TEXT)
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl)
       AND NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
                         AND COLUMN_NAME = col) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN `', col, '` ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
CREATE PROCEDURE _pk_add_idx(IN tbl VARCHAR(64), IN idx VARCHAR(64), IN ddl TEXT)
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl)
       AND NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
                         AND INDEX_NAME = idx) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
-- Guarded on the CURRENT type, not on absence: re-running must not pay for a second
-- full-table rebuild of a partitioned table.
CREATE PROCEDURE _pk_modify_col(IN tbl VARCHAR(64), IN col VARCHAR(64),
                                IN target_type VARCHAR(32), IN ddl TEXT)
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = tbl
                 AND COLUMN_NAME = col AND DATA_TYPE <> target_type) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` MODIFY COLUMN `', col, '` ', ddl);
        PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
    END IF;
END //
DELIMITER ;


-- ---- 1. entity_movement_details --------------------------------------------
--
-- entity_id becomes a string so a box's scanned carton label lives in it directly
-- ('WH1-000148213') instead of needing a parallel column. These codes are
-- alphanumeric and their prefix and leading zeros are meaningful — a BIGINT would
-- silently destroy both. Precedent: transferin_info.transferin_id, widened for
-- exactly this reason. Widening an integer to a string cannot lose data.
--
-- The one code change this retype forces is in
-- api/modules/inventory/router_v1.py — codes_for_sku_ids() keys on ints and needs
-- int(entity_id) for entity_type='sku' rows. Applied in the same change.
CALL _pk_modify_col('entity_movement_details', 'entity_id', 'varchar',
                    'VARCHAR(64) NOT NULL');

-- Weights are columns, not JSON. `weight_kg` on a box row is THE number the dispatch
-- gate compares against, and fraud reporting filters on `variance_g`; read out of a
-- TEXT JSON document both would be unindexable full scans. All four are NULL for
-- every other movement type, so stacking and picking are untouched.
CALL _pk_add_col('entity_movement_details', 'tare_weight_kg',
                 'DECIMAL(12,3) NULL AFTER picked_quantity');
CALL _pk_add_col('entity_movement_details', 'weight_kg',
                 'DECIMAL(12,3) NULL AFTER tare_weight_kg');
CALL _pk_add_col('entity_movement_details', 'expected_weight_kg',
                 'DECIMAL(12,3) NULL AFTER weight_kg');
CALL _pk_add_col('entity_movement_details', 'variance_g',
                 'INT NULL AFTER expected_weight_kg');

-- idx_emd_entity serves "has this label ever been used?" — the single-use check at
-- bind time and the label scan at the dispatch gate. It CANNOT be a UNIQUE key: the
-- table is partitioned, MySQL requires the partition column in every unique index,
-- and one including created_on would be unique only per month. The single-use rule
-- is therefore an application check over this index, which is sufficient: there is
-- exactly one physical sticker.
CALL _pk_add_idx('entity_movement_details', 'idx_emd_entity',
                 'KEY idx_emd_entity (entity_id, entity_type)');
CALL _pk_add_idx('entity_movement_details', 'idx_emd_variance',
                 'KEY idx_emd_variance (variance_g)');


-- ---- 2. product_uom ---------------------------------------------------------
--
-- The weight of one rung's packaging, excluding the stock inside it. It is what lets
-- a sealed supplier carton be weight-checked at all: a built box is weighed empty
-- because nobody knows its weight in advance, but a sealed carton cannot be emptied
-- to find out. The rung is identified by matching the scanned quantity against
-- factor_to_base — which works precisely because the printed codes carry no
-- pack-level field.
--
-- NOTE: until this column is POPULATED, weight verification cannot be switched on
-- for any SKU scanned above the retail rung. The column existing is not enough.
CALL _pk_add_col('product_uom', 'pack_tare_kg',
                 'DECIMAL(12,3) NULL AFTER factor_to_base');


-- ---- 3. potential_order -----------------------------------------------------
--
-- Where a short-closed order records WHY. Already shipped as
-- migration_short_pack_reason.sql, repeated here guarded because a database built
-- from the DDL alone never got it — and /packing/jobs/{id}/submit writes it.
CALL _pk_add_col('potential_order', 'short_pack_reason',
                 'VARCHAR(255) NULL AFTER box_count');


-- ---- 4. The packer role — DELIBERATELY NOT CREATED --------------------------
--
-- Packing ships DARK. Every /api/v1/packing/* route is gated on
-- rbac.P.INVENTORY_PACK, and that code is granted to NO role and NO user, so the
-- only account that can reach packing is `admin` — `_legacy_codes_for_user`
-- returns the full code set for admin and derives nothing for anyone else. The
-- handheld's Packing tile reads the same permission list, so it stays hidden on
-- every other device.
--
-- This is the whole off switch. Do not add a grant here "for later": the moment
-- `inventory:pack` reaches a role that somebody holds, packing is live for them.
--
-- The `inventory:pack` row already exists in `permissions` (all 27 codes are
-- seeded), so there is nothing to insert even to make the code known.
--
-- TO TURN PACKING ON, when the bench, the scale and the label format are ready:
--
--   INSERT IGNORE INTO roles (name, description, all_warehouses, eway_bill_admin,
--                             eway_bill_filling, supply_sheet)
--   VALUES ('packer',
--           'Handheld packing station. Weight-verified carton packing only.',
--           0, 0, 0, 0);
--
--   INSERT IGNORE INTO role_permissions (role_id, permission_id)
--   SELECT r.role_id, p.permission_id
--   FROM roles r
--   JOIN permissions p ON p.code IN ('inventory:pack', 'inventory:read',
--                                    'order:read', 'catalog:read')
--   WHERE r.name = 'packer';
--
-- ...and then give the packer BOTH a `user_roles` row and a
-- `user_warehouse_company` row. `get_user_permission_codes` reads
-- permissions ⋈ role_permissions ⋈ user_roles; a user carrying only
-- `users.role = 'packer'` falls through to the legacy derivation, which cannot
-- produce `inventory:pack` — so the role alone is a silent 403. Creating the user
-- through the admin Users screen writes `user_roles` for you.

-- ---- cleanup ----------------------------------------------------------------
DROP PROCEDURE IF EXISTS _pk_add_col;
DROP PROCEDURE IF EXISTS _pk_add_idx;
DROP PROCEDURE IF EXISTS _pk_modify_col;


-- =============================================================================
-- Verification (run manually; none of it changes anything)
-- =============================================================================
-- SHOW COLUMNS FROM entity_movement_details
--   WHERE Field IN ('entity_id','tare_weight_kg','weight_kg','expected_weight_kg','variance_g');
-- SHOW INDEX FROM entity_movement_details WHERE Key_name LIKE 'idx_emd_%';
-- SHOW COLUMNS FROM product_uom WHERE Field = 'pack_tare_kg';
-- SELECT r.name, p.code FROM roles r
--   JOIN role_permissions rp ON rp.role_id = r.role_id
--   JOIN permissions p ON p.permission_id = rp.permission_id
--  WHERE r.name = 'packer';
--
-- PREREQUISITE — PACKING_DESIGN.md §6.5 Q1. A picklist containing a SKU with no unit
-- weight cannot be weight-reconciled at all, and poor coverage can invalidate the
-- module for a company. Run this before enabling packing for one:
--
-- SELECT company_id,
--        COUNT(*)                           AS skus,
--        SUM(weight IS NULL OR weight <= 0) AS missing_weight,
--        SUM(weight > 0 AND weight < 0.030) AS below_verify_floor
-- FROM product GROUP BY company_id;
