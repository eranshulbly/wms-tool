-- =============================================================================
-- Migration: drop the simplified v2-port inventory tables.
--
-- Replaced by the bin- and batch-level model in
-- api/modules/inventory/GRN_STACKING_DESIGN.md:
--
--   stock                  -> fc_entity_stock          (per location + bin + batch,
--                                                       includes unstacked at location 8)
--   inventory_transactions -> fc_entity_stock_ledger   (append-only)
--   picklists              -> entity_movement_request  (movement_type = 'picking')
--   picklist_items         -> entity_movement_details + entity_movement_recommendation
--                             -> fc_entity_recommendation
--
-- The /api/v1/inventory endpoints were redesigned onto the new model in the same
-- change, so nothing reads these tables any more. Safe to re-run.
-- =============================================================================

DROP TABLE IF EXISTS picklist_items;
DROP TABLE IF EXISTS picklists;
DROP TABLE IF EXISTS inventory_transactions;
DROP TABLE IF EXISTS stock;
