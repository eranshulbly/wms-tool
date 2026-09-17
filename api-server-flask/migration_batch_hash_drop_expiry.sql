-- Recompute sku_batch.batch_hash without expiry in the identity.
--
-- Batch identity changed from (sku_id, batch_number, expiry) to (sku_id, batch_number):
-- expiry is an attribute of a batch, not part of what makes it "the same batch". Cadila's
-- own documents disagree with each other on a batch's expiry often enough (batch EA26223:
-- 05/2028 on the credit note and the PO receipts export, 07/2028 on the tax invoice that
-- actually received it) that hashing expiry in was forking one physical lot into two
-- sku_batch rows the moment a document printed the wrong one — a phantom batch with a
-- price but no stock ever received into it, and a perfectly in-stock batch reported as
-- "not in inventory" to any order line naming the other expiry.
--
-- See api/modules/inventory/ingestion/service.py::batch_hash for the code-side half of
-- this fix. This migration re-hashes every existing row so old rows become findable
-- under the new formula too — without it, the code fix alone makes EVERY existing batch
-- look new on its next touch, creating a duplicate for all of them, not just EA26223.
--
-- Stored expiry values are NOT touched — only the hash. A wrong expiry already on file
-- (like EA26223's) is a separate, deliberate non-fix: correcting it needs someone to
-- confirm which document is actually right, not a migration to guess at it.

-- ── Step 1 — MUST run first. Confirms it's safe to re-hash with a plain UPDATE ────────
-- If this returns any rows, STOP: those are batches that already forked into more than
-- one sku_batch row over a differing expiry (the EA26223 failure mode already having
-- happened). They must be merged by hand — repoint fc_sku_price_details, fc_entity_stock,
-- fc_entity_stock_ledger, transferin_info and potential_order_product.batch_id from the
-- duplicate row(s) onto one survivor, then delete the duplicates — before Step 2 can run
-- without hitting the UNIQUE constraint on batch_hash.
--
-- As of 2026-09-17 this returned zero rows in both dev and production.

SELECT sku_id,
       JSON_UNQUOTE(JSON_EXTRACT(batch_params, '$.batch_number')) AS batch_number,
       COUNT(*) AS row_count,
       GROUP_CONCAT(id) AS sku_batch_ids,
       GROUP_CONCAT(JSON_UNQUOTE(JSON_EXTRACT(batch_params, '$.expiry'))) AS expiries
  FROM sku_batch
 GROUP BY sku_id, JSON_UNQUOTE(JSON_EXTRACT(batch_params, '$.batch_number'))
HAVING COUNT(*) > 1;

-- ── Step 2 — the actual migration. Safe to re-run (already-correct rows are a no-op). ──

UPDATE sku_batch
   SET batch_hash = SHA2(
         CONCAT(sku_id, '|',
                UPPER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(batch_params, '$.batch_number'))))),
         256)
 WHERE batch_hash != SHA2(
         CONCAT(sku_id, '|',
                UPPER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(batch_params, '$.batch_number'))))),
         256);
