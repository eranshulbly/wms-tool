-- Migration: Add short_pack_reason to potential_order table
-- This is a non-breaking nullable addition — no data backfill required.
ALTER TABLE potential_order
    ADD COLUMN short_pack_reason VARCHAR(255) NULL AFTER box_count;
