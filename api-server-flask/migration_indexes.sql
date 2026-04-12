-- =============================================================================
-- Performance Indexes for 100-150 orders/day workload
-- At this rate: ~55k orders/year, ~1.5M total rows across all tables after 3 years
--
-- Run once: mysql -u root -p warehouse_management < migration_indexes.sql
-- Safe to re-run (uses IF NOT EXISTS pattern via CREATE INDEX ... IGNORE)
-- =============================================================================

-- ── potential_order (hottest table) ──────────────────────────────────────────

-- Dashboard counts by status (WHERE status = ?)
ALTER TABLE potential_order
    ADD INDEX IF NOT EXISTS idx_po_status (status);

-- Warehouse-level order views (WHERE warehouse_id = ? AND status = ?)
ALTER TABLE potential_order
    ADD INDEX IF NOT EXISTS idx_po_warehouse_status (warehouse_id, status);

-- Paginated order list sorted by date (ORDER BY created_at DESC)
ALTER TABLE potential_order
    ADD INDEX IF NOT EXISTS idx_po_created_at (created_at DESC);

-- Company-filtered queries
ALTER TABLE potential_order
    ADD INDEX IF NOT EXISTS idx_po_company_status (company_id, status);

-- ── order_status_history (grows ~6x orders = ~300k rows/year) ────────────────

-- Fetching history for a specific order (WHERE order_id = ? ORDER BY changed_at)
ALTER TABLE order_status_history
    ADD INDEX IF NOT EXISTS idx_osh_order_changed (order_id, changed_at);

-- ── invoice (1:1 with orders, ~55k/year) ─────────────────────────────────────

-- Join from order to invoice
ALTER TABLE invoice
    ADD INDEX IF NOT EXISTS idx_invoice_order_id (original_order_id);

-- Dealer invoices list (WHERE dealer_id = ? ORDER BY created_at DESC)
ALTER TABLE invoice
    ADD INDEX IF NOT EXISTS idx_invoice_dealer_created (dealer_id, created_at DESC);

-- Dashboard: GROUP BY DATE(created_at) for daily invoice stats
ALTER TABLE invoice
    ADD INDEX IF NOT EXISTS idx_invoice_created_at (created_at);

-- Company invoices
ALTER TABLE invoice
    ADD INDEX IF NOT EXISTS idx_invoice_company (company_id);

-- ── invoice_item (grows ~8-10x orders = ~500k rows/year) ─────────────────────
-- If you have an invoice_item table, these are critical:
-- ALTER TABLE invoice_item
--     ADD INDEX IF NOT EXISTS idx_ii_invoice_id (invoice_id);

-- ── order_box (2-3 per order = ~150k rows/year) ───────────────────────────────
ALTER TABLE order_box
    ADD INDEX IF NOT EXISTS idx_ob_order_id (order_id);

-- ── jwt_token_blocklist (grows with logins, prune periodically) ───────────────
-- Fast lookup during auth
ALTER TABLE jwt_token_blocklist
    ADD INDEX IF NOT EXISTS idx_jwt_created (created_at);

-- =============================================================================
-- Verify indexes
-- =============================================================================
SELECT
    TABLE_NAME,
    INDEX_NAME,
    COLUMN_NAME,
    SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'warehouse_management'
  AND INDEX_NAME != 'PRIMARY'
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
