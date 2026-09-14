# -*- encoding: utf-8 -*-
"""PDF parser for the "Tax Invoice" template (Ebco DMS / bizom).

The third document this supplier issues, and the last step of the chain:

  * inventory.ingestion.parser   GRN / credit note   -> stock coming IN
  * order.challan_parser         Order Challan       -> an order going OUT
  * this parser                  Tax Invoice         -> that order, billed

Separate from the challan parser because the templates label their fields differently and
share no table geometry. The challan prints a caption in one line of a cell and its value
in the next; this invoice prints "Caption:value" on a single line. One parser branching on
both would be a change to either document breaking the other.

WHAT TIES AN INVOICE TO ITS ORDER
---------------------------------
`Buyers Order No.` — printed in the invoice header, and the same number the challan prints
as `Buyer's Order No`, which is what the order is keyed on (potential_order.original_order_id).
So the two documents join on a value both of them print, with nothing inferred: invoice
26-27-EB-INV-2 carries "Buyers Order No.:11956" and order 11956 is the one it bills.

The invoice number itself is NOT that link. It belongs to the seller's own billing
sequence and says nothing about which order it settles.
"""

import re
from datetime import datetime

import pdfplumber

from api.core.logging import get_logger

logger = get_logger(__name__)


class TaxInvoiceParseError(Exception):
    """The PDF is not a Tax Invoice of this template, or the template has changed."""


# Checked before anything is read. A wrong template that parses "successfully" into the
# wrong columns would bill the wrong order and reduce stock for parts nobody sold.
_DOC_MARKER = 'tax invoice'

# Header fields, by their printed caption. The value follows the colon on the SAME line.
_HEADER_FIELDS = {
    'invoice_number':   ('invoice no.', 'invoice no'),
    'order_number':     ('buyers order no.', 'buyers order no', "buyer's order no."),
    'invoice_date':     ('invoice date',),
    'order_date':       ('buyers order date', "buyer's order date"),
    'payment_mode':     ('payment mode',),
    'reference_number': ('reference no.', 'reference no'),
}

# The line-item columns, by header label. Only the first three are load-bearing: without a
# part and a quantity there is nothing to bill or to take out of stock.
_COLUMNS = {
    'sr':        (('sr no.', 'sr no'),                    False),
    'item_code': (('item code.', 'item code', 'item no.'), True),
    'item_name': (('item name', 'description'),           False),
    'hsn':       (('hsn/sac', 'hsn', 'hsn no.'),          False),
    'gst_rate':  (('gst rate', 'gst'),                    False),
    'quantity':  (('quantity', 'qty'),                    True),
    'uom':       (('uom', 'unit'),                        False),
    'rate':      (('rate',),                              False),
    'discount':  (('discount (%)', 'discount(%)', 'discount'), False),
    'sd':        (('sd (%)', 'sd(%)', 'sd'),              False),
    'amount':    (('amount',),                            False),
}

# Totals printed as their own rows beneath the line items, captioned in one cell with the
# figure in the last. Read by caption because their row positions move with the number of
# line items above them.
_TOTAL_ROWS = {
    'cash_discount':      ('cash discount',),
    'total_after_cd':     ('total after cash discount applied',),
    'freight_charges':    ('freight charges',),
    'cgst':               ('cgst',),
    'sgst':               ('sgst',),
    'igst':               ('igst',),
    'round_off':          ('round off',),
    'grand_total':        ('grand total',),
}


# Captions that appear in the Item Code column BELOW the last line item. The line table
# has no footer marker, so the totals block is what ends it — and the first of these rows
# ("Total") otherwise parses as a perfectly plausible line item, with a quantity and an
# amount, for a part called "Total".
_END_OF_LINES = (
    'total', 'cash discount', 'total after cash discount applied', 'freight charges',
    'cgst', 'sgst', 'igst', 'round off', 'grand total', 'credit adjustment amount (-)',
    'credit adjustment amount',
)


def _norm(value):
    return ' '.join(str(value or '').replace('\n', ' ').split()).strip().lower()


def _num(value, default=None):
    """A number out of '44,580.48', '18%', '52,605' or ''. None when there isn't one."""
    text = str(value or '').replace(',', '').replace('%', '').strip()
    if not text:
        return default
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return default
    try:
        val = float(match.group(0))
    except ValueError:
        return default
    return int(val) if val.is_integer() else val


def _date(value):
    """This template prints DD-MM-YYYY. Returned as a date, or None."""
    text = str(value or '').strip()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _header_values(tables):
    """Every 'Caption:value' printed anywhere in the document, normalised caption -> value.

    Scanned across all cells rather than read at fixed positions: this template packs
    several captions into one cell and which cell that is moves with the length of the
    seller's address block.
    """
    found = {}
    for table in tables:
        for row in table:
            for cell in row:
                if not cell:
                    continue
                for line in str(cell).split('\n'):
                    if ':' not in line:
                        continue
                    caption, _, value = line.partition(':')
                    caption = _norm(caption)
                    if caption and caption not in found:
                        found[caption] = value.strip()
    return found


def _party(tables):
    """The BUYER's block, read from inside the 'Bill To' cell.

    Not from the document-wide caption scan: the seller's block prints GSTIN/UIN, State
    and Code with exactly the same captions, and appears FIRST, so a whole-document scan
    returns the issuer's GSTIN for the buyer — quietly filing every invoice against the
    wrong party's tax number.
    """
    for table in tables:
        for row in table:
            for cell in row:
                if not cell or 'bill to' not in _norm(cell):
                    continue
                out = {'name': '', 'address': '', 'gstin': '', 'phone': '', 'state': ''}
                address = []
                for line in str(cell).split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    caption, sep, value = line.partition(':')
                    key, value = _norm(caption), value.strip()
                    if not sep:
                        address.append(line)          # a bare address line
                    elif key == 'bill to':
                        out['name'] = value
                    elif key == 'gstin/uin':
                        out['gstin'] = value
                    elif key == 'customer number':
                        out['phone'] = value
                    elif key == 'state':
                        out['state'] = value
                    elif key in ('customer name', 'code', 'ship to'):
                        pass
                    else:
                        address.append(line)
                out['address'] = ', '.join(address)
                return out
    return {}


def _pick(header, aliases):
    for alias in aliases:
        if alias in header and header[alias]:
            return header[alias]
    return None


def _line_header(table):
    """(row index, {field: column index}) for the line-item header row."""
    for ri, row in enumerate(table):
        labels = {}
        for ci, cell in enumerate(row):
            key = _norm(cell)
            if key and key not in labels:
                labels[key] = ci
        if not labels:
            continue
        found = {}
        for field, (aliases, _req) in _COLUMNS.items():
            for alias in aliases:
                if alias in labels:
                    found[field] = labels[alias]
                    break
        # Both together identify the line table. 'Quantity' alone also appears on the
        # Total row, and 'Amount' alone on every tax row beneath it.
        if 'item_code' in found and 'quantity' in found:
            missing = [f for f, (_a, req) in _COLUMNS.items() if req and f not in found]
            if missing:
                raise TaxInvoiceParseError(
                    'Tax Invoice line table is missing required column(s): '
                    + ', '.join(missing))
            return ri, found
    raise TaxInvoiceParseError(
        'no Tax Invoice line table found (expected headers "Item Code." and "Quantity")')


def _totals(tables):
    """The captioned total rows, as {name: number}."""
    out = {}
    for table in tables:
        for row in table:
            caption = None
            for cell in row:
                text = _norm(cell)
                if text:
                    caption = text
                    break
            if not caption:
                continue
            for name, aliases in _TOTAL_ROWS.items():
                if name in out:
                    continue
                if caption in aliases:
                    # The figure is the last non-empty cell on the row.
                    for cell in reversed(row):
                        if cell and str(cell).strip():
                            value = _num(cell)
                            if value is not None:
                                out[name] = value
                            break
    return out


def looks_like_tax_invoice(path):
    """True when this PDF is a Tax Invoice of this template. First-page text only."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return False
            text = _norm(pdf.pages[0].extract_text() or '')
            # 'Buyers Order No' is required as well as the title: it is what makes the
            # document usable here, and a tax invoice without it cannot be matched to an
            # order however well it parses.
            return _DOC_MARKER in text and 'buyers order no' in text
    except Exception:
        return False


def parse_tax_invoice(path, filename=None):
    """Parse one Tax Invoice into a plain dict.

    Returns {invoice_number, order_number, invoice_date, order_date, party, totals, lines},
    where each line carries item_code, item_name, hsn, gst_rate, quantity, uom, rate,
    discount_pct, sd_pct and amount.
    """
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise TaxInvoiceParseError('the PDF has no pages')
        first_text = _norm(pdf.pages[0].extract_text() or '')
        if _DOC_MARKER not in first_text:
            raise TaxInvoiceParseError(
                'not a Tax Invoice (the words "Tax Invoice" do not appear)')
        # Totals continue onto page 2 (Round Off, Grand Total), so every page is read.
        tables = []
        for page in pdf.pages:
            tables.extend(page.extract_tables() or [])

    if not tables:
        raise TaxInvoiceParseError('no table found in the document')

    header = _header_values(tables)
    invoice_number = _pick(header, _HEADER_FIELDS['invoice_number'])
    order_number = _pick(header, _HEADER_FIELDS['order_number'])

    if not invoice_number:
        raise TaxInvoiceParseError('Invoice No. is missing')
    if not order_number:
        raise TaxInvoiceParseError(
            "Buyers Order No. is missing - there is nothing to match this invoice to an "
            "order with")

    # The line table is found by its HEADER, not by being the biggest. The HSN summary on
    # page 2 has more rows than the line table on page 1, so picking the longest table
    # selected the summary and then failed looking for "Item Code." in it.
    line_table = cols = hdr_i = None
    for table in tables:
        try:
            hdr_i, cols = _line_header(table)
            line_table = table
            break
        except TaxInvoiceParseError:
            continue
    if line_table is None:
        raise TaxInvoiceParseError(
            'no Tax Invoice line table found (expected headers "Item Code." and "Quantity")')

    def cell(row, field):
        ci = cols.get(field)
        return row[ci] if ci is not None and ci < len(row) else None

    lines = []
    for row in line_table[hdr_i + 1:]:
        code = str(cell(row, 'item_code') or '').strip()
        qty = _num(cell(row, 'quantity'))
        # The totals block sits in the same column as the item codes, and its first row
        # ("Total") carries a quantity and an amount too — so it reads as a line item for
        # a part called "Total" unless it is recognised. It also marks the end of the
        # goods, so nothing below it can be a line either.
        if _norm(code) in _END_OF_LINES:
            break
        if not code or qty is None:
            continue
        lines.append({
            'item_code': code,
            'item_name': str(cell(row, 'item_name') or '').strip(),
            'hsn': str(cell(row, 'hsn') or '').strip() or None,
            'gst_rate': _num(cell(row, 'gst_rate')),
            'quantity': qty,
            'uom': str(cell(row, 'uom') or '').strip() or None,
            'rate': _num(cell(row, 'rate')),
            'discount_pct': _num(cell(row, 'discount'), 0),
            'sd_pct': _num(cell(row, 'sd'), 0),
            'amount': _num(cell(row, 'amount')),
        })

    if not lines:
        raise TaxInvoiceParseError('the invoice has no readable line items')

    doc = {
        'doc_type': 'tax_invoice',
        'source_file': filename,
        'invoice_number': str(invoice_number).strip(),
        'order_number': str(order_number).strip(),
        'invoice_date': _date(_pick(header, _HEADER_FIELDS['invoice_date'])),
        'order_date': _date(_pick(header, _HEADER_FIELDS['order_date'])),
        'payment_mode': _pick(header, _HEADER_FIELDS['payment_mode']) or '',
        'reference_number': _pick(header, _HEADER_FIELDS['reference_number']) or '',
        'party': _party(tables),
        # The issuer's own GSTIN, kept apart from the buyer's so the two can never be
        # confused by a later reader.
        'seller_gstin': (header.get('gstin/uin') or '').strip(),
        'totals': _totals(tables),
        'lines': lines,
    }
    logger.info('Tax Invoice parsed', extra={
        'invoice_number': doc['invoice_number'], 'order_number': doc['order_number'],
        'lines': len(lines), 'source_file': filename})
    return doc
