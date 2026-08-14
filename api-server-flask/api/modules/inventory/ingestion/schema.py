# -*- encoding: utf-8 -*-
"""Tables owned by inventory.ingestion.

  fc_sku_price_details     MRP and landing price of a SKU in a given batch

The invoice itself is not stored. Its lines become `transferin_info` rows, keyed by
`transferin_id` (the invoice number verbatim). What the paperwork said beyond product,
quantity, MRP and rate is discarded on purpose.

The unique key here carries `company_id`. That is deliberate: keys written at a narrower
grain than the thing they protect let a second tenant collide with rows it cannot see or
delete. `part_groups.uq_period_part` and `fc_entity_stock.planogram_id_new` both had to be
widened for exactly that reason; `dealer.idx_dealer_code` still has it.
"""

from api.shared.schema_registry import register_table


# ── SKU price details ────────────────────────────────────────────────────────
# What a SKU costs, and what it retails for, in a specific batch. One row per
# (company, sku, batch).
#
# MRP belongs here rather than on the batch because MRP is commercial, not physical: the
# same manufacturing lot can be re-priced without becoming a different lot. Keeping it out
# of batch identity is also what stops every credit note forking a phantom batch — the
# supplier prints MRP 0.00 on all of them.
#
# `landing_price` is the receipt rate, `cn_rate` the credit-note rate against the same
# batch. The effective cost is computed where it is needed:
#
#     final landing price          = landing_price - cn_rate
#     final landing price inc-GST  = (landing_price - cn_rate) * (1 + gst_rate / 100)
#
# Neither is stored, so there is no second copy to drift. Both columns are SET rather than
# accumulated, which is what makes a re-uploaded invoice harmless: writing the same value
# twice is the same as writing it once. An accumulating column would silently double.
#
# The consequence to know: a SECOND credit note against the same batch overwrites the
# first rather than adding to it. That matches the observed paperwork — one adjustment per
# receipt — but it is an assumption, not a guarantee.
register_table("fc_sku_price_details", """
CREATE TABLE IF NOT EXISTS fc_sku_price_details (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id          INT NOT NULL,
    planogram_id        INT UNSIGNED NOT NULL DEFAULT 0,
    entity_id           INT UNSIGNED NOT NULL,
    entity_type         VARCHAR(32) NOT NULL DEFAULT 'sku',
    batch_id            BIGINT UNSIGNED NOT NULL,

    mrp                 DECIMAL(12,4) NOT NULL DEFAULT 0,
    landing_price       DECIMAL(12,4) NOT NULL DEFAULT 0,
    cn_rate             DECIMAL(12,4) NOT NULL DEFAULT 0,

    -- Total GST percentage on the receipt line, however the supplier split it. The two
    -- printed layouts both come to the same total — IGST 5.00, or SGST 2.50 + CGST 2.50 —
    -- so one figure is enough to gross the landing price up, and which halves it was made
    -- of does not affect the cost.
    gst_rate            DECIMAL(6,2) NOT NULL DEFAULT 0,

    uom                 VARCHAR(16) NOT NULL DEFAULT 'strip',
    quantity_received   DECIMAL(16,4) NOT NULL DEFAULT 0,
    grn_reference       VARCHAR(64) NOT NULL DEFAULT '',
    cn_reference        VARCHAR(64) NOT NULL DEFAULT '',

    created_by          VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by          VARCHAR(255) NOT NULL DEFAULT 'system',

    PRIMARY KEY (id),
    UNIQUE KEY uq_sku_batch_price (company_id, entity_id, entity_type, batch_id),
    KEY idx_batch (batch_id),
    KEY idx_landing (company_id, landing_price)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=46)
