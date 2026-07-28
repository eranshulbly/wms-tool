-- =============================================================================
-- Migration: remove the box concept.
--
-- Packing is now a pure order state transition; boxes are no longer built or
-- tracked. Drops the three box tables. Order.box_count / potential_order.box_count
-- (plain integer counts) are kept — they are unrelated to these tables.
--
-- Safe to run more than once (IF EXISTS). Apply against warehouse_management.
-- =============================================================================

DROP TABLE IF EXISTS box_product;
DROP TABLE IF EXISTS order_box;
DROP TABLE IF EXISTS box;
