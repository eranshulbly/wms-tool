# -*- encoding: utf-8 -*-
"""Parsers for the three TAT Check uploads. Pure functions — no database.

  inventory         DMS Inventory Report (.csv/.xlsx)          -> inventory rows
  dispatch_pending  supplier workbook, sheets DISPATCH+PENDING -> dispatch rows, pending rows
  grn               DMS GRN Approved Status Report SKU-wise    -> grn rows

Every feed replaces what is stored, so a file is checked against the slot it was
uploaded into BEFORE anything is parsed: an inventory file dropped into the GRN slot
would otherwise wipe the GRNs and mark every dispatch as still in transit.
"""

import csv
import io
from datetime import date, datetime


class ParseError(Exception):
    pass


FEED_INVENTORY = 'inventory'
FEED_DISPATCH_PENDING = 'dispatch_pending'
FEED_GRN = 'grn'

FEED_LABELS = {
    FEED_INVENTORY: 'Inventory Report',
    FEED_DISPATCH_PENDING: 'Dispatch & Pending workbook',
    FEED_GRN: 'GRN Approved Status Report',
}

# Only the columns read here are required, so an export that gains a column still loads.
INVENTORY_COLS = ['Sku_Code', 'Sku_Name', 'Units']
GRN_COLS = ['Bill_No', 'Invoice_No', 'Sku_code', 'Sku', 'primary_stock_quantity_Uploaded',
            'primary_stock_quantity_Approved', 'Uploaded_Date', 'Approved_Date']
# The DISPATCH sheet repeats 'Bill-to Party' and 'Product' (code, then name); read_rows
# names the second occurrence '<name> #2'.
DISPATCH_COLS = ['Profit Center', 'Billing Date', 'Billing Document', 'Product',
                 'Product #2', 'Doc. Reference ID', 'Sales Volume Qty']
PENDING_COLS = ['Plant Name', 'Order date', 'PO Number', 'Sales Document',
                'Sales Document Item', 'Product', 'Product Description', 'Order Quantity',
                'Delivered Quantity', 'Open Dlv Quantity']


# ── low-level helpers ────────────────────────────────────────────────────────

def _s(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _num(v):
    s = _s(v).replace(',', '')
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _s(v)
    if not s or s.startswith('0000'):
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _dedupe(header):
    """'Product', 'Product' -> 'Product', 'Product #2' — so a repeated column does not
    silently overwrite the first one in a dict row."""
    seen, out = {}, []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        out.append(h if seen[h] == 1 else f'{h} #{seen[h]}')
    return out


def _sheet_rows(ws):
    it = ws.iter_rows(values_only=True)
    header = _dedupe([_s(h) for h in next(it, [])])
    rows = [dict(zip(header, r)) for r in it if any(c not in (None, '') for c in r)]
    return header, rows


def _workbook(data):
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(data), read_only=True, data_only=True)


def _table(data, filename):
    """Header and rows of a single-table export (.csv, or the first sheet of an .xlsx)."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        return _sheet_rows(_workbook(data).worksheets[0])
    if name.endswith('.csv') or not name:
        text = data.decode('utf-8-sig', errors='replace')
        reader = csv.reader(io.StringIO(text))
        header = _dedupe([h.strip() for h in next(reader, [])])
        rows = [dict(zip(header, r)) for r in reader if any(c.strip() for c in r)]
        return header, rows
    raise ParseError('Upload the report as .csv or .xlsx.')


def _require(header, cols, label, where=''):
    missing = [c for c in cols if c not in header]
    if missing:
        raise ParseError(f'Not a {label}{where} — missing column(s): {", ".join(missing)}. '
                         'Nothing was changed.')


# ── per-feed parsers ─────────────────────────────────────────────────────────

def parse_inventory(data, filename):
    """Current stock only: SKU code, name, and Units (saleable pieces)."""
    header, rows = _table(data, filename)
    if all(c in header for c in GRN_COLS):
        raise ParseError('This file looks like the GRN Approved Status Report, not the '
                         'Inventory Report. Nothing was changed.')
    _require(header, INVENTORY_COLS, FEED_LABELS[FEED_INVENTORY])
    stock, names, warnings = {}, {}, []
    for i, r in enumerate(rows, start=2):
        code = _s(r.get('Sku_Code'))
        if not code:
            warnings.append(f'Row {i}: no Sku_Code — skipped')
            continue
        if code in stock:
            warnings.append(f'Row {i}: {code} appears more than once — stock summed')
        stock[code] = stock.get(code, 0.0) + _num(r.get('Units'))
        names.setdefault(code, _s(r.get('Sku_Name')))
    out = [{'sku_code': c, 'sku_name': names[c], 'stock_qty': q} for c, q in stock.items()]
    return {'inventory': out}, warnings


def parse_dispatch_pending(data, filename):
    if not (filename or '').lower().endswith(('.xlsx', '.xlsm')):
        raise ParseError('Upload the Dispatch & Pending workbook as .xlsx (it has a DISPATCH '
                         'and a PENDING sheet). Nothing was changed.')
    wb = _workbook(data)
    sheets = {ws.title.strip().upper(): ws for ws in wb.worksheets}
    missing = [s for s in ('DISPATCH', 'PENDING') if s not in sheets]
    if missing:
        raise ParseError(f'The workbook has no {" or ".join(missing)} sheet '
                         f'(found: {", ".join(ws.title for ws in wb.worksheets)}). '
                         'Nothing was changed.')
    label = FEED_LABELS[FEED_DISPATCH_PENDING]
    d_header, d_rows = _sheet_rows(sheets['DISPATCH'])
    _require(d_header, DISPATCH_COLS, label, ' (DISPATCH sheet)')
    p_header, p_rows = _sheet_rows(sheets['PENDING'])
    _require(p_header, PENDING_COLS, label, ' (PENDING sheet)')

    warnings, dispatch, pending = [], [], []
    for i, r in enumerate(d_rows, start=2):
        doc, code = _s(r.get('Billing Document')), _s(r.get('Product'))
        if not doc or not code:
            warnings.append(f'DISPATCH row {i}: no Billing Document or Product — skipped')
            continue
        dispatch.append({
            'plant': _s(r.get('Profit Center')),
            'billing_date': _date(r.get('Billing Date')),
            'billing_doc': doc,
            'doc_ref_id': _s(r.get('Doc. Reference ID')),
            'sku_code': code,
            'sku_name': _s(r.get('Product #2')),
            'qty': _num(r.get('Sales Volume Qty')),
        })
    for i, r in enumerate(p_rows, start=2):
        code = _s(r.get('Product'))
        if not code:
            warnings.append(f'PENDING row {i}: no Product — skipped')
            continue
        open_qty = _num(r.get('Open Dlv Quantity'))
        if open_qty <= 0:
            continue
        pending.append({
            'plant': _s(r.get('Plant Name')),
            'order_date': _date(r.get('Order date')),
            'po_number': _s(r.get('PO Number')),
            'sales_doc': _s(r.get('Sales Document')),
            'sales_doc_item': _s(r.get('Sales Document Item')),
            'sku_code': code,
            'sku_name': _s(r.get('Product Description')),
            'order_qty': _num(r.get('Order Quantity')),
            'delivered_qty': _num(r.get('Delivered Quantity')),
            'open_qty': open_qty,
        })
    if not dispatch and not pending:
        raise ParseError('Both the DISPATCH and PENDING sheets are empty. Nothing was changed.')
    return {'dispatch': dispatch, 'pending': pending}, warnings


def parse_grn(data, filename):
    header, rows = _table(data, filename)
    if all(c in header for c in INVENTORY_COLS):
        raise ParseError('This file looks like the Inventory Report, not the GRN Approved '
                         'Status Report. Nothing was changed.')
    _require(header, GRN_COLS, FEED_LABELS[FEED_GRN])
    out, warnings = [], []
    for i, r in enumerate(rows, start=2):
        bill_no, code = _s(r.get('Bill_No')), _s(r.get('Sku_code'))
        if not bill_no or not code:
            warnings.append(f'Row {i}: no Bill_No or Sku_code — skipped')
            continue
        out.append({
            'bill_no': bill_no,
            'billing_doc': billing_doc_of(bill_no),
            'invoice_no': _s(r.get('Invoice_No')),
            'sku_code': code,
            'sku_name': _s(r.get('Sku')),
            'qty_uploaded': _num(r.get('primary_stock_quantity_Uploaded')),
            'qty_approved': _num(r.get('primary_stock_quantity_Approved')),
            'uploaded_date': _date(r.get('Uploaded_Date')),
            'approved_date': _date(r.get('Approved_Date')),
        })
    return {'grn': out}, warnings


def billing_doc_of(bill_no):
    """'126023937_16466' -> '126023937': the DMS appends its order id to the supplier's
    billing document when one invoice covers several DMS orders."""
    return _s(bill_no).split('_', 1)[0]


PARSERS = {
    FEED_INVENTORY: parse_inventory,
    FEED_DISPATCH_PENDING: parse_dispatch_pending,
    FEED_GRN: parse_grn,
}


def parse(feed, stream, filename):
    """{table_key: rows}, warnings. Raises ParseError on the wrong file or no rows."""
    if feed not in PARSERS:
        raise ParseError(f'Unknown upload type: {feed}')
    data = stream.read()
    tables, warnings = PARSERS[feed](data, filename)
    if not any(tables.values()):
        raise ParseError(f'No usable rows in this {FEED_LABELS[feed]}. Nothing was changed.')
    return tables, warnings
