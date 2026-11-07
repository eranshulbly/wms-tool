# -*- encoding: utf-8 -*-
"""PO Builder — everything that touches the database. See schema.py for the tables and
pricing.py / matching.py for the rules (both pure, and tested on their own).
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from api.shared.db_manager import mysql_manager
from api.modules.procurement.po_builder import pricing
from api.modules.procurement.po_builder.matching import (
    DEFAULT_FINISH_SUFFIXES, Matcher, parse_suffixes)
from api.modules.procurement.po_builder.parsers import (
    parse_list, parse_scheme_map, parse_sku_master)


class PoBuilderError(ValueError):
    """A request that cannot be done as asked; the message is shown to the user."""


class NotFound(PoBuilderError):
    pass


def _q(sql, params=()):
    return mysql_manager.execute_query(sql, params)


def _one(sql, params=()):
    rows = _q(sql, params)
    return rows[0] if rows else None


def _f(v):
    return float(v) if v is not None else None


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _parse_date(v, field='date'):
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise PoBuilderError(f'Invalid {field} — use YYYY-MM-DD.')


# ======================================================================================
# Settings
# ======================================================================================

def ebco_company_id():
    """PO Builder is an Ebco-only tool: it always works on the Ebco company.

    The company whose name starts with "Ebco" (EBCO, Ebco Pvt Ltd, ...); on a database that
    holds a single company, that one. Never chosen by the caller.
    """
    rows = _q("SELECT company_id FROM company WHERE LOWER(TRIM(name)) LIKE 'ebco%%' ORDER BY company_id")
    if len(rows) == 1:
        return rows[0]['company_id']
    if not rows:
        only = _q('SELECT company_id FROM company')
        if len(only) == 1:
            return only[0]['company_id']
    raise PoBuilderError('Could not identify the Ebco company (expected exactly one company named '
                         '"Ebco…"). Ask an admin to check the company list.')


_SETTING_FIELDS = ('dtr_discount_pct', 'std_discount_pct', 'show_case_helper')
# The DMS ids the DMS order upload is raised under — kept apart from the pricing settings
# (pob_dms_order_settings), and never frozen into a PO: they say who places the order in
# the DMS, not what it costs.
_DMS_ORDER_FIELDS = ('dms_user_id', 'dms_outlet_id', 'dms_warehouse_id')
# Used until a value is saved, and when one is cleared: the ids on Ebco's own DMS order
# upload sample (upload-secondary-and-primary-order-final.csv) — Anmol Associates' DMS user.
_DMS_ORDER_DEFAULTS = {'dms_user_id': '171', 'dms_outlet_id': '4962', 'dms_warehouse_id': '1'}


def get_settings(company_id):
    row = _one('SELECT * FROM pob_settings WHERE company_id = %s', (company_id,))
    if row is None:
        mysql_manager.execute_query(
            'INSERT IGNORE INTO pob_settings (company_id) VALUES (%s)', (company_id,), fetch=False)
        row = _one('SELECT * FROM pob_settings WHERE company_id = %s', (company_id,))
    dms = _one('SELECT * FROM pob_dms_order_settings WHERE company_id = %s', (company_id,)) or {}
    return {
        'dtr_discount_pct': float(row['dtr_discount_pct']),
        'std_discount_pct': float(row['std_discount_pct']),
        'show_case_helper': bool(row['show_case_helper']),
        **{k: dms.get(k) or _DMS_ORDER_DEFAULTS[k] for k in _DMS_ORDER_FIELDS},
        'updated_by': row['updated_by'],
        'updated_on': _iso(row['updated_on']),
    }


def update_settings(company_id, body, username):
    get_settings(company_id)
    sets, params = [], []
    for k in _SETTING_FIELDS:
        if k not in body:
            continue
        v = body[k]
        if k in ('dtr_discount_pct', 'std_discount_pct'):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise PoBuilderError(f'{k} must be a number.')
            if not 0 <= v < 100:
                raise PoBuilderError('Discounts must be between 0 and 100%.')
        else:
            v = 1 if v else 0
        sets.append(f'{k} = %s')
        params.append(v)
    if sets:
        sets.append('updated_by = %s')
        params += [username, company_id]
        mysql_manager.execute_query(
            f'UPDATE pob_settings SET {", ".join(sets)} WHERE company_id = %s', params, fetch=False)
    dms = {}
    for k in _DMS_ORDER_FIELDS:
        if k in body:
            v = str(body[k] if body[k] is not None else '').strip()
            if v and not v.isdigit():
                raise PoBuilderError('DMS user, outlet and warehouse ids must be numbers.')
            dms[k] = v
    if dms:
        cols = list(dms)
        mysql_manager.execute_query(
            f'INSERT INTO pob_dms_order_settings (company_id, {", ".join(cols)}, updated_by) '
            f'VALUES (%s, {", ".join(["%s"] * len(cols))}, %s) '
            f'ON DUPLICATE KEY UPDATE {", ".join(f"{c} = VALUES({c})" for c in cols)}, '
            f'updated_by = VALUES(updated_by)',
            (company_id, *[dms[c] for c in cols], username), fetch=False)
    return get_settings(company_id)


def _suffixes(company_id):
    """Finish suffixes recognised at the end of a code — a fixed list (see matching.py)."""
    return parse_suffixes(DEFAULT_FINISH_SUFFIXES)


# ======================================================================================
# SKU master
# ======================================================================================

def current_master(company_id):
    return _one('SELECT * FROM dms_sku_master WHERE company_id = %s ORDER BY id DESC LIMIT 1',
                (company_id,))


def list_masters(company_id):
    rows = _q('SELECT * FROM dms_sku_master WHERE company_id = %s ORDER BY id DESC', (company_id,))
    used = {r['sku_master_id']: r['n'] for r in _q(
        'SELECT sku_master_id, COUNT(*) n FROM pob_po WHERE company_id = %s GROUP BY sku_master_id',
        (company_id,))}
    return [{**_master_out(r), 'po_count': used.get(r['id'], 0)} for r in rows]


def _master_out(r):
    return {'id': r['id'], 'name': r['name'], 'filename': r['filename'],
            'row_count': r['row_count'], 'active_count': r['active_count'],
            'uploaded_by': r['uploaded_by'], 'uploaded_on': _iso(r['uploaded_on'])}


def sku_master_upload(company_id, data, filename, name, username, commit):
    """Preview (commit=False) or load a new SKU-master version.

    The preview compares the file with the current version so a bad export (an OCR'd
    list, a different company's file) is caught before it becomes the price basis.
    """
    parsed = parse_sku_master(data, filename, _suffixes(company_id))
    items = parsed['items']
    if not items:
        raise PoBuilderError('The file has no SKU rows.')
    cur = current_master(company_id)
    diff = {'new': 0, 'removed': 0, 'mrp_changed': 0, 'gst_changed': 0,
            'activated': 0, 'deactivated': 0, 'mrp_samples': []}
    if cur:
        old = {r['sku_code'].upper(): r for r in _q(
            'SELECT sku_code, mrp, gst_pct, is_active FROM dms_sku_master_item WHERE master_id = %s',
            (cur['id'],))}
        seen = set()
        for it in items:
            k = it['sku_code'].upper()
            seen.add(k)
            o = old.get(k)
            if o is None:
                diff['new'] += 1
                continue
            if abs(float(o['mrp']) - it['mrp']) > 0.005:
                diff['mrp_changed'] += 1
                if len(diff['mrp_samples']) < 15:
                    diff['mrp_samples'].append(
                        {'sku_code': it['sku_code'], 'old': float(o['mrp']), 'new': it['mrp']})
            if abs(float(o['gst_pct']) - it['gst_pct']) > 0.005:
                diff['gst_changed'] += 1
            if bool(o['is_active']) != it['is_active']:
                diff['activated' if it['is_active'] else 'deactivated'] += 1
        diff['removed'] = len(set(old) - seen)

    summary = {
        'filename': filename,
        'row_count': parsed['row_count'],
        'sku_count': len(items),
        'active_count': sum(1 for i in items if i['is_active']),
        'duplicates': parsed['duplicates'],
        'skipped': parsed['skipped'][:50],
        'skipped_count': len(parsed['skipped']),
        'gst_rates': _counts(f"{i['gst_pct']:g}%" for i in items if i['is_active']),
        'categories': _counts(i['category'] or '(none)' for i in items if i['is_active']),
        'missing_dms_id': sum(1 for i in items if i['is_active'] and not i['dms_sku_id']),
        'current': _master_out(cur) if cur else None,
        'diff': diff if cur else None,
    }
    if not commit:
        return {'preview': summary}

    with mysql_manager.get_cursor() as c:
        c.execute('INSERT INTO dms_sku_master (company_id, name, filename, row_count, active_count, '
                  'uploaded_by) VALUES (%s, %s, %s, %s, %s, %s)',
                  (company_id, (name or filename or 'SKU master')[:255], (filename or '')[:255],
                   len(items), summary['active_count'], username))
        mid = c.lastrowid
        rows = [(mid, i['sku_code'], i['dms_sku_id'], i['description'], i['category'], i['finish'],
                 i['mrp'], i['gst_pct'], i['hsn_code'], i['spu'], i['uom'], 1 if i['is_active'] else 0,
                 json.dumps(i['raw'], ensure_ascii=False)) for i in items]
        for k in range(0, len(rows), 1000):
            c.executemany(
                'INSERT INTO dms_sku_master_item (master_id, sku_code, dms_sku_id, description, '
                'category, finish, mrp, gst_pct, hsn_code, spu, uom, is_active, raw) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', rows[k:k + 1000])
    return {'master': _master_out(current_master(company_id)), 'preview': summary}


def _counts(values):
    out = defaultdict(int)
    for v in values:
        out[v] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _master_items(master_id, codes=None, active_only=False):
    sql = ('SELECT sku_code, dms_sku_id, description, category, finish, mrp, gst_pct, spu, uom, '
           'is_active FROM dms_sku_master_item WHERE master_id = %s')
    params = [master_id]
    if active_only:
        sql += ' AND is_active = 1'
    if codes is not None:
        if not codes:
            return {}
        sql += f' AND sku_code IN ({",".join(["%s"] * len(codes))})'
        params += list(codes)
    return {r['sku_code']: r for r in _q(sql, params)}


def _item_out(r):
    return {'sku_code': r['sku_code'], 'dms_sku_id': r['dms_sku_id'],
            'description': r['description'], 'category': r['category'], 'finish': r['finish'],
            'mrp': float(r['mrp']), 'gst_pct': float(r['gst_pct']), 'spu': float(r['spu']),
            'uom': r['uom'], 'is_active': bool(r['is_active'])}


# ======================================================================================
# Schemes
# ======================================================================================

def list_schemes(company_id):
    rows = _q('SELECT * FROM dms_scheme WHERE company_id = %s ORDER BY id DESC', (company_id,))
    return [{**_scheme_out(r), 'current': i == 0} for i, r in enumerate(rows)]


def _scheme_out(r):
    return {'id': r['id'], 'name': r['name'], 'filename': r['filename'], 'group_count': r['group_count'],
            'sku_count': r['sku_count'], 'uploaded_by': r['uploaded_by'],
            'uploaded_on': _iso(r['uploaded_on'])}


def current_scheme(company_id):
    """The scheme in force: the one uploaded last. A scheme stays valid until the next
    upload replaces it, so there are no validity dates."""
    return _one('SELECT * FROM dms_scheme WHERE company_id = %s ORDER BY id DESC LIMIT 1', (company_id,))


def _get_scheme(company_id, scheme_id):
    r = _one('SELECT * FROM dms_scheme WHERE id = %s AND company_id = %s', (scheme_id, company_id))
    if not r:
        raise NotFound('Scheme not found.')
    return r


def scheme_upload(company_id, data, filename, form, username, commit):
    parsed = parse_scheme_map(data, filename)
    name = (form.get('name') or '').strip()
    cur = current_master(company_id)
    unknown = []
    if cur:
        known = {r['sku_code'].upper() for r in _q(
            'SELECT sku_code FROM dms_sku_master_item WHERE master_id = %s', (cur['id'],))}
        unknown = sorted(k for k in parsed['sku_map'] if k not in known)
    groups = sorted(parsed['groups'].values(), key=lambda g: pricing._scheme_sort_key(g['scheme_no']))
    preview = {
        'filename': filename,
        'group_count': len(groups),
        'sku_count': len(parsed['sku_map']),
        'no_scheme_count': parsed['no_scheme_count'],
        'basis_counts': _counts(g['basis'] for g in groups),
        'groups': [{k: g[k] for k in ('scheme_no', 'name', 'basis', 'slabs', 'sku_count')}
                   for g in groups],
        'errors': parsed['errors'],
        'warnings': parsed['warnings'],
        'unknown_skus': unknown[:30],
        'unknown_sku_count': len(unknown),
    }
    if not commit:
        return {'preview': preview}

    if parsed['errors']:
        raise PoBuilderError('Fix the errors in the file first — nothing was saved.')
    if not name:
        # scheme_ddmmyyyy, the upload date in IST.
        name = 'scheme_' + (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%d%m%Y')
    with mysql_manager.get_cursor() as c:
        c.execute('INSERT INTO dms_scheme (company_id, name, filename, group_count, sku_count, uploaded_by) '
                  'VALUES (%s,%s,%s,%s,%s,%s)',
                  (company_id, name[:255], (filename or '')[:255], len(groups), len(parsed['sku_map']), username))
        sid = c.lastrowid
        gid_by_no = {}
        for g in groups:
            c.execute('INSERT INTO dms_scheme_group (scheme_id, scheme_no, name, category, basis) '
                      'VALUES (%s,%s,%s,%s,%s)', (sid, g['scheme_no'], g['name'], g['category'], g['basis']))
            gid = gid_by_no[g['scheme_no']] = c.lastrowid
            c.executemany('INSERT INTO dms_scheme_slab (scheme_group_id, slab_no, min_threshold, '
                          'discount_pct) VALUES (%s,%s,%s,%s)',
                          [(gid, s['slab_no'], s['min_threshold'], s['discount_pct']) for s in g['slabs']])
        # The file's codes are upper-cased keys; store the master's spelling where known.
        spelled = {}
        if cur:
            spelled = {r['sku_code'].upper(): r['sku_code'] for r in _q(
                'SELECT sku_code FROM dms_sku_master_item WHERE master_id = %s', (cur['id'],))}
        rows = [(sid, spelled.get(k, k), gid_by_no[sno]) for k, sno in parsed['sku_map'].items()]
        for k in range(0, len(rows), 1000):
            c.executemany('INSERT INTO dms_scheme_sku (scheme_id, sku_code, scheme_group_id) '
                          'VALUES (%s,%s,%s)', rows[k:k + 1000])
    return {'scheme': _scheme_out(_get_scheme(company_id, sid)), 'preview': preview}


def update_scheme(company_id, scheme_id, body):
    s = _get_scheme(company_id, scheme_id)
    name = (body.get('name') or s['name']).strip()[:255]
    mysql_manager.execute_query('UPDATE dms_scheme SET name = %s WHERE id = %s', (name, scheme_id), fetch=False)
    return _scheme_out(_get_scheme(company_id, scheme_id))


def scheme_groups(scheme_id):
    """{group_id: {id, scheme_no, name, category, basis, slabs}}"""
    groups = {r['id']: {'id': r['id'], 'scheme_no': r['scheme_no'], 'name': r['name'],
                        'category': r['category'], 'basis': r['basis'], 'slabs': []}
              for r in _q('SELECT * FROM dms_scheme_group WHERE scheme_id = %s', (scheme_id,))}
    if groups:
        for s in _q(f'SELECT * FROM dms_scheme_slab WHERE scheme_group_id IN '
                    f'({",".join(["%s"] * len(groups))}) ORDER BY slab_no', list(groups)):
            groups[s['scheme_group_id']]['slabs'].append(
                {'slab_no': s['slab_no'], 'min_threshold': float(s['min_threshold']),
                 'discount_pct': float(s['discount_pct'])})
    return groups


def effective_groups(scheme_id, codes):
    """{sku_code: group_id or None} — exactly as the scheme file maps them."""
    if not codes or not scheme_id:
        return {c: None for c in codes}
    ph = ','.join(['%s'] * len(codes))
    out = {c: None for c in codes}
    upper = {c.upper(): c for c in codes}
    for r in _q(f'SELECT sku_code, scheme_group_id FROM dms_scheme_sku WHERE scheme_id = %s '
                f'AND sku_code IN ({ph})', [scheme_id] + list(codes)):
        out[upper.get(r['sku_code'].upper(), r['sku_code'])] = r['scheme_group_id']
    return out


def scheme_detail(company_id, scheme_id):
    s = _get_scheme(company_id, scheme_id)
    groups = scheme_groups(scheme_id)
    counts = {r['scheme_group_id']: r['n'] for r in _q(
        'SELECT scheme_group_id, COUNT(*) n FROM dms_scheme_sku WHERE scheme_id = %s GROUP BY 1',
        (scheme_id,))}
    out = sorted(groups.values(), key=lambda g: pricing._scheme_sort_key(g['scheme_no']))
    for g in out:
        g['sku_count'] = counts.get(g['id'], 0)
    return {'scheme': _scheme_out(s), 'groups': out}


def mapping(company_id, scheme_id, view='all', q='', limit=300):
    """SKU -> group rows over the current SKU master's active SKUs, for the read-only
    mapping screen. view: all | unmapped
    """
    _get_scheme(company_id, scheme_id)
    cur = current_master(company_id)
    if not cur:
        return {'rows': [], 'total': 0, 'counts': {}, 'groups': []}
    groups = scheme_groups(scheme_id)
    items = _q('SELECT sku_code, description, category FROM dms_sku_master_item '
               'WHERE master_id = %s AND is_active = 1 ORDER BY sku_code', (cur['id'],))
    file_map = {r['sku_code'].upper(): r['scheme_group_id'] for r in _q(
        'SELECT sku_code, scheme_group_id FROM dms_scheme_sku WHERE scheme_id = %s', (scheme_id,))}
    rows = []
    counts = {'all': 0, 'unmapped': 0}
    term = (q or '').strip().upper()
    for it in items:
        k = it['sku_code'].upper()
        gid = file_map.get(k)
        counts['all'] += 1
        if gid is None:
            counts['unmapped'] += 1
        if view == 'unmapped' and gid is not None:
            continue
        if term and term not in k and term not in it['description'].upper():
            continue
        rows.append({
            'sku_code': it['sku_code'], 'description': it['description'], 'category': it['category'],
            'group_id': gid,
            'group': groups[gid]['scheme_no'] if gid in groups else None,
            'group_name': groups[gid]['name'] if gid in groups else None,
        })
    return {'rows': rows[:limit], 'total': len(rows), 'counts': counts}


# ======================================================================================
# Purchase orders
# ======================================================================================

def _get_po(po_id, company_ids):
    r = _one('SELECT * FROM pob_po WHERE id = %s', (po_id,))
    if not r or (company_ids is not None and r['company_id'] not in company_ids):
        raise NotFound('PO not found.')
    return r


def _draft(po):
    if po['status'] != 'draft':
        raise PoBuilderError('This PO is finalised — reopen it to make changes.')
    return po


def current_po(company_id, username):
    """The PO being built: the latest one (draft, or finalised and not yet replaced).
    With none at all, a fresh draft is started. There is no list of POs — older ones are
    kept but never browsed."""
    r = _one('SELECT id FROM pob_po WHERE company_id = %s ORDER BY id DESC LIMIT 1', (company_id,))
    return r['id'] if r else create_po(company_id, {}, username)


def _po_head(r):
    return {'id': r['id'], 'company_id': r['company_id'], 'po_no': r['po_no'],
            'po_date': _iso(r['po_date']), 'title': r['title'], 'remarks': r['remarks'],
            'status': r['status'], 'sku_master_id': r['sku_master_id'],
            'created_by': r['created_by'], 'created_on': _iso(r['created_on']),
            'updated_on': _iso(r['updated_on']), 'finalised_by': r['finalised_by'],
            'finalised_on': _iso(r['finalised_on'])}


def create_po(company_id, body, username):
    master = current_master(company_id)
    if not master:
        raise PoBuilderError('No SKU master has been uploaded yet.')
    po_date = _parse_date(body.get('po_date') or date.today().isoformat(), 'PO date')
    with mysql_manager.get_cursor() as c:
        c.execute('INSERT INTO pob_po (company_id, po_date, title, remarks, sku_master_id, created_by) '
                  'VALUES (%s,%s,%s,%s,%s,%s)',
                  (company_id, po_date, (body.get('title') or '')[:255],
                   (body.get('remarks') or '')[:255], master['id'], username))
        pid = c.lastrowid
        c.execute('UPDATE pob_po SET po_no = %s WHERE id = %s', (f'PO-{po_date:%y%m%d}-{pid}', pid))
    return pid


def update_po(po_id, company_ids, body):
    po = _draft(_get_po(po_id, company_ids))
    sets, params = [], []
    if 'po_date' in body:
        sets.append('po_date = %s')
        params.append(_parse_date(body['po_date'], 'PO date'))
    for k in ('title', 'remarks'):
        if k in body:
            sets.append(f'{k} = %s')
            params.append(str(body[k] or '')[:255])
    if sets:
        mysql_manager.execute_query(f'UPDATE pob_po SET {", ".join(sets)} WHERE id = %s',
                                    params + [po['id']], fetch=False)


def delete_po(po_id, company_ids):
    po = _draft(_get_po(po_id, company_ids))
    with mysql_manager.get_cursor() as c:
        c.execute('DELETE r FROM pob_import_row r JOIN pob_import i ON i.id = r.import_id WHERE i.po_id = %s',
                  (po['id'],))
        for t in ('pob_import', 'pob_po_line_source', 'pob_po_line'):
            c.execute(f'DELETE FROM {t} WHERE po_id = %s', (po['id'],))
        c.execute('DELETE FROM pob_po WHERE id = %s', (po['id'],))


def _add_qty(c, po, sku_code, qty, source_tag, username, import_id=None):
    """Add qty of one SKU to a PO — merging into its existing line — and record where it
    came from. `c` is an open cursor (the caller owns the transaction)."""
    c.execute('SELECT * FROM dms_sku_master_item WHERE master_id = %s AND sku_code = %s',
              (po['sku_master_id'], sku_code))
    it = c.fetchone()
    if not it:
        raise PoBuilderError(f'{sku_code} is not in the SKU master this PO uses.')
    c.execute('''INSERT INTO pob_po_line (po_id, sku_code, qty, dms_sku_id, description, category,
                                          finish, mrp, gst_pct, spu, uom)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                 ON DUPLICATE KEY UPDATE qty = qty + VALUES(qty)''',
              (po['id'], it['sku_code'], qty, it['dms_sku_id'], it['description'], it['category'],
               it['finish'], it['mrp'], it['gst_pct'], it['spu'], it['uom']))
    c.execute('SELECT id FROM pob_po_line WHERE po_id = %s AND sku_code = %s', (po['id'], it['sku_code']))
    line_id = c.fetchone()['id']
    c.execute('INSERT INTO pob_po_line_source (po_line_id, po_id, source_tag, import_id, qty, created_by) '
              'VALUES (%s,%s,%s,%s,%s,%s)', (line_id, po['id'], source_tag[:255], import_id, qty, username))
    return line_id


def _qty(v):
    """Qty as entered. Blank means 0 — a line can be added now and its qty filled in
    later; 0-qty lines stay on the PO but are left out of the export."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0.0
    try:
        q = float(v)
    except (TypeError, ValueError):
        raise PoBuilderError('Qty must be a number.')
    if q < 0:
        raise PoBuilderError('Qty cannot be negative.')
    return q


def add_line(po_id, company_ids, body, username):
    po = _draft(_get_po(po_id, company_ids))
    code = (body.get('sku_code') or '').strip()
    qty = _qty(body.get('qty'))
    with mysql_manager.get_cursor() as c:
        _add_qty(c, po, code, qty, (body.get('source_tag') or 'Search').strip() or 'Search', username)


def set_line_qty(po_id, company_ids, line_id, body, username):
    po = _draft(_get_po(po_id, company_ids))
    qty = _qty(body.get('qty'))
    with mysql_manager.get_cursor() as c:
        c.execute('SELECT * FROM pob_po_line WHERE id = %s AND po_id = %s FOR UPDATE', (line_id, po['id']))
        ln = c.fetchone()
        if not ln:
            raise NotFound('Line not found.')
        delta = qty - float(ln['qty'])
        if abs(delta) < 1e-9:
            return
        c.execute('UPDATE pob_po_line SET qty = %s WHERE id = %s', (qty, line_id))
        c.execute('INSERT INTO pob_po_line_source (po_line_id, po_id, source_tag, qty, created_by) '
                  'VALUES (%s,%s,%s,%s,%s)', (line_id, po['id'], 'Manual edit', delta, username))


def delete_line(po_id, company_ids, line_id):
    po = _draft(_get_po(po_id, company_ids))
    with mysql_manager.get_cursor() as c:
        c.execute('DELETE FROM pob_po_line_source WHERE po_line_id = %s AND po_id = %s', (line_id, po['id']))
        c.execute('DELETE FROM pob_po_line WHERE id = %s AND po_id = %s', (line_id, po['id']))


NO_GROUP = 'none'


def search(po_id, company_ids, q, group=None, limit=25):
    """Active SKUs of the PO's SKU master matching every word of `q` (code or
    description), optionally within one scheme group of the scheme in force (`group` = its
    id, or 'none' for SKUs in no group). With no `q` it browses — the dropdown opened
    without typing — in category, then code order."""
    po = _get_po(po_id, company_ids)
    limit = max(1, min(int(limit or 25), 200))
    words = [w for w in (q or '').strip().split() if w][:6]
    conds, params = ['master_id = %s', 'is_active = 1'], [po['sku_master_id']]
    if group:
        scheme = current_scheme(po['company_id'])
        if group == NO_GROUP:
            if scheme:
                conds.append('sku_code NOT IN (SELECT sku_code FROM dms_scheme_sku WHERE scheme_id = %s)')
                params.append(scheme['id'])
        else:
            conds.append('sku_code IN (SELECT sku_code FROM dms_scheme_sku WHERE scheme_group_id = %s)')
            params.append(int(group))
    for w in words:
        conds.append('(sku_code LIKE %s OR description LIKE %s)')
        params += [f'%{w}%', f'%{w}%']
    where = ' AND '.join(conds)
    if words:
        first = words[0]
        order = ('(sku_code = %s) DESC, (sku_code LIKE %s) DESC, (sku_code LIKE %s) DESC, '
                 'CHAR_LENGTH(sku_code), sku_code')
        order_params = [first, f'{first}%', f'%{first}%']
    else:
        order, order_params = 'category, sku_code', []
    total = _one(f'SELECT COUNT(*) n FROM dms_sku_master_item WHERE {where}', params)['n']
    rows = _q(f'''SELECT sku_code, dms_sku_id, description, category, finish, mrp, gst_pct, spu, uom, is_active
                  FROM dms_sku_master_item WHERE {where}
                  ORDER BY {order} LIMIT %s''', params + order_params + [limit])
    scheme = current_scheme(po['company_id'])
    eff = effective_groups(scheme['id'], [r['sku_code'] for r in rows]) if scheme else {}
    groups = scheme_groups(scheme['id']) if scheme else {}
    in_po = {r['sku_code']: float(r['qty']) for r in _q(
        'SELECT sku_code, qty FROM pob_po_line WHERE po_id = %s', (po['id'],))}
    out = []
    for r in rows:
        g = groups.get(eff.get(r['sku_code']))
        out.append({**_item_out(r), 'scheme_no': g['scheme_no'] if g else None,
                    'in_po_qty': in_po.get(r['sku_code'])})
    return {'results': out, 'total': total}


def group_options(po_id, company_ids):
    """The scheme groups of the scheme in force — scheme no, category, name and how many
    active SKUs of the PO's master each holds — plus the count of SKUs in no group."""
    po = _get_po(po_id, company_ids)
    scheme = current_scheme(po['company_id'])
    if not scheme:
        return {'groups': [], 'none_count': None}
    rows = _q('''SELECT g.id, g.scheme_no, g.name, g.category, COUNT(i.id) n
                 FROM dms_scheme_group g
                 JOIN dms_scheme_sku s ON s.scheme_group_id = g.id
                 JOIN dms_sku_master_item i ON i.master_id = %s AND i.sku_code = s.sku_code AND i.is_active = 1
                 WHERE g.scheme_id = %s GROUP BY g.id''', (po['sku_master_id'], scheme['id']))
    none = _one('SELECT COUNT(*) n FROM dms_sku_master_item WHERE master_id = %s AND is_active = 1 '
                'AND sku_code NOT IN (SELECT sku_code FROM dms_scheme_sku WHERE scheme_id = %s)',
                (po['sku_master_id'], scheme['id']))['n']
    groups = [{'id': r['id'], 'scheme_no': r['scheme_no'], 'name': r['name'], 'category': r['category'],
               'count': r['n']} for r in rows]
    groups.sort(key=lambda g: pricing._scheme_sort_key(g['scheme_no']))
    return {'groups': groups, 'none_count': none}


def po_view(po_id, company_ids):
    """Everything the PO page needs: header, lines with sources and prices, the scheme
    groups touched (with their slabs, so the page can re-price as qty is typed), the
    group summary, totals, and the imports with rows still waiting for a decision."""
    po = _get_po(po_id, company_ids)
    lines = _q('SELECT * FROM pob_po_line WHERE po_id = %s ORDER BY id', (po['id'],))
    sources = defaultdict(list)
    for s in _q('SELECT po_line_id, source_tag, import_id, qty, created_by, created_on '
                'FROM pob_po_line_source WHERE po_id = %s ORDER BY id', (po['id'],)):
        sources[s['po_line_id']].append({'source_tag': s['source_tag'], 'import_id': s['import_id'],
                                         'qty': float(s['qty']), 'created_by': s['created_by'],
                                         'created_on': _iso(s['created_on'])})
    master = _one('SELECT * FROM dms_sku_master WHERE id = %s', (po['sku_master_id'],))
    latest = current_master(po['company_id'])
    finalised = po['status'] == 'finalised'

    if finalised:
        settings = json.loads(po['frozen_settings'])
        frozen = json.loads(po['frozen_totals'])
        scheme = frozen.get('scheme')
        groups = {}
        price_lines = [{'id': l['id'], 'qty': l['qty'], 'mrp': l['mrp'], 'gst_pct': l['gst_pct'],
                        'scheme_group_id': None, 'fixed_scheme_pct': _f(l['scheme_pct']) or 0.0}
                       for l in lines]
        priced = pricing.price_po(price_lines, {}, settings)
        priced['groups'] = frozen['groups']
        priced['totals'] = frozen['totals']
    else:
        s = get_settings(po['company_id'])
        settings = {k: s[k] for k in ('dtr_discount_pct', 'std_discount_pct', 'show_case_helper')}
        sch = current_scheme(po['company_id'])
        scheme = _scheme_out(sch) if sch else None
        eff = effective_groups(sch['id'], [l['sku_code'] for l in lines]) if sch else {}
        all_groups = scheme_groups(sch['id']) if sch else {}
        groups = {gid: all_groups[gid] for gid in set(eff.values()) if gid in all_groups}
        price_lines = [{'id': l['id'], 'qty': l['qty'], 'mrp': l['mrp'], 'gst_pct': l['gst_pct'],
                        'scheme_group_id': eff.get(l['sku_code'])} for l in lines]
        priced = pricing.price_po(price_lines, groups, settings)

    out_lines = []
    for l, pl in zip(lines, price_lines):
        g = groups.get(pl['scheme_group_id'])
        out_lines.append({
            'id': l['id'], 'sku_code': l['sku_code'], 'qty': float(l['qty']),
            'dms_sku_id': l['dms_sku_id'], 'description': l['description'], 'category': l['category'],
            'finish': l['finish'], 'mrp': float(l['mrp']), 'gst_pct': float(l['gst_pct']),
            'spu': float(l['spu']), 'uom': l['uom'],
            'scheme_group_id': pl['scheme_group_id'],
            'scheme_no': l['scheme_no'] if finalised else (g['scheme_no'] if g else None),
            'scheme_name': l['scheme_name'] if finalised else (g['name'] if g else None),
            'sources': sources.get(l['id'], []),
            **priced['lines'][l['id']],
        })

    imports = []
    for i in _q('''SELECT i.*, SUM(r.applied = 0 AND r.match_status <> 'dismissed') AS pending,
                          SUM(r.applied = 0 AND r.resolved_sku_code IS NOT NULL
                              AND r.match_status NOT IN ('dismissed', 'bad_qty')) AS ready,
                          SUM(r.applied = 1) AS applied_rows
                   FROM pob_import i LEFT JOIN pob_import_row r ON r.import_id = i.id
                   WHERE i.po_id = %s AND i.status <> 'discarded' GROUP BY i.id ORDER BY i.id''', (po['id'],)):
        imports.append({'id': i['id'], 'source_tag': i['source_tag'], 'filename': i['filename'],
                        'status': i['status'], 'row_count': i['row_count'],
                        'pending': int(i['pending'] or 0), 'ready': int(i['ready'] or 0),
                        'applied_rows': int(i['applied_rows'] or 0),
                        'created_on': _iso(i['created_on'])})

    return {
        'po': {**_po_head(po), 'scheme': scheme,
               'master': _master_out(master) if master else None,
               'newer_master': _master_out(latest) if latest and master and latest['id'] != master['id'] else None},
        'settings': settings,
        'lines': out_lines,
        'groups': {str(k): v for k, v in groups.items()},
        'summary': {'groups': priced['groups'], 'totals': priced['totals']},
        'imports': imports,
        'unrecognised': [] if finalised else _unrecognised(po),
    }


def _unrecognised(po):
    """Imported rows that are not in the PO because no SKU could be settled on — a
    finish to pick, a suggestion to confirm, an unknown code, or a missing qty."""
    rows = _q('''SELECT r.*, i.source_tag FROM pob_import_row r JOIN pob_import i ON i.id = r.import_id
                 WHERE i.po_id = %s AND i.status <> 'discarded' AND r.applied = 0
                   AND r.match_status <> 'dismissed'
                   AND (r.resolved_sku_code IS NULL OR r.match_status = 'bad_qty')
                 ORDER BY i.id, r.row_no''', (po['id'],))
    codes = set()
    for r in rows:
        codes.update(json.loads(r['candidates'] or '[]'))
    items = _master_items(po['sku_master_id'], sorted(codes), active_only=True)
    reason = {'needs_choice': 'Several finishes — pick one', 'fuzzy': 'Not found — closest codes suggested',
              'unmatched': 'Not found in SKU master', 'bad_qty': 'Qty missing or not a number'}
    return [{'id': r['id'], 'import_id': r['import_id'], 'source_tag': r['source_tag'], 'row_no': r['row_no'],
             'raw_code': r['raw_code'], 'raw_finish': r['raw_finish'], 'raw_desc': r['raw_desc'],
             'qty': float(r['qty']), 'match_status': r['match_status'],
             'reason': reason.get(r['match_status'], r['match_note']),
             'candidates': [_item_out(items[c]) for c in json.loads(r['candidates'] or '[]') if c in items]}
            for r in rows]


def finalise(po_id, company_ids, username):
    po = _draft(_get_po(po_id, company_ids))
    view = po_view(po_id, company_ids)
    if not view['lines']:
        raise PoBuilderError('Add at least one line before finalising.')
    if view['unrecognised']:
        raise PoBuilderError(f"{len(view['unrecognised'])} unrecognised code(s) are listed on the PO — "
                             'add each under the right SKU or dismiss it first.')
    ready = sum(i['ready'] for i in view['imports'])
    if ready:
        raise PoBuilderError(f'{ready} matched row(s) from a bulk import were never added — open the '
                             'import and add or discard them first.')
    s = get_settings(po['company_id'])
    settings = {'dtr_discount_pct': s['dtr_discount_pct'], 'std_discount_pct': s['std_discount_pct'],
                'show_case_helper': s['show_case_helper']}
    frozen = {'scheme': view['po']['scheme'], 'groups': view['summary']['groups'],
              'totals': view['summary']['totals']}
    groups = {int(k): g for k, g in view['groups'].items()}
    with mysql_manager.get_cursor() as c:
        for ln in view['lines']:
            g = groups.get(ln['scheme_group_id'])
            c.execute('UPDATE pob_po_line SET scheme_no = %s, scheme_name = %s, scheme_basis = %s, '
                      'scheme_pct = %s WHERE id = %s',
                      (g['scheme_no'] if g else None, g['name'] if g else None,
                       g['basis'] if g else None, ln['scheme_pct'], ln['id']))
        c.execute("UPDATE pob_po SET status = 'finalised', frozen_settings = %s, frozen_totals = %s, "
                  "finalised_by = %s, finalised_on = NOW() WHERE id = %s",
                  (json.dumps(settings), json.dumps(frozen, default=str), username, po['id']))


def reopen(po_id, company_ids):
    po = _get_po(po_id, company_ids)
    if po['status'] != 'finalised':
        raise PoBuilderError('Only a finalised PO can be reopened.')
    with mysql_manager.get_cursor() as c:
        c.execute('UPDATE pob_po_line SET scheme_no = NULL, scheme_name = NULL, scheme_basis = NULL, '
                  'scheme_pct = NULL WHERE po_id = %s', (po['id'],))
        c.execute("UPDATE pob_po SET status = 'draft', frozen_settings = NULL, frozen_totals = NULL, "
                  "finalised_by = NULL, finalised_on = NULL WHERE id = %s", (po['id'],))


# ======================================================================================
# Bulk import
# ======================================================================================

def _matcher(po):
    items = _q('SELECT sku_code, is_active FROM dms_sku_master_item WHERE master_id = %s',
               (po['sku_master_id'],))
    return Matcher([r['sku_code'] for r in items if r['is_active']], _suffixes(po['company_id']),
                   [r['sku_code'] for r in items if not r['is_active']])


def create_import(po_id, company_ids, username, source_tag, data=None, filename=None, text=None, sheet=None):
    po = _draft(_get_po(po_id, company_ids))
    # No tag is asked for: the file name (without extension) identifies the import.
    tag = (source_tag or '').strip() or (filename.rsplit('.', 1)[0] if filename else 'Pasted list')
    parsed = parse_list(data=data, filename=filename, text=text, sheet=sheet)
    if not parsed['rows']:
        raise PoBuilderError('No rows with a SKU code were found.')
    m = _matcher(po)
    with mysql_manager.get_cursor() as c:
        c.execute('INSERT INTO pob_import (po_id, source_tag, filename, sheet_name, columns_used, '
                  'row_count, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                  (po['id'], tag[:255], (filename or 'Pasted list')[:255], parsed['sheet'][:128],
                   json.dumps(parsed['columns'])[:500], len(parsed['rows']), username))
        iid = c.lastrowid
        rows = []
        for r in parsed['rows']:
            res = m.match(r['code'], r['finish'])
            rows.append((iid, r['row_no'], r['code'], r['finish'], r['desc'], r['qty'], res['status'], res['note'][:255],
                         json.dumps(res['candidates']), res['sku_code']))
        c.executemany('INSERT INTO pob_import_row (import_id, row_no, raw_code, raw_finish, raw_desc, qty, '
                      'match_status, match_note, candidates, resolved_sku_code) '
                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', rows)
    out = import_view(po_id, company_ids, iid)
    out['sheets'] = parsed['sheets']
    return out


def _get_import(po, import_id):
    i = _one('SELECT * FROM pob_import WHERE id = %s AND po_id = %s', (import_id, po['id']))
    if not i:
        raise NotFound('Import not found.')
    return i


def import_view(po_id, company_ids, import_id):
    po = _get_po(po_id, company_ids)
    imp = _get_import(po, import_id)
    rows = _q('SELECT * FROM pob_import_row WHERE import_id = %s ORDER BY row_no, id', (imp['id'],))
    codes = set()
    for r in rows:
        codes.update(json.loads(r['candidates'] or '[]'))
        if r['resolved_sku_code']:
            codes.add(r['resolved_sku_code'])
    items = _master_items(po['sku_master_id'], sorted(codes))
    out_rows, counts = [], defaultdict(int)
    for r in rows:
        resolved = r['resolved_sku_code']
        bucket = ('applied' if r['applied'] else 'dismissed' if r['match_status'] == 'dismissed'
                  else 'unmatched' if r['match_status'] == 'bad_qty'
                  else 'matched' if resolved else
                  'needs_choice' if r['match_status'] in ('needs_choice', 'fuzzy') else 'unmatched')
        counts[bucket] += 1
        cands = [_item_out(items[c]) for c in json.loads(r['candidates'] or '[]') if c in items]
        out_rows.append({
            'id': r['id'], 'row_no': r['row_no'], 'raw_code': r['raw_code'], 'raw_finish': r['raw_finish'],
            'raw_desc': r['raw_desc'], 'qty': float(r['qty']), 'match_status': r['match_status'],
            'match_note': r['match_note'], 'bucket': bucket, 'applied': bool(r['applied']),
            'resolved': _item_out(items[resolved]) if resolved in items else None,
            'candidates': cands,
        })
    return {'import': {'id': imp['id'], 'source_tag': imp['source_tag'], 'filename': imp['filename'],
                       'sheet_name': imp['sheet_name'],
                       'columns_used': json.loads(imp['columns_used'] or '{}'),
                       'row_count': imp['row_count'], 'status': imp['status']},
            'rows': out_rows, 'counts': dict(counts)}


def resolve_row(po_id, company_ids, import_id, row_id, body, username):
    """In the import review: pick the SKU for a row, fix its qty, or dismiss it."""
    po = _draft(_get_po(po_id, company_ids))
    imp = _get_import(po, import_id)
    row = _one('SELECT * FROM pob_import_row WHERE id = %s AND import_id = %s', (row_id, imp['id']))
    if not row:
        raise NotFound('Row not found.')
    if row['applied']:
        raise PoBuilderError('This row is already in the PO — edit the line instead.')
    with mysql_manager.get_cursor() as c:
        if 'qty' in body:
            q = _qty(body['qty'])
            c.execute("UPDATE pob_import_row SET qty = %s, match_status = IF(match_status = 'bad_qty', "
                      "IF(resolved_sku_code IS NULL, 'unmatched', 'exact'), match_status) WHERE id = %s",
                      (q, row['id']))
        if body.get('dismiss'):
            c.execute("UPDATE pob_import_row SET match_status = 'dismissed', resolved_sku_code = NULL, "
                      "match_note = 'Dismissed' WHERE id = %s", (row['id'],))
            _refresh_import_status(c, imp['id'])
            return import_view(po_id, company_ids, import_id)
        if 'sku_code' in body:
            code = (body.get('sku_code') or '').strip()
            if code:
                item = _one('SELECT sku_code FROM dms_sku_master_item WHERE master_id = %s AND sku_code = %s '
                            'AND is_active = 1', (po['sku_master_id'], code))
                if not item:
                    raise PoBuilderError(f'{code} is not an active SKU in the master.')
                code = item['sku_code']
            c.execute("UPDATE pob_import_row SET resolved_sku_code = %s, match_note = %s, "
                      "match_status = IF(match_status IN ('dismissed', 'bad_qty'), 'unmatched', match_status) "
                      "WHERE id = %s", (code or None, 'Chosen by you' if code else 'Choice cleared', row['id']))
        _refresh_import_status(c, imp['id'])
    return import_view(po_id, company_ids, import_id)


def add_row(po_id, company_ids, import_id, row_id, body, username):
    """From the PO page's list of unrecognised codes: put one row into the PO under the
    SKU the user picked (and the qty they corrected, if any) in a single step."""
    po = _draft(_get_po(po_id, company_ids))
    imp = _get_import(po, import_id)
    code = (body.get('sku_code') or '').strip()
    if not code:
        raise PoBuilderError('Pick the SKU this code means.')
    with mysql_manager.get_cursor() as c:
        c.execute('SELECT * FROM pob_import_row WHERE id = %s AND import_id = %s FOR UPDATE', (row_id, imp['id']))
        row = c.fetchone()
        if not row:
            raise NotFound('Row not found.')
        if row['applied']:
            raise PoBuilderError('This row is already in the PO.')
        qty = _qty(body['qty']) if body.get('qty') not in (None, '') else float(row['qty'])
        c.execute('SELECT sku_code FROM dms_sku_master_item WHERE master_id = %s AND sku_code = %s AND is_active = 1',
                  (po['sku_master_id'], code))
        item = c.fetchone()
        if not item:
            raise PoBuilderError(f'{code} is not an active SKU in the master.')
        _add_qty(c, po, item['sku_code'], qty, imp['source_tag'], username, import_id=imp['id'])
        c.execute("UPDATE pob_import_row SET resolved_sku_code = %s, qty = %s, applied = 1, "
                  "match_note = 'Chosen by you' WHERE id = %s", (item['sku_code'], qty, row['id']))
        _refresh_import_status(c, imp['id'])


def _refresh_import_status(c, import_id):
    """An applied import stays 'partial' while any row is neither in the PO nor dismissed."""
    c.execute("SELECT i.status, SUM(r.applied = 0 AND r.match_status <> 'dismissed') open_rows "
              'FROM pob_import i JOIN pob_import_row r ON r.import_id = i.id WHERE i.id = %s GROUP BY i.id',
              (import_id,))
    r = c.fetchone()
    if not r or r['status'] in ('review', 'discarded'):
        return
    c.execute('UPDATE pob_import SET status = %s WHERE id = %s',
              ('partial' if r['open_rows'] else 'applied', import_id))


def apply_import(po_id, company_ids, import_id, username):
    """Put every decided, not-yet-applied row into the PO. Undecided rows stay behind
    (and keep the import open) — nothing is dropped."""
    po = _draft(_get_po(po_id, company_ids))
    imp = _get_import(po, import_id)
    if imp['status'] == 'discarded':
        raise PoBuilderError('This import was discarded.')
    with mysql_manager.get_cursor() as c:
        c.execute("SELECT id, resolved_sku_code, qty FROM pob_import_row WHERE import_id = %s AND applied = 0 "
                  "AND resolved_sku_code IS NOT NULL AND qty >= 0 AND match_status NOT IN ('dismissed', 'bad_qty') "
                  "FOR UPDATE", (imp['id'],))
        ready = c.fetchall()
        per_sku = defaultdict(float)
        for r in ready:
            per_sku[r['resolved_sku_code']] += float(r['qty'])
        for code, qty in per_sku.items():
            _add_qty(c, po, code, qty, imp['source_tag'], username, import_id=imp['id'])
        if ready:
            c.execute(f'UPDATE pob_import_row SET applied = 1 WHERE id IN ({",".join(["%s"] * len(ready))})',
                      [r['id'] for r in ready])
        c.execute("SELECT COUNT(*) n FROM pob_import_row WHERE import_id = %s AND applied = 0 "
                  "AND match_status <> 'dismissed'", (imp['id'],))
        left = c.fetchone()['n']
        c.execute('UPDATE pob_import SET status = %s, applied_on = NOW() WHERE id = %s',
                  ('partial' if left else 'applied', imp['id']))
    return {'applied_rows': len(ready), 'lines_touched': len(per_sku), 'left': left}


def discard_import(po_id, company_ids, import_id):
    po = _draft(_get_po(po_id, company_ids))
    imp = _get_import(po, import_id)
    if _one('SELECT 1 FROM pob_import_row WHERE import_id = %s AND applied = 1 LIMIT 1', (imp['id'],)):
        raise PoBuilderError('Some rows are already in the PO. Remove those lines first, or dismiss '
                             'the remaining rows instead.')
    mysql_manager.execute_query("UPDATE pob_import SET status = 'discarded' WHERE id = %s", (imp['id'],), fetch=False)
