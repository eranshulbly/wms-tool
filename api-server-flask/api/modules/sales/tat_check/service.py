# -*- encoding: utf-8 -*-
"""sales.tat_check service — loads the uploads and answers "where is this SKU?".

The only cross-module API of this module. Parsing lives in parser.py and the rules in
tat.py; this file is the database half of both.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from api.shared.db_manager import mysql_manager
from api.modules.sales.tat_check import parser as P
from api.modules.sales.tat_check import tat as T


class TatCheckError(Exception):
    pass


def ebco_company_id():
    """TAT Check is Ebco only — same company lookup PO Builder uses."""
    from api.modules.procurement.po_builder import service as pob
    try:
        return pob.ebco_company_id()
    except pob.PoBuilderError as e:
        raise TatCheckError(str(e))


# table key (from the parser) -> (table, columns)
_TABLES = {
    'inventory': ('tat_inventory', ['sku_code', 'sku_name', 'stock_qty']),
    'dispatch': ('tat_dispatch', ['plant', 'billing_date', 'billing_doc', 'doc_ref_id',
                                  'sku_code', 'sku_name', 'qty']),
    'pending': ('tat_pending', ['plant', 'order_date', 'po_number', 'sales_doc',
                                'sales_doc_item', 'sku_code', 'sku_name', 'order_qty',
                                'delivered_qty', 'open_qty']),
    'grn': ('tat_grn', ['bill_no', 'billing_doc', 'invoice_no', 'sku_code', 'sku_name',
                        'qty_uploaded', 'qty_approved', 'uploaded_date', 'approved_date']),
}

# Which tables each feed replaces.
_FEED_TABLES = {
    P.FEED_INVENTORY: ['inventory'],
    P.FEED_DISPATCH_PENDING: ['dispatch', 'pending'],
    P.FEED_GRN: ['grn'],
}


# ── uploads ──────────────────────────────────────────────────────────────────

def ingest(feed, stream, filename, company_id, user):
    """Parse and load one upload, replacing that feed's rows in one transaction — a
    failure part-way leaves the previous upload in place, never half of this one."""
    tables, warnings = P.parse(feed, stream, filename)
    counts = {}
    with mysql_manager.get_cursor() as cur:
        cur.execute(
            """INSERT INTO tat_upload_log (company_id, feed, filename, row_count, uploaded_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (company_id, feed, (filename or '')[:255],
             sum(len(tables.get(k) or []) for k in _FEED_TABLES[feed]), (user or 'system')[:100]))
        upload_id = cur.lastrowid
        for key in _FEED_TABLES[feed]:
            table, cols = _TABLES[key]
            rows = tables.get(key) or []
            all_cols = ['company_id', 'upload_id'] + cols
            cur.execute(f'DELETE FROM {table} WHERE company_id = %s', (company_id,))
            if rows:
                cur.executemany(
                    f'INSERT INTO {table} ({", ".join(all_cols)}) '
                    f'VALUES ({", ".join(["%s"] * len(all_cols))})',
                    [(company_id, upload_id, *[r[c] for c in cols]) for r in rows])
            counts[key] = len(rows)
    return {
        'feed': feed, 'label': P.FEED_LABELS[feed], 'filename': filename,
        'counts': counts, 'warnings': warnings[:50], 'warning_count': len(warnings),
    }


def feed_status(company_id):
    """Last upload and stored rows per feed — what the upload panel shows."""
    out = []
    for feed, keys in _FEED_TABLES.items():
        last = mysql_manager.execute_query(
            """SELECT filename, row_count, uploaded_by, uploaded_on FROM tat_upload_log
               WHERE company_id = %s AND feed = %s ORDER BY id DESC LIMIT 1""",
            (company_id, feed))
        stored = {}
        for key in keys:
            n = mysql_manager.execute_query(
                f'SELECT COUNT(*) AS n FROM {_TABLES[key][0]} WHERE company_id = %s',
                (company_id,))
            stored[key] = n[0]['n'] if n else 0
        out.append({'feed': feed, 'label': P.FEED_LABELS[feed], 'stored': stored,
                    'last_upload': _upload_out(last[0]) if last else None})
    return out


def sources(company_id):
    """Every file TAT Check depends on and when it was last uploaded — the SKU master
    (searched) and the three feeds (quantities). What the TAT Check page shows on top."""
    from api.modules.procurement.po_builder import service as pob
    master = pob.current_master(company_id)
    out = [{'key': 'sku_master', 'label': 'SKU Master',
            'last_upload': _upload_out({'filename': master['filename'],
                                        'row_count': master['row_count'],
                                        'uploaded_by': master['uploaded_by'],
                                        'uploaded_on': master['uploaded_on']}) if master else None}]
    out += [{'key': f['feed'], 'label': f['label'], 'last_upload': f['last_upload']}
            for f in feed_status(company_id)]
    return out


# ── lookup ───────────────────────────────────────────────────────────────────

MAX_RESULTS = 25


def lookup(company_id, q):
    """SKUs matching `q`, each with qty in stock / in transit / in PO and its status.

    SKUs are searched in the SKU master, not in the uploads: a pasted code that matches a
    master SKU exactly returns just that SKU, otherwise code or name is matched partially.
    A master SKU that is in none of the uploads comes back as Not available.
    """
    q = (q or '').strip()
    if not q:
        return []
    master_names = _matching_codes(company_id, q)
    codes = list(master_names)
    if not codes:
        return []

    marks = ', '.join(['%s'] * len(codes))
    args = (company_id, *codes)
    stock = mysql_manager.execute_query(
        f'SELECT sku_code, sku_name, stock_qty FROM tat_inventory '
        f'WHERE company_id = %s AND sku_code IN ({marks})', args) or []
    dispatch = mysql_manager.execute_query(
        f'SELECT plant, billing_date, billing_doc, doc_ref_id, sku_code, sku_name, qty '
        f'FROM tat_dispatch WHERE company_id = %s AND sku_code IN ({marks}) '
        f'ORDER BY billing_date, billing_doc', args) or []
    approved = mysql_manager.execute_query(
        f'SELECT billing_doc, sku_code, qty_uploaded, approved_date FROM tat_grn '
        f'WHERE company_id = %s AND approved_date IS NOT NULL AND sku_code IN ({marks})',
        args) or []
    pending = mysql_manager.execute_query(
        f'SELECT plant, order_date, po_number, sales_doc, sku_code, sku_name, order_qty, '
        f'delivered_qty, open_qty FROM tat_pending '
        f'WHERE company_id = %s AND sku_code IN ({marks}) ORDER BY order_date, po_number',
        args) or []

    names, stock_qty = dict(master_names), defaultdict(float)
    for r in stock:
        stock_qty[r['sku_code']] += float(r['stock_qty'])
        names.setdefault(r['sku_code'], r['sku_name'])
    transit = defaultdict(list)
    for d in T.in_transit(dispatch, approved):
        transit[d['sku_code']].append(d)
        names.setdefault(d['sku_code'], d['sku_name'])
    po = defaultdict(list)
    for p in pending:
        po[p['sku_code']].append(p)
        names.setdefault(p['sku_code'], p['sku_name'])

    results = []
    for code in codes:
        t_lines, p_lines = transit.get(code, []), po.get(code, [])
        summary = T.summarize(stock_qty.get(code, 0.0), t_lines,
                              sum(float(p['open_qty']) for p in p_lines))
        summary = {**summary, 'eta': _iso(summary['eta']),
                   'buckets': [_jsonable(b) for b in summary['buckets']]}
        results.append({
            'sku_code': code,
            'sku_name': names.get(code, ''),
            'in_inventory_file': code in stock_qty,
            **summary,
            'transit_lines': [_jsonable({
                'billing_doc': d['billing_doc'], 'billing_date': d['billing_date'],
                'eta': d['eta'], 'plant': d['plant'], 'qty': d['qty']}) for d in t_lines],
            'po_lines': [_jsonable({
                'po_number': p['po_number'], 'order_date': p['order_date'],
                'plant': p['plant'], 'order_qty': p['order_qty'],
                'delivered_qty': p['delivered_qty'], 'open_qty': p['open_qty']})
                for p in p_lines],
        })
    return results


SUGGEST_LIMIT = 15


def _master_id(company_id):
    """The SKU master in force — PO Builder's latest upload (Admin → SKU Master Upload).
    TAT Check searches SKUs in it, so a SKU is found even when it is in no upload yet."""
    from api.modules.procurement.po_builder import service as pob
    master = pob.current_master(company_id)
    if not master:
        raise TatCheckError('No SKU master uploaded yet — upload one from Admin → SKU Master Upload.')
    return master['id']


def suggest(company_id, q):
    """Type-ahead from the SKU master: SKUs whose code or description contains `q`, codes
    starting with `q` first, active before inactive. Code and name only — the quantities
    come from lookup()."""
    q = (q or '').strip()
    if not q:
        return []
    like = f'%{q}%'
    rows = mysql_manager.execute_query(
        """SELECT sku_code, description AS sku_name FROM dms_sku_master_item
           WHERE master_id = %s AND (sku_code LIKE %s OR description LIKE %s)
           ORDER BY sku_code LIKE %s DESC, is_active DESC, sku_code
           LIMIT %s""",
        (_master_id(company_id), like, like, f'{q}%', SUGGEST_LIMIT)) or []
    return [{'sku_code': r['sku_code'], 'sku_name': r['sku_name'] or ''} for r in rows]


def _matching_codes(company_id, q):
    """{code: master description} for the SKU master entries matching `q` — the one SKU
    whose code is exactly `q` when there is one, else partial matches on code or name."""
    master_id = _master_id(company_id)
    rows = mysql_manager.execute_query(
        'SELECT sku_code, description FROM dms_sku_master_item WHERE master_id = %s AND sku_code = %s',
        (master_id, q)) or []
    if not rows:
        like = f'%{q}%'
        rows = mysql_manager.execute_query(
            """SELECT sku_code, description FROM dms_sku_master_item
               WHERE master_id = %s AND (sku_code LIKE %s OR description LIKE %s)
               ORDER BY sku_code LIKE %s DESC, is_active DESC, sku_code
               LIMIT %s""",
            (master_id, like, like, f'{q}%', MAX_RESULTS)) or []
    return {r['sku_code']: r['description'] or '' for r in rows}


def _upload_out(row):
    """An upload record for the browser. `uploaded_on` is filled by MySQL's
    CURRENT_TIMESTAMP, which is UTC on both the dev and Ebco databases, so it is sent
    marked as UTC ('Z') and the browser shows it in local time."""
    out = _jsonable(row)
    if isinstance(row.get('uploaded_on'), datetime):
        out['uploaded_on'] = row['uploaded_on'].isoformat() + 'Z'
    return out


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _jsonable(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, (Decimal, float)):
            f = float(v)
            out[k] = int(f) if f.is_integer() else f
        else:
            out[k] = v
    return out
