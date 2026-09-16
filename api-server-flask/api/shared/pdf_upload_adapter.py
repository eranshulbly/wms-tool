# -*- encoding: utf-8 -*-
"""Turn a supplier PDF into the DataFrame the spreadsheet uploads already expect.

The order, product and invoice uploads were built around Excel/CSV files whose columns
the operator controls. Cadila's paperwork arrives as PDFs on a fixed template instead, so
rather than teaching each upload a second input format, this adapter renders one PDF into
the same column shape those uploads already read. Every downstream rule — order matching,
state transitions, product creation — stays exactly as it is.

The grain depends on which upload is being fed — see `pdf_to_dataframe`. The order upload
gets one row for the document; the products and invoice uploads get one row per line.

Columns are a superset covering all three uploads, so the SAME file can be sent to each:

  order upload     Sales Order #, Order ID, Order Type, Purchaser Name,
                   Purchaser SAP Code, Shipping Address, Submit Date, B2B PO#,
                   Created By, Invoice # / VIN #, Number of Boxes
  products upload  Order #, Part #, Part Description, Reserved Qty
  invoice upload   Invoice #, Order #, Account Name, Cash Customer Name, Code

plus Batch #, Expiry, MRP, Rate and Amount, which the spreadsheet feeds never carried.
"""

import os

import pandas as pd

from api.core.logging import get_logger
from api.modules.inventory.ingestion import parser
from api.shared.db_manager import mysql_manager

logger = get_logger(__name__)


def derive_order_number(doc):
    """The order number for a document that may not print one.

    This supplier leaves 'Order No.' blank on its invoices, but every downstream upload
    keys on an order number — the invoice upload looks one up, the products upload
    attaches lines to it. Deriving it from the invoice number keeps that chain intact and
    makes the same file reproduce the same order number on every upload, which is what
    lets order, product and invoice uploads of one PDF agree with each other.
    """
    printed = (doc.get('order_number') or '').strip()
    return printed or f"O_{doc['doc_number']}"


def _company_prefix(company_id):
    """Short prefix for generated product codes, taken from the company name."""
    if not company_id:
        return 'PROD'
    rows = mysql_manager.execute_query(
        "SELECT name FROM company WHERE company_id = %s", (company_id,))
    name = rows[0]['name'] if rows else ''
    from api.modules.inventory.ingestion.service import _slug
    return _slug(name, 4) or 'PROD'


def _part_number(cursor_free_company_id, prefix, line):
    """The `product_string` this line should resolve to.

    The products upload matches on product_string, and the PDF ingestion flow generates
    codes as <PREFIX>-<name>-<pack>. Reusing that construction means both routes land on
    ONE product row; inventing a different code here would create a duplicate product for
    the same item, splitting its stock.

    An existing product for the same company and printed name wins outright, so a product
    already created by ingestion is reused even if its code was disambiguated.
    """
    from api.modules.inventory.ingestion.service import _slug
    name = (line['raw_product_name'] or '').strip()

    rows = mysql_manager.execute_query(
        "SELECT product_string FROM product WHERE company_id = %s AND name = %s LIMIT 1",
        (cursor_free_company_id, name)) if cursor_free_company_id else None
    if rows and rows[0]['product_string']:
        return rows[0]['product_string']

    pack = line.get('raw_pack') or ''
    return (f"{prefix}-{_slug(name)}" + (f"-{_slug(pack, 12)}" if pack else ''))[:90]


def pdf_to_dataframe(path, company_id=None, upload_type=None):
    """Parse one PDF and return it as an upload-shaped DataFrame.

    `upload_type` sets the GRAIN, because the uploads disagree about what a row means.
    The order upload treats one row as one order — a spreadsheet of orders has a row per
    order — so feeding it a row per line item would create one order per line. The
    products upload needs the opposite: a row per line. The invoice upload keys on the
    order and is indifferent.

    So 'orders' and 'invoices' collapse to a single header row; the products upload keeps
    one row per line.
    """
    doc = parser.parse_pdf(path, os.path.basename(path))

    # Only a sale belongs in the order and invoice uploads. The same parser reads goods
    # receipts and credit/debit notes; accepting one here would open or close an order for
    # stock that is arriving rather than leaving. Those go through Inventory Ingestion.
    if upload_type in ('orders', 'invoices') and doc['doc_type'] not in parser.OUTBOUND_TYPES:
        raise parser.ParseError(
            f"this is a {doc.get('doc_title') or doc['doc_type']}, not a sales invoice — "
            f"upload it in Inventory Ingestion")
    order_no = derive_order_number(doc)
    prefix = _company_prefix(company_id)
    party = doc.get('party_name') or ''

    rows = []
    for line in doc['lines']:
        rows.append({
            # ── identity, repeated on every line ──────────────────────────────
            'Invoice #': doc['doc_number'],
            'Invoice # / VIN #': doc['doc_number'],
            'Order #': order_no,
            'Sales Order #': order_no,
            'Order ID': order_no,
            'Order Type': doc['doc_type'],
            'Submit Date': doc['doc_date'],
            'Order Date': doc['doc_date'],
            # Read by the invoice upload. Without them the invoice is stored with no value
            # and no date, and every sales figure built on invoices reads zero.
            'Invoice Date': doc['doc_date'],
            'Invoice Amount': doc.get('grand_total'),
            'Invoice Type': doc['doc_type'],
            'Number of Boxes': doc.get('cases') or 0,
            'B2B PO#': '',
            'Created By': '',
            'Shipping Address': '',

            # ── counterparty ─────────────────────────────────────────────────
            'Purchaser Name': party,
            'Account Name': party,
            'Cash Customer Name': party,
            'Purchaser SAP Code': doc.get('party_gstin') or '',
            'Code': doc.get('party_gstin') or '',

            # ── the line itself ──────────────────────────────────────────────
            'Part #': _part_number(company_id, prefix, line),
            'Part Description': line['raw_product_name'],
            'Reserved Qty': line['quantity'],
            'Batch #': line['raw_batch'],
            'Expiry': line['expiry_date'],
            'MRP': line['mrp'],
            'Rate': line['rate'],
            'Amount': line['amount'],
        })

    # The invoice upload treats one row as one document, so a row per line item would
    # create an invoice per line — `invoice` has no unique key on invoice_number, so its
    # INSERT IGNORE will not catch the duplicates for you.
    #
    # Orders keep every line. The order upload creates ONE order from the first row
    # carrying a given order number and reads the rest as its line items (see
    # order/business.py), so truncating here is what left a PDF-sourced order with a
    # header and nothing in it.
    if upload_type == 'invoices' and rows:
        rows = rows[:1]

    logger.info("PDF rendered to upload rows",
                extra={'doc_type': doc['doc_type'], 'doc_number': doc['doc_number'],
                       'order_number': order_no, 'upload_type': upload_type,
                       'lines': len(rows)})
    return pd.DataFrame(rows)
