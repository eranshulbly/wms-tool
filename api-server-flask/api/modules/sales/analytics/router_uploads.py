# -*- encoding: utf-8 -*-
"""
Monthly Data Upload API (/api/admin/monthly/*) — admin only.

The four recurring monthly feeds that drive sales analytics. For every feed the
admin first picks a period (year + month) in the UI, then uploads the file; the
selected period — not any per-row date — decides which period the data belongs to,
and each upload *replaces* that period's existing rows (never appends duplicates).

Feeds:
  sales          -> busy_sales_data          (Hero sales actuals from Busy)
  part-groups    -> part_groups              (part -> part-group + scheme mapping)
  qty-targets    -> dealer_part_group_target (dealer x part-group quantity targets)
  money-targets  -> dealer_money_target      (dealer rupee targets)

All four are Hero (company_id = 1); dealers are matched by name.
"""

import calendar
from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger
from api.shared.upload_utils import resolve_required_columns

logger = get_logger(__name__)

HERO = 1  # this data is Hero's; dealers are matched within this company

# feed -> the table it (re)loads, keyed for the status endpoint
_FEEDS = ('sales', 'part-groups', 'qty-targets', 'money-targets')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _admin_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _period(year, month):
    """(year, month) -> ('YYYY-MM-01', 'July', 'July 2026'). Raises ValueError if bad."""
    year, month = int(year), int(month)
    if not (2000 <= year <= 2100) or not (1 <= month <= 12):
        raise ValueError('Invalid year/month')
    return (f"{year:04d}-{month:02d}-01",
            calendar.month_name[month],
            f"{calendar.month_name[month]} {year}")


def _read_df(uploaded_file):
    """Parse the uploaded CSV/Excel into a str DataFrame with trimmed headers."""
    filename = uploaded_file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('csv', 'xls', 'xlsx'):
        raise ValueError('File must be CSV, XLS, or XLSX')
    raw = uploaded_file.read()
    df = pd.read_csv(BytesIO(raw), dtype=str) if ext == 'csv' \
        else pd.read_excel(BytesIO(raw), dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _dealer_map():
    """Hero dealer name -> dealer_id (exact name match, as the sales data uses)."""
    rows = mysql_manager.execute_query(
        "SELECT dealer_id, name FROM dealer WHERE company_id = %s", (HERO,)) or []
    return {(r['name'] or '').strip(): r['dealer_id'] for r in rows}


def _num(val):
    """Parse a possibly comma-grouped numeric cell; None/''/unparseable -> None.

    Never raises — targets treat None as a per-row error, so one bad cell doesn't
    abort (and roll back) the whole upload.
    """
    if val is None:
        return None
    s = str(val).replace(',', '').strip()
    if s == '' or s.lower() == 'nan':
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Per-feed loaders — each returns (inserted, skipped, errors, warnings)
# ---------------------------------------------------------------------------

def _load_sales(df):
    """Sales is NOT month-scoped: it loads by the dates in the file itself.

    Every date that appears in the file is replaced (its existing rows deleted,
    then the file's rows inserted); dates not present in the file are left alone.
    e.g. existing Jul 1-10 + upload Jul 8-13  ->  Jul 1-7 kept, 8-10 replaced,
    11-13 added. Returns the standard tuple plus a `covered` {min,max} range.
    """
    required = ['Date', 'Particulars', 'Item Details', 'Qty.', 'Amount']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)
    # optional columns
    for opt in ('Vch/Bill No', 'Unit', 'Price'):
        df, _ = resolve_required_columns(df, [opt])  # renames if present, ignore miss

    dealers = set(_dealer_map().keys())
    skipped, errors, unmatched = 0, [], 0
    rows = []  # parsed, valid rows awaiting insert

    # First pass: parse + validate every row (no DB writes yet).
    for idx, row in df.iterrows():
        row_num = idx + 2
        raw_date = row.get('Date')
        particulars = (row.get('Particulars') or '').strip()
        item = (row.get('Item Details') or '').strip()
        if not raw_date or not item:
            skipped += 1
            continue
        d = pd.to_datetime(raw_date, errors='coerce', dayfirst=False)
        if pd.isna(d):
            d = pd.to_datetime(raw_date, errors='coerce', dayfirst=True)
        if pd.isna(d):
            errors.append({'row': row_num, 'key': str(raw_date), 'reason': 'Unparseable date'})
            continue
        if particulars and particulars not in dealers:
            unmatched += 1
        rows.append({
            'row_num': row_num,
            'date': d.strftime('%Y-%m-%d'),
            'vch': (row.get('Vch/Bill No') or '').strip() or None,
            'particulars': particulars, 'item': item,
            'qty': _num(row.get('Qty.')) or 0,
            'unit': (row.get('Unit') or '').strip() or None,
            'price': _num(row.get('Price')),
            'amount': _num(row.get('Amount')) or 0,
        })

    dates = sorted({r['date'] for r in rows})
    inserted, replaced = 0, 0

    with mysql_manager.get_cursor() as cur:
        # Replace only the dates the file actually covers.
        if dates:
            placeholders = ','.join(['%s'] * len(dates))
            cur.execute(
                f"DELETE FROM busy_sales_data WHERE company_id=%s AND sale_date IN ({placeholders})",
                (HERO, *dates))
            replaced = cur.rowcount
        for r in rows:
            try:
                cur.execute(
                    """INSERT INTO busy_sales_data
                       (sale_date, voucher_no, particulars, item_code, quantity,
                        unit, price, amount, company_id, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r['date'], r['vch'], r['particulars'], r['item'], r['qty'],
                     r['unit'], r['price'], r['amount'], HERO, datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': r['row_num'], 'key': r['item'], 'reason': str(e)})

    warnings = []
    if len(dates) > 1:
        warnings.append(f'Replaced {len(dates)} date(s) from {dates[0]} to {dates[-1]}; '
                        f'other dates were left untouched.')
    if unmatched:
        warnings.append(f'{unmatched} row(s) have a "Particulars" that matches no dealer '
                        f'— they are stored but will not be attributed to an executive.')
    covered = {'min': dates[0], 'max': dates[-1]} if dates else None
    return replaced, inserted, skipped, errors, warnings, covered


def _load_part_groups(df, period_date, year, month, label):
    required = ['Part number', 'Part Group']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)
    for opt in ('Description', 'Scheme'):
        df, _ = resolve_required_columns(df, [opt])

    inserted, skipped, errors = 0, 0, []
    with mysql_manager.get_cursor() as cur:
        cur.execute("DELETE FROM part_groups WHERE period=%s", (period_date,))
        replaced = cur.rowcount
        for idx, row in df.iterrows():
            row_num = idx + 2
            part = (row.get('Part number') or '').strip()
            group = (row.get('Part Group') or '').strip()
            if not part:
                skipped += 1
                continue
            try:
                cur.execute(
                    """INSERT INTO part_groups
                       (part_number, description, part_group, scheme, month, period, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (part, (row.get('Description') or '').strip() or None,
                     group or None, (row.get('Scheme') or '').strip() or None,
                     label, period_date, datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': part, 'reason': str(e)})
    return replaced, inserted, skipped, errors, []


def _load_qty_targets(df, period_date, year, month, label):
    required = ['Dealer', 'Part Group', 'Target Qty']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)

    dmap = _dealer_map()
    # part_group -> scheme, taken from this period's mapping
    scheme_rows = mysql_manager.execute_query(
        "SELECT part_group, MAX(scheme) AS scheme FROM part_groups "
        "WHERE period=%s GROUP BY part_group", (period_date,)) or []
    scheme_of = {(r['part_group'] or '').strip(): r['scheme'] for r in scheme_rows}

    inserted, skipped, errors = 0, 0, []
    with mysql_manager.get_cursor() as cur:
        cur.execute("DELETE FROM dealer_part_group_target WHERE target_period=%s", (period_date,))
        replaced = cur.rowcount
        for idx, row in df.iterrows():
            row_num = idx + 2
            dealer = (row.get('Dealer') or '').strip()
            group = (row.get('Part Group') or '').strip()
            if not dealer and not group:
                skipped += 1
                continue
            dealer_id = dmap.get(dealer)
            if not dealer_id:
                errors.append({'row': row_num, 'key': dealer, 'reason': 'Unknown dealer'})
                continue
            if not group:
                errors.append({'row': row_num, 'key': dealer, 'reason': 'Missing part group'})
                continue
            qty = _num(row.get('Target Qty'))
            if qty is None:
                errors.append({'row': row_num, 'key': f'{dealer} / {group}',
                               'reason': 'Target Qty is not a number'})
                continue
            try:
                cur.execute(
                    """INSERT INTO dealer_part_group_target
                       (dealer_id, part_group, scheme, target_qty, month, target_period,
                        created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (dealer_id, group, scheme_of.get(group), qty, label, period_date,
                     datetime.utcnow(), datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': f'{dealer} / {group}', 'reason': str(e)})
    return replaced, inserted, skipped, errors, []


def _load_money_targets(df, period_date, year, month, label):
    required = ['Dealer', 'Money Target']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)

    dmap = _dealer_map()
    inserted, skipped, errors = 0, 0, []
    with mysql_manager.get_cursor() as cur:
        cur.execute("DELETE FROM dealer_money_target WHERE target_period=%s", (period_date,))
        replaced = cur.rowcount
        for idx, row in df.iterrows():
            row_num = idx + 2
            dealer = (row.get('Dealer') or '').strip()
            if not dealer:
                skipped += 1
                continue
            dealer_id = dmap.get(dealer)
            if not dealer_id:
                errors.append({'row': row_num, 'key': dealer, 'reason': 'Unknown dealer'})
                continue
            val = _num(row.get('Money Target'))
            if val is None:
                errors.append({'row': row_num, 'key': dealer,
                               'reason': 'Money Target is not a number'})
                continue
            try:
                cur.execute(
                    """INSERT INTO dealer_money_target
                       (dealer_id, target_period, value_target, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (dealer_id, period_date, val, datetime.utcnow(), datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': dealer, 'reason': str(e)})
    return replaced, inserted, skipped, errors, []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/monthly/status')
class MonthlyStatus(Resource):
    """What is already loaded, per feed, per period — powers the 'loaded periods' hints."""

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        try:
            def periods(sql):
                return {r['p']: r['c'] for r in (mysql_manager.execute_query(sql) or [])}
            # Sales isn't month-scoped — report its overall coverage (min/max date + total).
            cov = mysql_manager.execute_query(
                "SELECT MIN(sale_date) mn, MAX(sale_date) mx, COUNT(*) c "
                "FROM busy_sales_data WHERE company_id=1") or [{}]
            sales_coverage = {
                'min': str(cov[0]['mn']) if cov[0].get('mn') else None,
                'max': str(cov[0]['mx']) if cov[0].get('mx') else None,
                'total': cov[0].get('c') or 0,
            }
            return {
                'success': True,
                'sales_coverage': sales_coverage,
                'status': {
                    'sales': periods(
                        "SELECT DATE_FORMAT(sale_date,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM busy_sales_data WHERE company_id=1 GROUP BY p"),
                    'part-groups': periods(
                        "SELECT DATE_FORMAT(period,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM part_groups GROUP BY p"),
                    'qty-targets': periods(
                        "SELECT DATE_FORMAT(target_period,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM dealer_part_group_target GROUP BY p"),
                    'money-targets': periods(
                        "SELECT DATE_FORMAT(target_period,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM dealer_money_target GROUP BY p"),
                },
            }, 200
        except Exception as e:
            logger.exception("Error in /api/admin/monthly/status")
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/admin/monthly/<string:feed>')
class MonthlyUpload(Resource):
    """Replace one period's data for a monthly feed. Form: file, year, month."""

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, feed):
        if feed not in _FEEDS:
            return {'success': False, 'msg': f'Unknown feed "{feed}"'}, 404

        uploaded_file = request.files.get('file')
        if not uploaded_file:
            return {'success': False, 'msg': 'No file uploaded'}, 400
        try:
            df = _read_df(uploaded_file)
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 400

        # Sales loads by the dates inside the file — the month/year selector doesn't apply.
        if feed == 'sales':
            try:
                replaced, inserted, skipped, errors, warnings, covered = _load_sales(df)
            except ValueError as e:
                return {'success': False, 'msg': str(e)}, 400
            except Exception as e:
                logger.exception("Error loading sales feed")
                return {'success': False, 'msg': f'Load failed: {str(e)}'}, 400
            label = (f"{covered['min']} → {covered['max']}" if covered else 'no dated rows')
            return {
                'success': True, 'feed': feed, 'period': None, 'period_label': label,
                'covered': covered, 'replaced': replaced, 'inserted': inserted,
                'skipped': skipped, 'error_count': len(errors),
                'errors': errors[:200], 'warnings': warnings,
            }, 200

        # The other three feeds are month-scoped and need a period.
        try:
            year = request.form.get('year', type=int)
            month = request.form.get('month', type=int)
            if not year or not month:
                return {'success': False, 'msg': 'year and month are required'}, 400
            period_date, label, period_label = _period(year, month)
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 400

        try:
            if feed == 'part-groups':
                replaced, inserted, skipped, errors, warnings = _load_part_groups(
                    df, period_date, year, month, label)
            elif feed == 'qty-targets':
                replaced, inserted, skipped, errors, warnings = _load_qty_targets(
                    df, period_date, year, month, label)
            else:  # money-targets
                replaced, inserted, skipped, errors, warnings = _load_money_targets(
                    df, period_date, year, month, label)
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 400
        except Exception as e:
            logger.exception("Error loading monthly feed %s", feed)
            return {'success': False, 'msg': f'Load failed: {str(e)}'}, 400

        return {
            'success': True,
            'feed': feed,
            'period': period_date,
            'period_label': period_label,
            'replaced': replaced,
            'inserted': inserted,
            'skipped': skipped,
            'error_count': len(errors),
            'errors': errors[:200],
            'warnings': warnings,
        }, 200
