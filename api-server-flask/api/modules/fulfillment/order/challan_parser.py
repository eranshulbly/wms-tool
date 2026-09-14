# -*- encoding: utf-8 -*-
"""PDF parser for the "Order Challan" template (Anmol Associates / Ebco DMS).

Extraction only — nothing here touches the database or decides what an order means. That
separation is what lets the parser be tested against a corpus of real challans, and it
mirrors inventory.ingestion.parser, which does the same job for the INBOUND documents.

Two documents from the same issuer, pulling in opposite directions:

  * inventory.ingestion.parser  reads a GRN / credit note  -> stock coming IN
  * this parser                 reads an Order Challan     -> an order going OUT to a dealer

They are separate because the templates genuinely differ. The GRN packs every line item
into ONE table row (newline-separated per cell) and carries a diagonal watermark through
the table; the challan prints one row per item and no watermark. Sharing a parser would
mean one function branching on both, and a change for one document silently breaking the
other.

Columns are read by their HEADER LABEL, not by index. The labels here are clean and
stable ('Item No.', 'Quantity', 'Rate'), while the column INDICES are not: pdfplumber
reports 17 columns for an 11-column table because the template's cell borders create
empty spacer columns, and their number shifts with the widest row. Reading by label
survives that; reading by index does not.
"""

import re
from datetime import datetime

import pdfplumber

from api.core.logging import get_logger

logger = get_logger(__name__)


class ChallanParseError(Exception):
    """The PDF is not an Order Challan, or its template has changed."""


# What marks the document. Checked before anything else is read: a wrong template that
# parses "successfully" into the wrong columns is far worse than a refused file.
_DOC_MARKER = 'order challan'

# The line-item columns, by header label. `required` ones abort the parse when absent,
# because an order line without them cannot be turned into an order.
_COLUMNS = {
    'sr':        (('sr. no', 'sr no', 'sr.no'),          False),
    'item_code': (('item no.', 'item no', 'item code'),  True),
    'item_name': (('item name', 'description'),          True),
    'gst_rate':  (('gst rate', 'gst'),                   False),
    'stock':     (('available stock', 'stock'),          False),
    'quantity':  (('quantity', 'qty'),                   True),
    'uom':       (('uom', 'unit'),                       False),
    'rate':      (('rate',),                             False),
    'discount':  (('discount (%)', 'discount'),          False),
    'sd':        (('sd (%)', 'sd'),                      False),
    'amount':    (('amount',),                           False),
}


def _norm(s):
    return ' '.join(str(s or '').replace('\n', ' ').split()).strip().lower()


def _num(v, default=None):
    """A number out of '44,580.48', '18%', '450' or ''. None when there isn't one."""
    s = str(v or '').replace(',', '').replace('%', '').strip()
    if not s:
        return default
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    if not m:
        return default
    try:
        f = float(m.group(0))
    except ValueError:
        return default
    return int(f) if f.is_integer() else f


def _date(v):
    """The challan prints DD-MM-YYYY. Returned as a date, or None."""
    s = str(v or '').strip()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _labelled_value(table, label):
    """The value printed under a boxed caption, e.g. "Buyer's Order No" then "11956".

    The template puts caption and value in ONE cell, caption first. Searched across the
    whole table rather than at a fixed cell, because which column the box lands in moves
    with the spacer columns described in the module docstring.
    """
    want = _norm(label)
    for row in table:
        for cell in row:
            if not cell:
                continue
            lines = [l.strip() for l in str(cell).split('\n') if l.strip()]
            if lines and _norm(lines[0]) == want and len(lines) > 1:
                return lines[1]
    return None


def _party(table):
    """The buyer's block, which shares one cell with the seller's.

    Split on the 'Buyer (Bill to)' caption: everything before it is the issuer (us),
    everything after is the dealer. Keyed on the caption rather than on line offsets,
    because the seller block's height varies with how many of PAN / MSME are filled in.
    """
    for row in table:
        for cell in row:
            if cell and 'buyer (bill to)' in _norm(cell):
                lines = [l.strip() for l in str(cell).split('\n') if l.strip()]
                i = next(n for n, l in enumerate(lines) if 'buyer (bill to)' in _norm(l))
                after = lines[i + 1:]
                if not after:
                    return {}
                out = {'name': after[0], 'address': '', 'phone': '', 'gstin': ''}
                addr = []
                for l in after[1:]:
                    low = _norm(l)
                    if low.startswith('phone') or low.startswith('ph '):
                        out['phone'] = l.split(':', 1)[-1].strip()
                    elif low.startswith('gstin'):
                        out['gstin'] = l.split(':', 1)[-1].strip()
                    elif low.startswith('state name'):
                        pass
                    else:
                        addr.append(l)
                out['address'] = ', '.join(addr)
                return out
    return {}


def _header_row(table):
    """(row index, {field: column index}) for the line-item header."""
    for ri, row in enumerate(table):
        labels = {_norm(c): ci for ci, c in enumerate(row) if c and str(c).strip()}
        if not labels:
            continue
        found = {}
        for field, (aliases, _req) in _COLUMNS.items():
            for a in aliases:
                if a in labels:
                    found[field] = labels[a]
                    break
        # 'Item No.' AND 'Quantity' together identify the line table; either alone also
        # appears in the totals and HSN blocks.
        if 'item_code' in found and 'quantity' in found:
            missing = [f for f, (_a, req) in _COLUMNS.items() if req and f not in found]
            if missing:
                raise ChallanParseError(
                    'Order Challan line table is missing required column(s): '
                    + ', '.join(missing))
            return ri, found
    raise ChallanParseError(
        'No Order Challan line table found (expected headers "Item No." and "Quantity")')


def _hsn(table):
    """The HSN from the summary block.

    Every sample challan so far carries a single HSN, so it is applied to all lines. A
    future document with several would need per-line HSN; this returns the first, and the
    caller should stop trusting it for that case rather than silently mis-tagging goods.
    """
    for ri, row in enumerate(table):
        if any(c and _norm(c).startswith('hsn') for c in row):
            for later in table[ri + 1:]:
                for c in later:
                    s = str(c or '').strip()
                    if s.isdigit() and len(s) >= 4:
                        return s
            return None
    return None


def looks_like_challan(path):
    """True when this PDF is an Order Challan. Cheap: first page text only."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return False
            return _DOC_MARKER in _norm(pdf.pages[0].extract_text() or '')
    except Exception:
        return False


def parse_challan(path, filename=None):
    """Parse one Order Challan into a plain dict.

    Returns {doc_type, order_number, order_date, party:{...}, hsn, lines:[...]}, where each
    line carries item_code, item_name, quantity, uom, rate, gst_rate, discount_pct, sd_pct,
    amount, available_stock and hsn.
    """
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ChallanParseError('the PDF has no pages')
        page = pdf.pages[0]
        if _DOC_MARKER not in _norm(page.extract_text() or ''):
            raise ChallanParseError(
                'not an Order Challan (the words "Order Challan" do not appear)')
        tables = page.extract_tables()
        if not tables:
            raise ChallanParseError('no table found on the first page')
        table = max(tables, key=len)

    order_number = _labelled_value(table, "Buyer's Order No")
    if not order_number:
        raise ChallanParseError(
            "Buyer's Order No is missing - the order has nothing to be keyed on")
    order_date = _date(_labelled_value(table, "Buyer's Order Date"))
    party = _party(table)
    hsn = _hsn(table)

    hdr_i, cols = _header_row(table)

    def cell(row, field):
        ci = cols.get(field)
        return row[ci] if ci is not None and ci < len(row) else None

    lines = []
    for row in table[hdr_i + 1:]:
        code = str(cell(row, 'item_code') or '').strip()
        qty = _num(cell(row, 'quantity'))
        # The totals row repeats a quantity with no item code; the words and HSN blocks
        # have neither. Requiring both ends the line table without having to recognise
        # the footer, which differs between documents.
        if not code or qty is None:
            continue
        lines.append({
            'item_code': code,
            'item_name': str(cell(row, 'item_name') or '').strip(),
            'quantity': qty,
            'uom': str(cell(row, 'uom') or '').strip() or None,
            'rate': _num(cell(row, 'rate')),
            'gst_rate': _num(cell(row, 'gst_rate')),
            'discount_pct': _num(cell(row, 'discount'), 0),
            'sd_pct': _num(cell(row, 'sd'), 0),
            'amount': _num(cell(row, 'amount')),
            'available_stock': _num(cell(row, 'stock')),
            'hsn': hsn,
        })

    if not lines:
        raise ChallanParseError('the challan has no readable line items')

    doc = {
        'doc_type': 'order_challan',
        'source_file': filename,
        'order_number': str(order_number).strip(),
        'order_date': order_date,
        'party': party,
        'hsn': hsn,
        'lines': lines,
    }
    logger.info('Order Challan parsed', extra={
        'order_number': doc['order_number'], 'lines': len(lines),
        'party': party.get('name'), 'source_file': filename})
    return doc
