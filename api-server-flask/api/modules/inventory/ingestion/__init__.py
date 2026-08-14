# -*- encoding: utf-8 -*-
"""inventory.ingestion — inbound supplier documents (Cadila flow).

Reads the supplier's PDF paperwork and turns it straight into stock:

    GRN line
     ├─ product                reuse if it exists, create it if it does not
     ├─ sku_batch              reuse the batch if it exists, else create it
     ├─ transferin_info        one row per invoice line, transferin_id = the invoice
     ├─ fc_entity_stock        quantity at location 8 (unstacked), bin 0
     ├─ fc_entity_stock_ledger the movement
     └─ fc_sku_price_details   MRP, landing price and credit-note rate

The invoice itself is not stored — its lines ARE the `transferin_info` rows. Credit and
debit notes move no goods; they resolve the product and batch only so the price
adjustment lands on the right one.

`fc_sku_price_details` is the single table this module owns. Everything else it writes
already existed.

Three things about this supplier drive the design:
  * documents carry no product code, only a printed name and pack, so the name within the
    company is the identity and a missing product is created rather than queued;
  * a credit note carries a quantity yet moves no stock at all, so the movement effect
    follows the document kind and is never inferred from the quantity;
  * stock is batch-tracked with expiry, so FEFO — not bin priority — orders picking.
"""
