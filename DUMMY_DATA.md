# Seeded and generated data — Cadila inventory ingestion

Read this before provisioning production. It lists **every row this feature can create
that a human did not type**, so nothing appears in a production database unexplained.

Kept current as the module changes. Last updated 2026-08-11 — the invoice is no longer
stored; its lines become `transferin_info` rows.

---

## 1. No dummy or sample data is created

The ingestion module ships with **no fixtures, no demo documents, no placeholder
products, and no example batches.** Nothing is inserted at boot and nothing is inserted
by deploying it.

If a screen is empty in production, it is empty because no document has been uploaded —
not because seed data is missing.

Only ONE new table is added — `fc_sku_price_details`. Everything else this flow writes
belongs to tables that already existed. The invoice itself is not stored: its lines
become `transferin_info` rows keyed by `transferin_id` (the digits of the invoice number),
with the printed number kept in `meta_info`.

---

## 2. Rows created automatically at runtime

These are created by the code, not by a person, the first time they are needed. They are
real operating data rather than dummy data — but they appear without anyone typing them,
so they are listed here.

| Table | Row | When | Why |
|---|---|---|---|
| `transferin_type` | `'CADILA_GRN'`, `'CADILA_CN'`, `'CADILA_DN'` | first time each document kind is seen | `transferin_info.transferin_type_id` is `NOT NULL` with no default. One row per kind, created once. They also disambiguate invoice numbers that reduce to the same digits — `P000002` and `PD00002` both yield `2`. Auto-increment ids — do **not** hard-code them. |
| `sku_batch` | one row per (SKU, batch number, expiry) | first time a batch is seen | Batch identity. See §4 — the hash convention matters. |
| `product` | one row per printed product name not already in the catalogue | on upload | **Auto-created.** The supplier's paperwork is the only description of these products that exists, so the printed name, pack and HSN become the product record. A typo on a PDF becomes a real product — see §5. |
| `fc_sku_price_details` | one row per (company, SKU, batch) | on upload | MRP, landing price, and the credit-note rate. Effective cost is computed on read as `landing_price - cn_rate` — not stored, so there is no second copy to drift. |
| `transferin_info` | one row per invoice line | GRN only | The invoice line itself. `transferin_id` = digits of the invoice number, full number in `meta_info`. |
| `fc_entity_stock` | upsert per (SKU, batch) | GRN only | Quantity at location 8, bin 0. |
| `fc_entity_stock_ledger` | one row per line | GRN only | The movement. |

No `upload_batches` row is written — this flow does not use it.

Nothing above is deleted by the module. `transferin_info` is append-only by design.

---

## 3. Provisioning required BEFORE the first upload

The module does **not** create these. It will fail or refuse without them, deliberately —
these are decisions, not defaults.

> **Already created in the dev database (2026-08-11):** one row in `company` —
> `company_id = 3, name = 'Cadila'`. Inserted by hand, guarded so re-running is a no-op.
> It is the only row anyone typed rather than uploaded. **Production needs the same row**,
> and its `company_id` will differ — nothing hard-codes it, but any data you migrate
> between environments must be re-pointed.

| Table | What is needed | Notes |
|---|---|---|
| `company` | the Cadila row | The operator picks the company at upload; it is never read from the PDF. |
| `warehouse` | at least one active warehouse | Selected in the upload form. `planogram_id` is taken as `warehouse_id`. |
| `user_warehouse_company` | the uploading admin mapped to that company + warehouse | Otherwise `resolve_company_scope` rejects the upload. |
| `planogram_locations` | id `8` (`unstacked`) | Already seeded by `LOCATION_SEED` in `db_manager`. Received stock lands here, bin `0`, and is picking-enabled so it is sellable before put-away. |

`product` is **not** a prerequisite: products are created from the document when the
catalogue does not have them. That is a convenience with a cost — see §5.

**Not created, and needed later:** there is no quarantine/expired location. `LOCATION_SEED`
has no non-picking location suitable for blocked stock (`4 return` means something else).
Expiry quarantine will need one — deliberately left out rather than invented, since it is
outside this build.

---

## 4. Two conventions this code establishes permanently

Both were previously undefined. The first write fixes them, and changing either one later
is expensive.

**Batch identity — `sku_batch.batch_hash`.** Nothing in the codebase populated this field
before now, so ingestion defines it:

```
sha256( "<sku_id>|<BATCH NUMBER UPPERCASED>|<expiry YYYY-MM-DD>" )
```

**MRP is deliberately excluded**, which departs from the comment in
`modules/platform/catalog/schema.py` stating that MRP is part of batch identity. Reason:
every credit/debit note in the sample corpus prints **MRP 0.00** while naming the batch it
adjusts — 22 of 22 note lines, no exceptions. An MRP-keyed hash therefore forks a second,
phantom `sku_batch` row for a lot that physically exists once, breaking FEFO and
traceability. Batch number plus expiry is also the regulatory identity: one manufacturing
lot, one recall unit. Price variation is carried by `fc_sku_price_details`, where it gets
history instead of a duplicate row.

Changing the hash inputs later re-hashes every batch and orphans the stock pointing at the
old ids through `uq_batch_hash`.

**Expiry normalisation.** Printed `3/28` is stored as **2028-03-31** — the last day of the
month. The stock is good for the whole month, and month-end makes "expired?" a plain date
comparison and FEFO a plain `ORDER BY`.

---

## 5. What to audit in production

- **Auto-created products.** Products now appear in the catalogue without anyone typing
  them, keyed on the printed name within the company. A misprint or a parse quirk becomes
  a real product, and near-duplicate names ("METBETIC GL1 TAB" vs "METBETIC GL1 TAB 10X15
  T") become two products. Review new arrivals:

  ```sql
  SELECT product_id, product_string, name, hsn_code, created_at
    FROM product WHERE company_id = ? ORDER BY product_id DESC;
  ```

- **`fc_sku_price_details` columns are SET, never accumulated.** That is what makes a
  re-uploaded file harmless — writing the same value twice equals writing it once. The
  consequence: a SECOND credit note against the same batch **replaces** the first rather
  than adding to it. Check for batches where a note landed before its receipt:

  ```sql
  SELECT * FROM fc_sku_price_details WHERE landing_price = 0 AND cn_rate > 0;
  ```

- **Duplicate receipts are blocked by an application check, not a constraint.** With no
  invoice table there is no unique key; `_already_received()` looks for existing
  `transferin_info` rows with the same planogram, type and `transferin_id`. Two truly
  simultaneous uploads of the same invoice could both pass it.

- **The total mismatch is no longer stored.** It is still computed at parse time and shown
  on the upload result, but with the invoice tables gone there is nowhere to keep it, so
  "which invoices don't add up" is no longer answerable by query — only by watching the
  upload screen as files go in.

  This matters more than it sounds. Across the 25-document sample, **9 carry a material
  gap** between the printed grand total and line amounts plus GST — seven between 0.0978%
  and 0.1012% of subtotal, one (`P000013`) at exactly 0.1000%: 1,080.00 on 1,080,000.00.
  `DIS AMT.` prints 0.00 on every one of them, so the deduction is undisclosed. The parser
  reproduces every printed line amount exactly across all 98 sample lines, so this is a
  question for the supplier, not a parsing defect — it is simply no longer recorded.
