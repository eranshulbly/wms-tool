# -*- encoding: utf-8 -*-
"""Readers for the three files PO Builder takes in. Pure parsing — nothing is stored here.

  parse_sku_master   the DMS "Category Wise SKU Master" export (CSV or Excel)
  parse_scheme_map   the quarterly SKU -> scheme map (one row per SKU, slabs on the row)
  parse_list         a customer list / quotation: a file, or cells pasted from a sheet

Headers are matched loosely ("(%)GST", "Is Active ?" and "SKU Code (corrected)" all
resolve), and every reader reports what it skipped and why rather than dropping rows.
"""

import csv
import io
import re

import openpyxl

from api.modules.procurement.po_builder.matching import derive_finish


class ParseError(ValueError):
    """The file cannot be used at all (wrong file, missing required columns)."""


def _norm(h):
    return re.sub(r'[^a-z0-9]', '', str(h or '').lower())


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(',', '').replace('₹', '').strip()
    if s in ('', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _read_tables(data, filename):
    """[(sheet_name, rows)] — every sheet of a workbook, or the one table of a CSV."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise ParseError(f'Could not open the workbook: {e}')
        out = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        wb.close()
        return out
    if name.endswith('.xls'):
        import xlrd
        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as e:
            raise ParseError(f'Could not open the workbook: {e}')
        return [(sh.name, [sh.row_values(i) for i in range(sh.nrows)]) for sh in book.sheets()]
    if name.endswith(('.csv', '.txt', '.tsv')) or not name:
        for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return [('Pasted' if not name else 'CSV', _split_text(text))]
    raise ParseError('Upload a .xlsx, .xls or .csv file.')


def _split_text(text):
    """Rows of a CSV or of cells pasted from a sheet (tab-separated)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    delim = '\t' if any('\t' in ln for ln in lines) else ','
    return [list(r) for r in csv.reader(lines, delimiter=delim)]


def _find_header(rows, wanted, required, scan=30):
    """(row_index, {field: col}) of the first row that names every required field.

    `wanted` maps field -> list of (predicate(normalised header), score); the best
    scoring column wins per field, so "SKU Code (corrected)" beats "Code (as quoted)".
    """
    for i, row in enumerate(rows[:scan]):
        heads = [_norm(c) for c in row]
        cols = {}
        for field, rules in wanted.items():
            best = None
            for j, h in enumerate(heads):
                if not h:
                    continue
                for pred, score in rules:
                    if pred(h) and (best is None or score > best[0]):
                        best = (score, j)
            if best:
                cols[field] = best[1]
        if all(f in cols for f in required):
            return i, cols
    return None, None


def _cell(row, col):
    return row[col] if col is not None and col < len(row) else None


# --------------------------------------------------------------------------------------
# SKU master
# --------------------------------------------------------------------------------------

_MASTER_COLS = {
    'sku_code':    [(lambda h: h in ('skucode', 'itemcode'), 3), (lambda h: h == 'code', 1)],
    'dms_sku_id':  [(lambda h: h == 'skuid', 3)],
    'description': [(lambda h: h == 'skuname', 3), (lambda h: h == 'description', 2),
                    (lambda h: h == 'itemname', 1)],
    'category':    [(lambda h: h == 'category', 3)],
    'mrp':         [(lambda h: h == 'mrp', 3)],
    'gst_pct':     [(lambda h: h in ('gst', 'gstpercent', 'gstrate'), 3)],
    'hsn_code':    [(lambda h: h in ('hsncode', 'hsn'), 3)],
    'spu':         [(lambda h: h == 'spu', 3)],
    'uom':         [(lambda h: h == 'uom', 3)],
    'is_active':   [(lambda h: h in ('isactive', 'active'), 3), (lambda h: h == 'status', 1)],
}


# Every column is required except UOM and the active flag. The labels are what the file
# is told to contain when a column is missing (DMS "Category Wise SKU Master" headers).
_MASTER_REQUIRED = (('sku_code', 'SKU_Code'), ('dms_sku_id', 'Sku_Id'), ('description', 'Sku Name'),
                    ('category', 'Category'), ('mrp', 'Mrp'), ('gst_pct', '(%)GST'), ('spu', 'SPU'))


def parse_sku_master(data, filename, suffixes):
    """{items: [...], skipped: [...], duplicates: n, row_count: n}.

    A missing required column rejects the file; a row with a required value blank (or an
    MRP / SPU that is not a positive number, a GST that is not a number) is skipped and
    reported, never stored with a made-up value.
    """
    tables = _read_tables(data, filename)
    for _, rows in tables:
        hi, cols = _find_header(rows, _MASTER_COLS, ('sku_code', 'mrp'))
        if hi is not None:
            break
    else:
        raise ParseError('No header row with an SKU_Code column and an Mrp column was found.')
    missing = [label for field, label in _MASTER_REQUIRED if field not in cols]
    if missing:
        raise ParseError('Required column(s) missing: ' + ', '.join(missing) + '. Only UOM and Is Active ? are optional.')

    items, skipped, dupes = {}, [], 0
    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        code = _text(_cell(row, cols['sku_code']))
        if not code:
            continue
        mrp = _num(_cell(row, cols['mrp']))
        gst = _num(_cell(row, cols['gst_pct']))
        spu = _num(_cell(row, cols['spu']))
        texts = {f: _text(_cell(row, cols[f])) for f in ('dms_sku_id', 'description', 'category')}
        problems = [label for (field, label) in _MASTER_REQUIRED if field in texts and not texts[field]]
        if mrp is None or mrp <= 0:
            problems.append('Mrp')
        if gst is None or gst < 0:
            problems.append('(%)GST')
        if spu is None or spu <= 0:
            problems.append('SPU')
        if problems:
            skipped.append({'row': n, 'sku_code': code, 'reason': 'Blank or invalid: ' + ', '.join(problems)})
            continue
        active_raw = _text(_cell(row, cols.get('is_active'))).lower()
        active = active_raw not in ('inactive', 'no', 'n', '0', 'false')
        item = {
            'sku_code': code,
            'dms_sku_id': texts['dms_sku_id'],
            'description': texts['description'][:500],
            'category': texts['category'][:128],
            'finish': derive_finish(code, suffixes),
            'mrp': mrp,
            'gst_pct': gst,
            'hsn_code': _text(_cell(row, cols.get('hsn_code')))[:20],
            'spu': spu,
            'uom': _text(_cell(row, cols.get('uom')))[:16],
            'is_active': active,
            'raw': {str(h): _text(v) for h, v in zip(rows[hi], row) if h not in (None, '')},
        }
        key = code.upper()
        if key in items:
            dupes += 1
            # The DMS keeps retired copies of a code next to the live one: an active row
            # always beats an inactive one; otherwise the later row wins.
            if items[key]['is_active'] and not active:
                continue
        items[key] = item
    return {'items': list(items.values()), 'skipped': skipped, 'duplicates': dupes,
            'row_count': len(rows) - hi - 1}


# --------------------------------------------------------------------------------------
# Scheme map
# --------------------------------------------------------------------------------------

_SCHEME_COLS = {
    'sku_code':    [(lambda h: h in ('skucode', 'itemcode'), 3), (lambda h: h == 'code', 1)],
    'scheme_no':   [(lambda h: h in ('schemeno', 'schemenumber', 'scheme'), 3)],
    'name':        [(lambda h: h in ('schemedescription', 'schemename', 'groupname'), 3)],
    'category':    [(lambda h: h == 'category', 3)],
    'basis':       [(lambda h: h == 'basis', 3)],
}

_NO_SCHEME = ('', 'noscheme', 'none', 'na', 'nil')


def _pct(v):
    """0.03 or 3 or '3%' -> 3.0"""
    n = _num(str(v).replace('%', '') if isinstance(v, str) else v)
    if n is None:
        return None
    return n * 100 if n <= 1 else n


def parse_scheme_map(data, filename):
    """{groups: {scheme_no: {...}}, sku_map: {sku: scheme_no}, errors, warnings, ...}.

    `errors` block the upload (a SKU in two schemes, one scheme with two slab ladders);
    `warnings` do not (odd slabs, a SKU both in a scheme and marked "No scheme").
    """
    tables = _read_tables(data, filename)
    for _, rows in tables:
        hi, cols = _find_header(rows, _SCHEME_COLS, ('sku_code', 'scheme_no'))
        if hi is not None:
            break
    else:
        raise ParseError('No header row with "SKU Code" and "Scheme No" columns was found.')
    missing = [label for field, label in (('category', 'Category'), ('basis', 'Basis')) if field not in cols]
    if missing:
        raise ParseError('Required column(s) missing: ' + ', '.join(missing) + '.')

    heads = [_norm(c) for c in rows[hi]]
    slab_cols = {}
    for j, h in enumerate(heads):
        m = re.fullmatch(r'slab(\d+)(min|minimum|pct|percent|)', h)
        if m:
            kind = 'min' if m.group(2).startswith('min') else 'pct'
            slab_cols.setdefault(int(m.group(1)), {})[kind] = j
    slab_nos = sorted(n for n, c in slab_cols.items() if 'min' in c and 'pct' in c)
    if not slab_nos:
        raise ParseError('No slab columns found (expected "Slab 1 %", "Slab 1 Min", ...).')

    groups, sku_map, no_scheme = {}, {}, set()
    errors, warnings = [], []
    conflicts = {}
    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        code = _text(_cell(row, cols['sku_code']))
        if not code:
            continue
        sno = _text(_cell(row, cols['scheme_no']))
        if _norm(sno) in _NO_SCHEME:
            no_scheme.add(code.upper())
            continue
        category = _text(_cell(row, cols['category']))
        if not category:
            errors.append(f'Row {n}: {code} (scheme {sno}) has no Category.')
            continue
        basis_raw = _norm(_cell(row, cols['basis']))
        basis = 'VALUE' if basis_raw.startswith('val') else 'QTY' if basis_raw.startswith(('qty', 'quan')) else None
        slabs = []
        for k in slab_nos:
            mn = _num(_cell(row, slab_cols[k]['min']))
            pc = _pct(_cell(row, slab_cols[k]['pct']))
            if mn is not None and pc is not None:
                slabs.append({'slab_no': k, 'min_threshold': mn, 'discount_pct': round(pc, 3)})
        sig = (basis, tuple((s['min_threshold'], s['discount_pct']) for s in slabs))
        g = groups.get(sno)
        if g is None:
            if basis is None:
                errors.append(f'Row {n}: scheme {sno} has no basis (Qty / Value).')
                continue
            if not slabs:
                errors.append(f'Row {n}: scheme {sno} has no slabs.')
                continue
            groups[sno] = g = {
                'scheme_no': sno,
                'name': _text(_cell(row, cols.get('name')))[:1000],
                'category': category[:128],
                'basis': basis, 'slabs': slabs, '_sig': sig, 'sku_count': 0,
            }
        elif g['_sig'] != sig:
            errors.append(f'Row {n}: scheme {sno} has different basis/slabs than its first row.')
            continue
        key = code.upper()
        if key in sku_map and sku_map[key] != sno:
            conflicts.setdefault(code, {sku_map[key]}).add(sno)
            continue
        if key not in sku_map:
            sku_map[key] = sno
            g['sku_count'] += 1

    for code, snos in sorted(conflicts.items()):
        errors.append(f'SKU {code} is in more than one scheme: {", ".join(sorted(snos))}.')
    both = sorted(set(sku_map) & no_scheme)
    if both:
        warnings.append(f'{len(both)} SKU(s) appear both in a scheme and as "No scheme" '
                        f'(kept in the scheme): {", ".join(both[:8])}'
                        + ('…' if len(both) > 8 else ''))
    for g in groups.values():
        mins = [s['min_threshold'] for s in g['slabs']]
        pcts = [s['discount_pct'] for s in g['slabs']]
        if any(b <= a for a, b in zip(mins, mins[1:])) or any(b <= a for a, b in zip(pcts, pcts[1:])):
            warnings.append(
                f"{g['scheme_no']}: slabs do not rise steadily ("
                + ', '.join(f"{s['discount_pct']:g}% from {s['min_threshold']:g}" for s in g['slabs'])
                + ') — the highest slab reached is applied.')
        del g['_sig']
    return {'groups': groups, 'sku_map': sku_map,
            'no_scheme_count': len(no_scheme - set(sku_map)),
            'errors': errors, 'warnings': warnings}


# --------------------------------------------------------------------------------------
# Customer lists / quotations
# --------------------------------------------------------------------------------------

_LIST_COLS = {
    'code':   [(lambda h: 'sku' in h and 'code' in h, 4), (lambda h: h in ('itemcode', 'productcode', 'partcode', 'partno'), 3),
               (lambda h: h.startswith('code'), 2), (lambda h: h in ('sku', 'item'), 1)],
    'qty':    [(lambda h: h in ('qty', 'quantity', 'orderqty', 'totalqty'), 3),
               (lambda h: 'qty' in h or 'quantity' in h, 2)],
    'finish': [(lambda h: h == 'finish', 3), (lambda h: 'finish' in h, 2)],
    'desc':   [(lambda h: h == 'description', 3), (lambda h: 'desc' in h or h in ('itemname', 'particulars'), 2)],
}


def parse_list(data=None, filename=None, text=None, sheet=None):
    """{sheets, sheet, columns, rows: [{row_no, code, qty, finish, desc}]}.

    The list is SKU code and quantity, with finish as an optional third column. A sheet
    with a recognisable header is read by header; text pasted without headers is read
    positionally as code, qty, finish.
    """
    if text is not None:
        tables = [('Pasted', _split_text(text))]
    else:
        tables = _read_tables(data, filename)
    names = [t[0] for t in tables]
    if sheet:
        tables = [t for t in tables if t[0] == sheet] or tables

    chosen = None
    for name, rows in tables:
        hi, cols = _find_header(rows, _LIST_COLS, ('code', 'qty'))
        if hi is not None:
            chosen = (name, rows, hi, cols)
            break
    if chosen is None:
        name, rows = tables[0]
        if not rows:
            raise ParseError('Nothing to import — the list is empty.')
        if len(rows[0]) < 2:
            raise ParseError('Need two columns: SKU code and quantity.')
        chosen = (name, rows, -1, {'code': 0, 'qty': 1, 'finish': 2 if len(rows[0]) > 2 else None})
    name, rows, hi, cols = chosen
    header = rows[hi] if hi >= 0 else []

    out = []
    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        code = _text(_cell(row, cols['code']))
        if not code:
            continue
        # A blank, 0 or unreadable qty is taken as 0: the SKU still goes into the PO and
        # its qty can be filled in there.
        qty = _num(_cell(row, cols['qty']))
        out.append({
            'row_no': n,
            'code': code[:255],
            'qty': qty if qty is not None and qty > 0 else 0.0,
            'finish': _text(_cell(row, cols.get('finish')))[:64],
            'desc': _text(_cell(row, cols.get('desc')))[:500],
        })
    used = {f: (_text(header[c]) if hi >= 0 and c is not None and c < len(header) else f'column {c + 1}')
            for f, c in cols.items() if c is not None}
    return {'sheets': names, 'sheet': name, 'columns': used, 'rows': out}
