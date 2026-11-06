# -*- encoding: utf-8 -*-
"""Tables owned by sales.tat_check. Every feed is a snapshot: each upload REPLACES the
company's rows for that feed, in one transaction.

  tat_inventory     DMS Inventory Report — current stock (Units, in pieces) per SKU, nothing else
  tat_dispatch      supplier's DISPATCH sheet — invoiced lines (billing document x SKU)
  tat_pending       supplier's PENDING sheet — PO lines not yet dispatched (Open Dlv Quantity)
  tat_grn           DMS GRN Approved Status Report (SKU-wise) — which invoices were received
  tat_upload_log    one row per upload, for "last updated"

The DISPATCH and PENDING sheets arrive in one workbook and are one upload (feed
'dispatch_pending'), so the two can never be from different days.

A dispatch line is IN TRANSIT until the GRN report shows it approved. The GRN's Bill_No
is the supplier's billing document, sometimes with the DMS order id appended
('126023937_16466'), so `billing_doc` holds the part before '_' and is the join key.
"""

from api.shared.schema_registry import register_table


register_table("tat_inventory", """
CREATE TABLE IF NOT EXISTS tat_inventory (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    sku_code      VARCHAR(128) NOT NULL,
    sku_name      VARCHAR(255) NOT NULL DEFAULT '',
    stock_qty     DECIMAL(14,3) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_tat_inventory_sku (company_id, sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=100)


register_table("tat_dispatch", """
CREATE TABLE IF NOT EXISTS tat_dispatch (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    upload_id     BIGINT UNSIGNED NOT NULL,
    plant         VARCHAR(128) NOT NULL DEFAULT '',
    billing_date  DATE NULL,
    billing_doc   VARCHAR(64)  NOT NULL,
    doc_ref_id    VARCHAR(64)  NOT NULL DEFAULT '',
    sku_code      VARCHAR(128) NOT NULL,
    sku_name      VARCHAR(255) NOT NULL DEFAULT '',
    qty           DECIMAL(14,3) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_tat_dispatch_sku (company_id, sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=101)


register_table("tat_pending", """
CREATE TABLE IF NOT EXISTS tat_pending (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id     INT NOT NULL,
    upload_id      BIGINT UNSIGNED NOT NULL,
    plant          VARCHAR(128) NOT NULL DEFAULT '',
    order_date     DATE NULL,
    po_number      VARCHAR(128) NOT NULL DEFAULT '',
    sales_doc      VARCHAR(64)  NOT NULL DEFAULT '',
    sales_doc_item VARCHAR(32)  NOT NULL DEFAULT '',
    sku_code       VARCHAR(128) NOT NULL,
    sku_name       VARCHAR(255) NOT NULL DEFAULT '',
    order_qty      DECIMAL(14,3) NOT NULL DEFAULT 0,
    delivered_qty  DECIMAL(14,3) NOT NULL DEFAULT 0,
    open_qty       DECIMAL(14,3) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_tat_pending_sku (company_id, sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=102)


register_table("tat_grn", """
CREATE TABLE IF NOT EXISTS tat_grn (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id     INT NOT NULL,
    upload_id      BIGINT UNSIGNED NOT NULL,
    bill_no        VARCHAR(128) NOT NULL DEFAULT '',
    billing_doc    VARCHAR(128) NOT NULL DEFAULT '',
    invoice_no     VARCHAR(128) NOT NULL DEFAULT '',
    sku_code       VARCHAR(128) NOT NULL,
    sku_name       VARCHAR(255) NOT NULL DEFAULT '',
    qty_uploaded   DECIMAL(14,3) NOT NULL DEFAULT 0,
    qty_approved   DECIMAL(14,3) NOT NULL DEFAULT 0,
    uploaded_date  DATE NULL,
    -- NULL until the distributor approves the GRN in the DMS (the report prints 0000-00-00)
    approved_date  DATE NULL,
    PRIMARY KEY (id),
    KEY idx_tat_grn_doc (company_id, billing_doc, sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=103)


register_table("tat_upload_log", """
CREATE TABLE IF NOT EXISTS tat_upload_log (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    company_id    INT NOT NULL,
    feed          VARCHAR(32)  NOT NULL,
    filename      VARCHAR(255) NOT NULL DEFAULT '',
    row_count     INT NOT NULL DEFAULT 0,
    uploaded_by   VARCHAR(100) NOT NULL DEFAULT '',
    uploaded_on   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_tat_upload_log_feed (company_id, feed, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
""", order=104)
