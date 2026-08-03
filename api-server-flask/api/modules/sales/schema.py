# -*- encoding: utf-8 -*-
"""
sales module — table DDL (registered with the schema registry).

The four feeds behind Sales-Executive Analytics. All of them are LOADED, never entered by
hand: modules/sales/analytics/router_uploads.py parses the monthly spreadsheets and writes
them; modules/sales/analytics/service.py + router.py read them back. See
docs/ANALYTICS_CALCULATIONS.md for the calculations these support.

  busy_sales_data          one row per sales line exported from Busy
  part_groups              part -> part-group mapping, per period
  dealer_money_target      rupee target, per dealer per period
  dealer_part_group_target quantity target, per dealer x part-group per period

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


# Part -> part-group for one period. UNIQUE (period, part_number) matters: analytics
# LEFT JOINs this on part_number, so a duplicated part would multiply every sales row it
# matches and overstate quantities.
register_table("part_groups", """
CREATE TABLE IF NOT EXISTS part_groups (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    part_number VARCHAR(100) NOT NULL,
    description VARCHAR(500) DEFAULT NULL,
    part_group  VARCHAR(150) DEFAULT NULL,
    scheme      VARCHAR(150) DEFAULT NULL,
    month       VARCHAR(30) DEFAULT NULL,
    period      DATE NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_period_part (period, part_number),
    KEY idx_part_group (part_group),
    KEY idx_period (period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=61)


# The rupee target: one row per category x dealer per period. The unique key IS the
# grain — the upload replaces by (period, category), so a second row for the same
# (dealer, category, period) would double the target rather than update it.
register_table("dealer_money_target", """
CREATE TABLE IF NOT EXISTS dealer_money_target (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dealer_id     INT NOT NULL,
    category_id   INT NOT NULL,
    target_period DATE NOT NULL,
    value_target  DECIMAL(16,4) NOT NULL DEFAULT 0,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dmt_grain (dealer_id, category_id, target_period),
    KEY idx_target_period (target_period),
    KEY idx_dmt_category (category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=62)


# The quantity target: one row per category x scheme x part-group x dealer per period.
# Analytics SUMs target_qty over the dealers in scope, so a duplicate row here inflates
# the target — hence the unique key on the full grain.
register_table("dealer_part_group_target", """
CREATE TABLE IF NOT EXISTS dealer_part_group_target (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dealer_id     INT NOT NULL,
    category_id   INT NOT NULL,
    part_group    VARCHAR(150) NOT NULL,
    scheme        VARCHAR(150) NOT NULL DEFAULT '',
    target_qty    DECIMAL(14,4) NOT NULL DEFAULT 0,
    month         VARCHAR(30) DEFAULT NULL,
    target_period DATE NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dpgt_grain (dealer_id, category_id, scheme, part_group, target_period),
    KEY idx_target_period (target_period),
    KEY idx_part_group (part_group),
    KEY idx_dpgt_category (category_id)
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
