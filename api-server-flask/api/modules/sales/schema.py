# -*- encoding: utf-8 -*-
"""
sales module — table DDL (registered with the schema registry).

The four feeds behind Sales-Executive Analytics. All of them are LOADED, never entered by
hand: modules/sales/uploads/router.py parses the monthly spreadsheets and writes them;
modules/sales/field_sales/service.py and modules/sales/target_tracker/service.py read
them back. See
docs/ANALYTICS_CALCULATIONS.md for the calculations these support.

  busy_sales_data          one row per sales line exported from Busy
  part_groups              part -> part-group mapping, per period
  dealer_target            EVERY dealer target — category / scheme / part-group level,
                           in rupees or units, per period. Was dealer_part_group_target.
  dealer_money_target      GONE. Rupee targets used to live here, at category grain only.
                           _migrate_target_type() copies them into dealer_target as
                           target_level='category', target_type='value'. No longer
                           registered, so it is never recreated; see the note where its
                           DDL used to be.

Plus the field-sales visit log:

  dealer_visits            check-in/check-out per executive per dealer

Conventions
-----------
* `period` / `target_period` is a DATE pinned to the FIRST DAY of the month (e.g.
  2026-07-01). It is the definitive period key — it cannot collide across years.
* Attribution is a name string-match: busy_sales_data.particulars = dealer.name. So
  `particulars` deliberately mirrors dealer.name's type and collation, or the join
  degrades to a scan.
* Every upload REPLACES its period (DELETE by period, then INSERT). The UNIQUE keys below
  are what stop a malformed file from double-loading a period — without them a duplicated
  row would fan out the analytics joins and silently inflate every total.
* No FKs to dealer/company: the loader resolves dealer names to ids itself and reports
  unknown dealers as per-row errors, which is friendlier than an FK violation aborting a
  whole upload.
"""

from api.shared.schema_registry import register_table

# One row per sales line from the Busy export. Not period-scoped — the loader replaces only
# the dates a given file actually covers, so several months coexist here.
register_table("busy_sales_data", """
CREATE TABLE IF NOT EXISTS busy_sales_data (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    sale_date   DATE NOT NULL,
    voucher_no  VARCHAR(100) DEFAULT NULL,
    particulars VARCHAR(255) DEFAULT NULL,
    item_code   VARCHAR(100) DEFAULT NULL,
    quantity    DECIMAL(14,4) NOT NULL DEFAULT 0,
    unit        VARCHAR(20) DEFAULT NULL,
    price       DECIMAL(14,4) NOT NULL DEFAULT 0,
    amount      DECIMAL(16,4) NOT NULL DEFAULT 0,
    -- GST is a flat 0.18 of the line amount. Generated rather than written by the
    -- loader so it can never disagree with `amount`, and STORED rather than VIRTUAL
    -- because analytics SUMs it over the whole feed. Keep every literal percent sign
    -- out of this DDL: execute_query interpolates the query against its params, so a
    -- bare one raises "not enough arguments for format string" at boot.
    gst             DECIMAL(16,4) AS (ROUND(amount * 0.18, 4)) STORED,
    amount_with_gst DECIMAL(16,4) AS (ROUND(amount * 1.18, 4)) STORED,
    company_id  INT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_company_sale_date (company_id, sale_date),
    KEY idx_particulars (particulars),
    KEY idx_item_code (item_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=60)


# Part -> part-group for one period. uq_period_part matters: analytics LEFT JOINs this on
# part_number, so a duplicated part would multiply every sales row it matches and overstate
# quantities.
#
# The key is created here as (time_period, part_number) and widened to
# (company_id, time_period, part_number) by _migrate_part_groups_company_uq() in
# db_manager.py — company_id is added by the _COMPANY_ID_TABLES manifest, which is the
# authority for the tenant column, so it does not exist yet at CREATE TABLE time. The
# company has to be in the key: the upload replaces a period with
# `DELETE ... WHERE time_period=%s AND company_id=%s`, and a key that ignores company
# rejects one tenant's rows over another tenant's, which that delete cannot clear.
register_table("part_groups", """
CREATE TABLE IF NOT EXISTS part_groups (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    part_number VARCHAR(100) NOT NULL,
    description VARCHAR(500) DEFAULT NULL,
    part_group  VARCHAR(150) DEFAULT NULL,
    scheme      VARCHAR(150) DEFAULT NULL,
    time_period DATE NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_period_part (time_period, part_number),
    KEY idx_part_group (part_group),
    KEY idx_period (time_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=61)


# dealer_money_target (order=62) USED TO BE REGISTERED HERE. It held the rupee target at
# (dealer, category, period) — a grain with nowhere to put a scheme, which is what forced
# the discriminator columns onto dealer_target and made this table redundant.
#
# It is deliberately NOT registered any more, because the registry only issues CREATE
# TABLE IF NOT EXISTS: leaving it here would recreate an empty copy on every boot of every
# database it has been dropped from, and an empty table that nothing reads is an invitation
# to start writing to it again.
#
# Deleting the registration does NOT delete the table. A database that still has it keeps
# it, and _migrate_target_type() still copies its rows into dealer_target on the boot that
# introduces target_level — that import is guarded on the table existing, so it is a no-op
# once the table is gone and a full migration where it is not. Dropping it is a manual
# step, taken after confirming the import ran; there is no automatic DROP, because a
# migration that destroys the only copy of a table it just read is one bug away from
# destroying the data too.


# EVERY dealer target, at whatever level and in whatever unit it is set.
#
# One row per (dealer, category, level, scheme, part-group, product, type) per period.
# Analytics SUMs the target over the dealers in scope, so a duplicate row here inflates
# the target — hence the unique key on the full grain.
#
# Renamed from dealer_part_group_target, which it outgrew: it began as part-group
# quantity targets and now carries category- and scheme-level targets in rupees as well as
# units. _migrate_dealer_target_rename() moves an existing table over, and runs before
# every other target migration so they all see the new name.
#
# Two columns say what a row MEANS, and nothing about a target may be inferred without
# reading them:
#
#   target_level  which grain the target is set at, and therefore which sales roll up to
#                 it. Stored, never derived from which of scheme/part_group is blank:
#                 _load_part_groups writes `part_group = group or scheme` for a basket
#                 that isn't broken into groups, so a scheme-level and a part-group-level
#                 row can carry identical text in both columns and still mean different
#                 things.
#   target_type   'value' -> the number lives in target_value and is measured against
#                 GST-inclusive rupees sold; 'qty' -> it lives in target_qty and is
#                 measured against units sold.
#
# The value and the quantity live in SEPARATE columns rather than one overloaded amount.
# The unused one stays 0, so any query that sums the wrong column reads 0 for those rows
# instead of adding rupees into a unit total — a caller that forgets to filter on
# target_type under-reports visibly rather than over-reporting invisibly.
#
# target_uom refines 'qty': '' means the target counts units exactly as the Busy feed
# bills them, 'litres' means it counts volume and the sold side must be scaled by
# product.litres_per_unit. Without it an Oil target of 100 litres would be compared
# against bottles sold.
#
# THE RULE THAT IS NOT IN THE SCHEMA: levels are never added together. A dealer's Parts
# rupee target and its Basket 1 rupee target are both 'value' rows on the same category,
# but the basket is a breakdown INSIDE the category target, not an addition to it. See
# target_tracker/service.py::_target_at, which is the only place allowed to choose.
register_table("dealer_target", """
CREATE TABLE IF NOT EXISTS dealer_target (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dealer_id     INT NOT NULL,
    category_id   INT NOT NULL,
    -- A target set against one specific product rather than a part group. Nothing writes
    -- it yet, so every current target carries the 0 sentinel meaning "no single product".
    -- NOT NULL DEFAULT 0 for the same reason `scheme` is NOT NULL DEFAULT '': it is part
    -- of uq_dt_grain, and MySQL treats every NULL in a UNIQUE index as distinct, so a
    -- nullable product_id would let the key wave through duplicates it exists to block.
    product_id    INT NOT NULL DEFAULT 0,
    part_group    VARCHAR(150) NOT NULL,
    scheme        VARCHAR(150) NOT NULL DEFAULT '',
    -- 'category' | 'scheme' | 'part_group' | 'product'. Same NOT NULL DEFAULT reasoning
    -- as product_id above — it sits in uq_dt_grain.
    target_level  VARCHAR(20) NOT NULL DEFAULT 'part_group',
    -- 'qty' | 'value'. In the key too: a dealer may carry both a unit and a rupee target
    -- on the same scheme, and without this the second would be rejected as a duplicate.
    target_type   VARCHAR(10) NOT NULL DEFAULT 'qty',
    -- '' | 'litres'. NOT in the key: it qualifies how target_qty is counted, it does not
    -- make a second target. Two rows differing only by uom are a data error, not a pair.
    target_uom    VARCHAR(20) NOT NULL DEFAULT '',
    target_qty    DECIMAL(14,4) NOT NULL DEFAULT 0,
    target_value  DECIMAL(16,4) NOT NULL DEFAULT 0,
    month         VARCHAR(30) DEFAULT NULL,
    target_period DATE NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dt_grain (dealer_id, category_id, target_level, product_id, scheme,
                            part_group, target_type, target_period),
    KEY idx_target_period (target_period),
    KEY idx_part_group (part_group),
    KEY idx_dt_category (category_id),
    KEY idx_dt_product (product_id),
    KEY idx_dt_level (target_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=63)


# Field-sales visit log — one row per check-in, closed out by check_out_at.
# DDL kept identical to migration_v2_api.sql so an existing deployment that already ran
# that migration is a no-op here rather than a conflict.
register_table("dealer_visits", """
CREATE TABLE IF NOT EXISTS dealer_visits (
    visit_id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id              INT NOT NULL,
    dealer_id            INT NOT NULL,
    company_id           INT,
    check_in_at          DATETIME NOT NULL,
    check_in_latitude    DECIMAL(10,7),
    check_in_longitude   DECIMAL(10,7),
    check_in_accuracy_m  FLOAT,
    check_out_at         DATETIME,
    check_out_latitude   DECIMAL(10,7),
    check_out_longitude  DECIMAL(10,7),
    check_out_accuracy_m FLOAT,
    status               VARCHAR(20) NOT NULL DEFAULT 'active',
    notes                TEXT,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_dv_user (user_id),
    INDEX idx_dv_dealer (dealer_id),
    INDEX idx_dv_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=64)
