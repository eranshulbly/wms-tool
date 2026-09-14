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
import pdfplumber

from api.core.logging import get_logger
from api.modules.inventory.ingestion import parser
from api.shared.db_manager import mysql_manager

logger = get_logger(__name__)


def _has_text_layer(path, pages_to_check=3):
    """True when this PDF carries text that can actually be read out of it.

    A PDF printed from a browser carries its text as characters; one that was scanned, or
    saved with its fonts flattened to outlines, carries only the SHAPES of those letters.
    The two look identical on screen and are completely different to parse — the flattened
    kind reports zero glyphs and zero images, while still drawing perfectly legible words
    out of vector paths.

    This matters because every detector below works by looking for words — "Order Challan",
    "Tax Invoice". Given a picture, they all see an empty string, all decline, and the
    document falls through to the last parser in the chain, which then fails on whatever it
    happens to check first. The operator is told the line-item header row is missing, which
    is true of an empty string and utterly misleading about the real problem.

    Errs towards True: if the file cannot be opened at all, the real parser should raise
    the real error rather than have this guess at one.
    """
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:pages_to_check]:
                if (page.extract_text() or '').strip():
                    return True
            return False
    except Exception:
        return True


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


def _challan_to_rows(path, filename=None):
    """An Order Challan as upload rows — one per line item.

    A different document from the GRN below: it is an order going OUT to a dealer, not
    stock coming in, and it prints a real order number, a real part number and a real
    dealer. So none of the derivation the GRN needs applies here — no order number is
    invented, and no product code is generated, because the document already carries both.
    """
    from api.modules.fulfillment.order import challan_parser

    doc = challan_parser.parse_challan(path, filename)
    party = doc.get('party') or {}
    rows = []
    for line in doc['lines']:
        rows.append({
            # ── the order, repeated on every line ─────────────────────────────
            'Sales Order #': doc['order_number'],
            'Order #': doc['order_number'],
            'Order ID': doc['order_number'],
            'Order Type': 'Order Challan',
            'Order Date': doc['order_date'],
            'Submit Date': doc['order_date'],
            'B2B PO#': '',
            'Created By': '',
            'Number of Boxes': 0,
            'Invoice # / VIN #': '',

            # ── the dealer ────────────────────────────────────────────────────
            'Purchaser Name': party.get('name') or '',
            'Account Name': party.get('name') or '',
            # The challan identifies the buyer by GSTIN, which is the only stable code it
            # prints — there is no SAP code on this template.
            'Purchaser SAP Code': party.get('gstin') or '',
            'Shipping Address': party.get('address') or '',

            # ── the line ──────────────────────────────────────────────────────
            'Part #': line['item_code'],
            'Part Description': line['item_name'],
            'Reserved Qty': line['quantity'],
            'Order Quantity': line['quantity'],
            # The rate is the GROSS quoted price; the two percentages below cut it down to
            # what is actually charged, and 'Amount' is the printed line total after both.
            # All four travel together because the rate alone is not what the dealer pays —
            # on this challan 428.00 becomes 222.90 once 44% and 7% come off it. They are
            # per-dealer terms, which is why they belong to the order line and never to the
            # product.
            'Rate': line['rate'],
            'Discount %': line['discount_pct'],
            'SD %': line['sd_pct'],
            'Amount': line['amount'],
            # Catalogue detail the spreadsheet feeds never carried. product_sync writes
            # these onto the product; the order itself ignores them.
            'UOM': line['uom'] or '',
            'GST %': line['gst_rate'],
            'HSN Code': line['hsn'] or '',
            'Available Stock': line['available_stock'],
        })
    return rows


def _tax_invoice_to_rows(path, filename=None):
    """A Tax Invoice as upload rows — one per line item.

    The invoice RECORD is header-level (one row is one invoice), but the line items have
    to travel too: they are what tells the stock ledger which parts left the building.
    The invoice service takes the header off the first row and uses the rest for stock.

    'Order #' is the invoice's printed `Buyers Order No.`, which is the same number the
    challan printed and the order is keyed on. Nothing is derived or guessed — both
    documents carry it.
    """
    from api.modules.fulfillment.invoice import tax_invoice_parser

    doc = tax_invoice_parser.parse_tax_invoice(path, filename)
    party = doc.get('party') or {}
    totals = doc.get('totals') or {}
    rows = []
    for line in doc['lines']:
        rows.append({
            # ── marks the grain, so the service knows the header is on row 0 only ──
            'Source Doc': 'tax_invoice',

            # ── the invoice ───────────────────────────────────────────────────
            'Invoice #': doc['invoice_number'],
            'Invoice # / VIN #': doc['invoice_number'],
            'Invoice Date': doc['invoice_date'],
            'Invoice Type': 'Tax Invoice',
            'Invoice Amount': totals.get('grand_total'),
            'Round Off Amount': totals.get('round_off'),
            'Invoice Round Off Amount': totals.get('round_off'),

            # ── the order it settles ──────────────────────────────────────────
            'Order #': doc['order_number'],
            'Sales Order #': doc['order_number'],
            'Order Date': doc['order_date'],

            # ── the buyer ─────────────────────────────────────────────────────
            'Account Name': party.get('name') or '',
            'Cash Customer Name': party.get('name') or '',
            'Purchaser Name': party.get('name') or '',
            # GSTIN is the only stable buyer code this template prints.
            'Account TIN#': party.get('gstin') or '',
            'Code': party.get('gstin') or '',
            'Purchaser SAP Code': party.get('gstin') or '',
            'Shipping Address': party.get('address') or '',

            # ── the line ──────────────────────────────────────────────────────
            'Part #': line['item_code'],
            'Part Description': line['item_name'],
            'Reserved Qty': line['quantity'],
            'Order Quantity': line['quantity'],
            'Rate': line['rate'],
            'Discount %': line['discount_pct'],
            'SD %': line['sd_pct'],
            'Amount': line['amount'],
            'UOM': line['uom'] or '',
            'GST %': line['gst_rate'],
            'HSN Code': line['hsn'] or '',
        })
    return rows


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
    # Two document families arrive as PDFs from the same issuer. The challan is detected
    # first and by its own marker, so a template change on one cannot silently route a
    # document into the other's parser and mis-read its columns.
    # Checked before any detector runs. Every one of them works by looking for words, so a
    # PDF that contains none makes all of them decline and the document falls through to
    # the last parser in the chain — which reports whatever it checks first, and sends the
    # operator looking for a missing header row in a file that has no text at all.
    if not _has_text_layer(path):
        logger.warning("PDF has no text layer", extra={'upload_type': upload_type,
                                                       'file': os.path.basename(path)})
        raise parser.ParseError(
            'this PDF has no selectable text. Its words were saved as pictures — either '
            'scanned, or printed in a way that turned the letters into shapes — so there '
            'is nothing in the file to read, however clear it looks on screen. Open the '
            'document in the DMS and use Print → Save as PDF; if you can select the text '
            'with the mouse in the saved copy, it will upload.')

    from api.modules.fulfillment.invoice import tax_invoice_parser
    if tax_invoice_parser.looks_like_tax_invoice(path):
        rows = _tax_invoice_to_rows(path, os.path.basename(path))
        logger.info("Tax Invoice rendered to upload rows",
                    extra={'upload_type': upload_type, 'lines': len(rows),
                           'invoice_number': rows[0]['Invoice #'] if rows else None,
                           'order_number': rows[0]['Order #'] if rows else None})
        return pd.DataFrame(rows)

    from api.modules.fulfillment.order import challan_parser
    if challan_parser.looks_like_challan(path):
        rows = _challan_to_rows(path, os.path.basename(path))
        logger.info("Order Challan rendered to upload rows",
                    extra={'upload_type': upload_type, 'lines': len(rows),
                           'order_number': rows[0]['Sales Order #'] if rows else None})
        # Deliberately NOT collapsed to one row for the orders upload, unlike the GRN
        # below: the order upload now creates the line items too, and it de-duplicates
        # the order itself in-file. Collapsing here would throw the lines away.
        return pd.DataFrame(rows)

    doc = parser.parse_pdf(path, os.path.basename(path))
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

    # Only the products upload works line by line. The order and invoice uploads each
    # treat one row as one document, so feeding them a row per line item creates an order
    # (or an invoice) per line — `invoice` has no unique key on invoice_number, so its
    # INSERT IGNORE will not catch the duplicates for you.
    if upload_type in ('orders', 'invoices') and rows:
        rows = rows[:1]

    logger.info("PDF rendered to upload rows",
                extra={'doc_type': doc['doc_type'], 'doc_number': doc['doc_number'],
                       'order_number': order_no, 'upload_type': upload_type,
                       'lines': len(rows)})
    return pd.DataFrame(rows)
