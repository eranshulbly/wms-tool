# -*- encoding: utf-8 -*-
"""Tables owned by sales.dealer_payments (the Dealer Payment Tracker).

  dpt_dealer             dealers, created from the Tally uploads: ledger name -> CAD-nnn
  dpt_upload             one row per file loaded (Export 1, Export 2)
  dpt_outstanding        Export 1 snapshots: pending bills per as-of date
  dpt_bill_adjustment    Export 1 voucher lines under each pending bill
  dpt_receipt            Export 2 receipts; each upload replaces its date window
  dpt_payment            payments logged in the app (BT / cash)
  dpt_manual_check       flags for a person to review; they never change a balance

Ledger names are stored with utf8mb4_0900_bin — binary and NO PAD — so MySQL compares
them exactly as Tally writes them: case, inner spaces and trailing spaces all count.
"""

from api.shared.schema_registry import register_table

_EXACT = 'CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin'

register_table("dpt_dealer", f"""
CREATE TABLE IF NOT EXISTS dpt_dealer (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id          INT NOT NULL,
    dealer_id           VARCHAR(16)  NOT NULL,
    tally_ledger_name   VARCHAR(255) {_EXACT} NOT NULL,
    dealer_name         VARCHAR(255) NOT NULL DEFAULT '',
    principal           VARCHAR(64)  NOT NULL DEFAULT '',
    town                VARCHAR(128) NOT NULL DEFAULT '',
    cheque_system_name  VARCHAR(255) {_EXACT} NOT NULL DEFAULT '',
    phone               VARCHAR(32)  NOT NULL DEFAULT '',
    salesman            VARCHAR(128) NOT NULL DEFAULT '',
    exclude_from_chase  TINYINT(1)   NOT NULL DEFAULT 0,
    active              TINYINT(1)   NOT NULL DEFAULT 1,
    first_txn_date      DATE NULL,
    source              VARCHAR(255) NOT NULL DEFAULT '',
    is_new              TINYINT(1)   NOT NULL DEFAULT 0,
    created_on          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dpt_dealer_id (company_id, dealer_id),
    UNIQUE KEY uq_dpt_dealer_ledger (company_id, tally_ledger_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=120)

register_table("dpt_upload", """
CREATE TABLE IF NOT EXISTS dpt_upload (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    kind          VARCHAR(16)  NOT NULL,
    filename      VARCHAR(255) NOT NULL DEFAULT '',
    as_of         DATE NULL,
    period_from   DATE NULL,
    period_to     DATE NULL,
    row_count     INT NOT NULL DEFAULT 0,
    warnings      TEXT NULL,
    uploaded_by   VARCHAR(100) NOT NULL DEFAULT '',
    uploaded_on   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_dpt_upload_kind (company_id, kind, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=121)

register_table("dpt_outstanding", """
CREATE TABLE IF NOT EXISTS dpt_outstanding (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id          INT NOT NULL,
    as_of_date          DATE NOT NULL,
    dealer_id           VARCHAR(16) NOT NULL,
    ref_no              VARCHAR(64) NOT NULL,
    kind                VARCHAR(16) NOT NULL DEFAULT '',
    bill_date           DATE NULL,
    opening_amt         DECIMAL(14,2) NULL,
    pending_amt_signed  DECIMAL(14,2) NOT NULL,
    due_on              DATE NULL,
    overdue_days        INT NULL,
    upload_id           BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dpt_outstanding (company_id, as_of_date, dealer_id, ref_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=122)

register_table("dpt_bill_adjustment", """
CREATE TABLE IF NOT EXISTS dpt_bill_adjustment (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    as_of_date    DATE NOT NULL,
    dealer_id     VARCHAR(16) NOT NULL,
    ref_no        VARCHAR(64) NOT NULL,
    vch_type      VARCHAR(64) NOT NULL DEFAULT '',
    vch_no        VARCHAR(64) NOT NULL DEFAULT '',
    vch_date      DATE NULL,
    amount        DECIMAL(14,2) NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dpt_adj (company_id, as_of_date, dealer_id, ref_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=123)

register_table("dpt_receipt", """
CREATE TABLE IF NOT EXISTS dpt_receipt (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    vch_no        VARCHAR(64) NOT NULL,
    vch_date      DATE NOT NULL,
    dealer_id     VARCHAR(16) NOT NULL,
    vch_type      VARCHAR(64) NOT NULL DEFAULT 'Receipt',
    amount        DECIMAL(14,2) NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dpt_receipt (company_id, vch_no, vch_date),
    KEY idx_dpt_receipt_date (company_id, vch_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=124)

register_table("dpt_payment", """
CREATE TABLE IF NOT EXISTS dpt_payment (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id        INT NOT NULL,
    dealer_id         VARCHAR(16)  NOT NULL,
    mode              VARCHAR(8)   NOT NULL,
    amount            DECIMAL(14,2) NOT NULL,
    payment_date      DATE NOT NULL,
    reference         VARCHAR(64)  NOT NULL DEFAULT '',
    proof_path        VARCHAR(255) NULL,
    proof_mime        VARCHAR(64)  NULL,
    note              VARCHAR(500) NOT NULL DEFAULT '',
    status            VARCHAR(12)  NOT NULL DEFAULT 'OPEN',
    matched_vch_no    VARCHAR(64)  NULL,
    matched_vch_date  DATE NULL,
    bounced_by_ref    VARCHAR(64)  NULL,
    created_by        VARCHAR(100) NOT NULL DEFAULT '',
    created_on        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by        VARCHAR(100) NOT NULL DEFAULT '',
    updated_on        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_dpt_payment_status (company_id, status),
    KEY idx_dpt_payment_dealer (company_id, dealer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=125)

register_table("dpt_manual_check", """
CREATE TABLE IF NOT EXISTS dpt_manual_check (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    fingerprint   VARCHAR(400) NOT NULL,
    flag_type     VARCHAR(24)  NOT NULL,
    dealer_id     VARCHAR(16)  NULL,
    details       TEXT NULL,
    reason        VARCHAR(500) NOT NULL DEFAULT '',
    active        TINYINT(1) NOT NULL DEFAULT 1,
    reviewed      TINYINT(1) NOT NULL DEFAULT 0,
    review_note   VARCHAR(500) NOT NULL DEFAULT '',
    reviewed_by   VARCHAR(100) NOT NULL DEFAULT '',
    reviewed_on   DATETIME NULL,
    first_seen    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dpt_manual_check (company_id, fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=126)
