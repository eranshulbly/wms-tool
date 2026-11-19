# -*- encoding: utf-8 -*-
"""Tables owned by sales.beat_outstanding. Each upload is loaded in one transaction. The
Beat Plan is a snapshot (an upload REPLACES its rows); the Outlet Master is incremental (an
upload adds new outlets and updates the ones in the file, by Outlet_Id; the rest are kept).

  bo_outlet        DMS Outlet Master — which beat (and city) each outlet is on, and its
                   GSTIN, which gives a picklist its City (incremental)
  bo_beat_plan     DMS User Beat Details — which beats each executive covers on a date
  bo_bill          no longer written: the Tally outstanding report is never stored —
                   the page sends it with each request (service.read_outstanding)
  bo_upload_log    one row per upload, for "last uploaded"
  bo_exec_beat     every beat each executive owns, kept by hand on the page (not an
                   upload) — the dealers on the executive's cash-discount sheet

A Tally party is placed on a beat by name: `name_key` (see parser.name_key) on both
sides. The Outlet Master's Beat_ID is the same id the beat plan carries, so beat_id is
the join key between the two DMS feeds.
"""

from api.shared.schema_registry import register_table


register_table("bo_outlet", """
CREATE TABLE IF NOT EXISTS bo_outlet (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    outlet_id     VARCHAR(64)  NOT NULL DEFAULT '',
    outlet_name   VARCHAR(255) NOT NULL,
    name_key      VARCHAR(255) NOT NULL,
    beat_id       VARCHAR(64)  NOT NULL DEFAULT '',
    beat_name     VARCHAR(255) NOT NULL DEFAULT '',
    city          VARCHAR(128) NOT NULL DEFAULT '',
    distributor   VARCHAR(255) NOT NULL DEFAULT '',
    gstin         VARCHAR(20)  NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    KEY idx_bo_outlet_name (company_id, name_key),
    KEY idx_bo_outlet_gstin (company_id, gstin),
    KEY idx_bo_outlet_beat (company_id, beat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=110)


register_table("bo_beat_plan", """
CREATE TABLE IF NOT EXISTS bo_beat_plan (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    user_id       VARCHAR(64)  NOT NULL DEFAULT '',
    se_name       VARCHAR(255) NOT NULL,
    plan_date     DATE NOT NULL,
    beat_id       VARCHAR(64)  NOT NULL,
    beat_name     VARCHAR(255) NOT NULL DEFAULT '',
    total_outlets INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_bo_beat_plan_date (company_id, plan_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=111)


register_table("bo_bill", """
CREATE TABLE IF NOT EXISTS bo_bill (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    distributor   VARCHAR(255) NOT NULL DEFAULT '',
    party_name    VARCHAR(255) NOT NULL,
    name_key      VARCHAR(255) NOT NULL,
    bill_date     DATE NOT NULL,
    ref_no        VARCHAR(128) NOT NULL,
    amount        DECIMAL(16,2) NOT NULL DEFAULT 0,
    -- Tally's Opening Amount, where the report prints one (NULL: the report has only
    -- the pending amount)
    opening       DECIMAL(16,2) NULL,
    due_on        DATE NOT NULL,
    PRIMARY KEY (id),
    KEY idx_bo_bill_name (company_id, name_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=112)


register_table("bo_upload_log", """
CREATE TABLE IF NOT EXISTS bo_upload_log (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    feed          VARCHAR(32)  NOT NULL,
    -- outstanding only: whose Tally report this is, and the last day it covers
    distributor   VARCHAR(255) NOT NULL DEFAULT '',
    report_to     DATE NULL,
    filename      VARCHAR(255) NOT NULL DEFAULT '',
    row_count     INT NOT NULL DEFAULT 0,
    uploaded_by   VARCHAR(100) NOT NULL DEFAULT '',
    uploaded_on   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_bo_upload_log_feed (company_id, feed, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=113)


register_table("bo_exec_beat", """
CREATE TABLE IF NOT EXISTS bo_exec_beat (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    se_name       VARCHAR(255) NOT NULL,
    beat_name     VARCHAR(255) NOT NULL,
    updated_by    VARCHAR(100) NOT NULL DEFAULT '',
    updated_on    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_bo_exec_beat (company_id, se_name, beat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=114)


_GSTIN_READY = False


def ensure_outlet_gstin():
    """bo_outlet.gstin — the registry only creates tables, so a database that already had
    bo_outlet gets the column (and its index) here. Once per process; idempotent."""
    global _GSTIN_READY
    if _GSTIN_READY:
        return
    from api.shared.db_manager import mysql_manager
    has_col = mysql_manager.execute_query(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'bo_outlet'
             AND COLUMN_NAME = 'gstin'""")
    if not has_col:
        mysql_manager.execute_query(
            "ALTER TABLE bo_outlet ADD COLUMN gstin VARCHAR(20) NOT NULL DEFAULT '' AFTER distributor, "
            "ADD KEY idx_bo_outlet_gstin (company_id, gstin)", fetch=False)
    _GSTIN_READY = True
