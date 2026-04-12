-- Migration: box_count restructure
-- Replaces the pattern of creating N order_box rows with a single integer count,
-- and moves Order record creation from Packed → Invoice upload time.
--
-- Run steps in order on the live database before deploying the updated application.

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 1: Add box_count to the `order` table
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE `order`
    ADD COLUMN box_count INT NOT NULL DEFAULT 1
    AFTER status;

-- Backfill order.box_count from existing order_box rows
UPDATE `order` o
SET box_count = (
    SELECT COUNT(*)
    FROM order_box ob
    WHERE ob.order_id = o.order_id
)
WHERE EXISTS (
    SELECT 1 FROM order_box ob WHERE ob.order_id = o.order_id
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 2: Add box_count to the `potential_order` table
-- (box count is now stored here at Packed time; copied to `order` at Invoice time)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE potential_order
    ADD COLUMN box_count INT NOT NULL DEFAULT 1
    AFTER status;

-- Backfill potential_order.box_count from the linked order record
-- (for orders already at Invoiced / Dispatch Ready / Completed)
UPDATE potential_order po
SET box_count = (
    SELECT o.box_count
    FROM `order` o
    WHERE o.potential_order_id = po.potential_order_id
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1 FROM `order` o WHERE o.potential_order_id = po.potential_order_id
);
