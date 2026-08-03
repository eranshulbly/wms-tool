# -*- encoding: utf-8 -*-
"""
Monthly Data Upload API (/api/admin/monthly/*) — admin only.

The four recurring monthly feeds that drive sales analytics. For every feed the
admin first picks a period (year + month) in the UI, then uploads the file; the
selected period — not any per-row date — decides which period the data belongs to,
and each upload *replaces* that period's existing rows (never appends duplicates).

Feeds:
  sales              -> busy_sales_data          (Hero sales actuals from Busy)
  part-groups        -> part_groups              (part -> part-group + scheme mapping)
  qty-targets        -> dealer_part_group_target (dealer x part-group quantity targets)
  money-targets      -> dealer_money_target      (dealer rupee targets)
  product-categories -> product.category_id      (sku -> category assignment)

Every feed is scoped to the uploading admin's company; dealers are matched by name
within that company.

Two feeds are NOT month-scoped and ignore the period selector:
  * sales — the dates inside the file decide what gets replaced.
  * product-categories — a product's category is a standing attribute, not a monthly
    fact, so this UPDATEs the product master in place rather than replacing a period.
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

# The Busy feed belongs to one company. It used to be hardcoded to Hero; it is now the
# uploading admin's own company, so a second tenant loads into its own rows rather than
# silently overwriting Hero's.
DEFAULT_COMPANY = 1


def _company(current_user):
    """The company this upload belongs to — the caller's own, not a request parameter."""
    from api.permissions import resolve_company_scope
    scope = resolve_company_scope(current_user)
    if not scope:            # None => unrestricted admin; [] => no grants
        return DEFAULT_COMPANY
    return scope[0]

# feed -> the table it (re)loads, keyed for the status endpoint
_FEEDS = ('sales', 'part-groups', 'qty-targets', 'money-targets', 'product-categories')

# Feeds that ignore the year/month selector (see module docstring).
_PERIODLESS_FEEDS = ('sales', 'product-categories')


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


def _dealer_map(company_id):
    """Dealer name -> dealer_id within one company (exact match, as the sales data uses)."""
    rows = mysql_manager.execute_query(
        "SELECT dealer_id, name FROM dealer WHERE company_id = %s", (company_id,)) or []
    return {(r['name'] or '').strip(): r['dealer_id'] for r in rows}


def _category_id_map():
    """Category name (lower-cased) -> category_id, for the target feeds.

    Both target feeds are keyed by category, so an unknown category name has to be a
    row error rather than a silent NULL — a NULL category would sit outside the
    replacement key and quietly survive every later upload.
    """
    rows = mysql_manager.execute_query(
        "SELECT category_id, name FROM categories WHERE is_active = 1") or []
    return {(r['name'] or '').strip().lower(): r['category_id'] for r in rows}


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

def _load_sales(df, company_id):
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

    dealers = set(_dealer_map(company_id).keys())
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
                (company_id, *dates))
            replaced = cur.rowcount
        for r in rows:
            try:
                cur.execute(
                    """INSERT INTO busy_sales_data
                       (sale_date, voucher_no, particulars, item_code, quantity,
                        unit, price, amount, company_id, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r['date'], r['vch'], r['particulars'], r['item'], r['qty'],
                     r['unit'], r['price'], r['amount'], company_id, datetime.utcnow()))
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


def _load_part_groups(df, period_date, year, month, label, company_id):
    required = ['Part number', 'Part Group']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)
    for opt in ('Description', 'Scheme'):
        df, _ = resolve_required_columns(df, [opt])

    inserted, skipped, errors = 0, 0, []
    with mysql_manager.get_cursor() as cur:
        cur.execute("DELETE FROM part_groups WHERE period=%s AND company_id=%s",
                    (period_date, company_id))
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
                       (part_number, description, part_group, scheme, month, period,
                        company_id, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (part, (row.get('Description') or '').strip() or None,
                     group or None, (row.get('Scheme') or '').strip() or None,
                     label, period_date, company_id, datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': part, 'reason': str(e)})
    return replaced, inserted, skipped, errors, []


def _load_qty_targets(df, period_date, year, month, label, company_id):
    """Quantity targets live at (category, scheme, part_group, dealer, period).

    Scheme stays derived from that period's part-group mapping rather than being asked
    for in the file — it is a property of the group, not of the target. Replacement is
    per category, so loading one category's targets leaves the others' alone.
    """
    required = ['Dealer', 'Category', 'Part Group', 'Target Qty']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)

    dmap = _dealer_map(company_id)
    cmap = _category_id_map()
    # part_group -> scheme, taken from this period's mapping
    scheme_rows = mysql_manager.execute_query(
        "SELECT part_group, MAX(scheme) AS scheme FROM part_groups "
        "WHERE period=%s AND company_id=%s GROUP BY part_group",
        (period_date, company_id)) or []
    # '' rather than NULL: scheme is part of the replacement key, and MySQL treats every
    # NULL in a UNIQUE index as distinct, so a NULL scheme would defeat the replacement.
    scheme_of = {(r['part_group'] or '').strip(): (r['scheme'] or '') for r in scheme_rows}

    inserted, skipped, errors = 0, 0, []
    rows = []  # parsed + validated, awaiting the write

    for idx, row in df.iterrows():
        row_num = idx + 2
        dealer = (row.get('Dealer') or '').strip()
        category = (row.get('Category') or '').strip()
        group = (row.get('Part Group') or '').strip()
        if not dealer and not group and not category:
            skipped += 1
            continue
        dealer_id = dmap.get(dealer)
        if not dealer_id:
            errors.append({'row': row_num, 'key': dealer, 'reason': 'Unknown dealer'})
            continue
        category_id = cmap.get(category.lower())
        if not category_id:
            errors.append({'row': row_num, 'key': f'{dealer} / {category}',
                           'reason': 'Unknown category' if category else 'Missing category'})
            continue
        if not group:
            errors.append({'row': row_num, 'key': dealer, 'reason': 'Missing part group'})
            continue
        qty = _num(row.get('Target Qty'))
        if qty is None:
            errors.append({'row': row_num, 'key': f'{dealer} / {group}',
                           'reason': 'Target Qty is not a number'})
            continue
        rows.append((row_num, dealer_id, category_id, group, scheme_of.get(group, ''), qty,
                     f'{dealer} / {category} / {group}'))

    replaced = 0
    with mysql_manager.get_cursor() as cur:
        covered = sorted({r[2] for r in rows})
        if covered:
            placeholders = ','.join(['%s'] * len(covered))
            cur.execute(
                f"DELETE FROM dealer_part_group_target "
                f"WHERE target_period=%s AND company_id=%s AND category_id IN ({placeholders})",
                (period_date, company_id, *covered))
            replaced = cur.rowcount
        for row_num, dealer_id, category_id, group, scheme, qty, key in rows:
            try:
                cur.execute(
                    """INSERT INTO dealer_part_group_target
                       (dealer_id, category_id, part_group, scheme, target_qty, month,
                        target_period, company_id, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (dealer_id, category_id, group, scheme, qty, label, period_date,
                     company_id, datetime.utcnow(), datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': key, 'reason': str(e)})

    warnings = []
    if covered:
        warnings.append(f'Replaced {len(covered)} categor{"y" if len(covered) == 1 else "ies"} '
                        f'for {label}; other categories were left untouched.')
    return replaced, inserted, skipped, errors, warnings


def _load_money_targets(df, period_date, year, month, label, company_id):
    """Money targets live at (category, dealer, period).

    Replacement is per category, not per period: a file covering one category must not
    wipe the others' targets for the same month. Only the categories present in the
    file are cleared, then reloaded.
    """
    required = ['Dealer', 'Category', 'Money Target']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)

    dmap = _dealer_map(company_id)
    cmap = _category_id_map()
    inserted, skipped, errors = 0, 0, []
    rows = []  # parsed + validated, awaiting the write

    for idx, row in df.iterrows():
        row_num = idx + 2
        dealer = (row.get('Dealer') or '').strip()
        category = (row.get('Category') or '').strip()
        if not dealer and not category:
            skipped += 1
            continue
        dealer_id = dmap.get(dealer)
        if not dealer_id:
            errors.append({'row': row_num, 'key': dealer, 'reason': 'Unknown dealer'})
            continue
        category_id = cmap.get(category.lower())
        if not category_id:
            errors.append({'row': row_num, 'key': f'{dealer} / {category}',
                           'reason': 'Unknown category' if category else 'Missing category'})
            continue
        val = _num(row.get('Money Target'))
        if val is None:
            errors.append({'row': row_num, 'key': f'{dealer} / {category}',
                           'reason': 'Money Target is not a number'})
            continue
        rows.append((row_num, dealer_id, category_id, val, f'{dealer} / {category}'))

    replaced = 0
    with mysql_manager.get_cursor() as cur:
        covered = sorted({r[2] for r in rows})
        if covered:
            placeholders = ','.join(['%s'] * len(covered))
            cur.execute(
                f"DELETE FROM dealer_money_target "
                f"WHERE target_period=%s AND company_id=%s AND category_id IN ({placeholders})",
                (period_date, company_id, *covered))
            replaced = cur.rowcount
        for row_num, dealer_id, category_id, val, key in rows:
            try:
                cur.execute(
                    """INSERT INTO dealer_money_target
                       (dealer_id, category_id, target_period, value_target, company_id,
                        created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (dealer_id, category_id, period_date, val, company_id,
                     datetime.utcnow(), datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': key, 'reason': str(e)})

    warnings = []
    if covered:
        warnings.append(f'Replaced {len(covered)} categor{"y" if len(covered) == 1 else "ies"} '
                        f'for {label}; other categories were left untouched.')
    return replaced, inserted, skipped, errors, warnings


def _txt(val):
    """Cell -> trimmed string, treating a blank cell as ''.

    pandas represents an empty cell as NaN — a float, and a *truthy* one — so the usual
    `(val or '').strip()` raises AttributeError on any column that has blanks. Needed here
    because a blank Category is meaningful: it clears the product's assignment.
    """
    if val is None:
        return ''
    try:
        if pd.isna(val):
            return ''
    except (TypeError, ValueError):
        pass  # array-like / unhashable — fall through to str()
    return str(val).strip()


def _category_map():
    """Active category name (lower-cased) -> category_id."""
    rows = mysql_manager.execute_query(
        "SELECT category_id, name FROM categories WHERE is_active = 1") or []
    return {(r['name'] or '').strip().lower(): r['category_id'] for r in rows}


def _load_product_categories(df):
    """Assign products to categories from a Product String -> Category file.

    Unlike the monthly feeds this UPDATEs the product master in place — a category is a
    standing attribute of a product, not a fact about one month. Nothing is deleted and no
    product is ever created: an unknown product string is reported as a row error, matching
    how the Product Nickname upload behaves.

    A blank Category clears the assignment, so a mis-categorised product can be corrected by
    re-uploading it with an empty cell.
    """
    required = ['Product String', 'Category']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)

    cmap = _category_map()
    if not cmap:
        raise ValueError('No active categories exist yet — seed or create categories first.')

    updated, cleared, replaced, skipped, errors = 0, 0, 0, 0, []
    unknown_categories = set()

    with mysql_manager.get_cursor() as cur:
        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-based + header row
            product_string = _txt(row.get('Product String'))
            category_name = _txt(row.get('Category'))

            if not product_string:
                skipped += 1
                continue

            cur.execute(
                "SELECT product_id, category_id FROM product WHERE product_string = %s",
                (product_string,))
            product = cur.fetchone()
            if not product:
                errors.append({'row': row_num, 'key': product_string,
                               'reason': 'Product not found'})
                continue

            if category_name:
                category_id = cmap.get(category_name.lower())
                if not category_id:
                    unknown_categories.add(category_name)
                    errors.append({'row': row_num, 'key': product_string,
                                   'reason': f'Unknown category "{category_name}"'})
                    continue
            else:
                category_id = None  # blank clears the assignment

            try:
                cur.execute(
                    "UPDATE product SET category_id = %s, updated_at = %s WHERE product_id = %s",
                    (category_id, datetime.utcnow(), product['product_id']))
                if category_id is None:
                    cleared += 1
                else:
                    updated += 1
                    # It already had a (different) category — the upload overwrote it.
                    if product['category_id'] and product['category_id'] != category_id:
                        replaced += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': product_string, 'reason': str(e)})

    warnings = []
    if unknown_categories:
        warnings.append(
            'These categories do not exist and were skipped: '
            + ', '.join(sorted(unknown_categories))
            + '. Valid categories: ' + ', '.join(sorted(c.title() for c in cmap)) + '.')
    if cleared:
        warnings.append(f'{cleared} product(s) had their category cleared (blank Category cell).')

    return replaced, updated + cleared, skipped, errors, warnings


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
            # Product categories aren't period-scoped — report how much of the product
            # master is assigned, plus the category list the upload will accept.
            pc = mysql_manager.execute_query(
                "SELECT COUNT(*) total, COUNT(category_id) mapped FROM product") or [{}]
            cats = mysql_manager.execute_query(
                "SELECT name FROM categories WHERE is_active = 1 ORDER BY name") or []
            cat_coverage = {
                'total': pc[0].get('total') or 0,
                'mapped': pc[0].get('mapped') or 0,
                'categories': [c['name'] for c in cats],
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
                    # Not period-scoped — coverage is reported separately below.
                    'product-categories': {},
                },
                'category_coverage': cat_coverage,
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

        # Product categories update the product master in place — no period involved.
        if feed == 'product-categories':
            try:
                replaced, applied, skipped, errors, warnings = _load_product_categories(df)
            except ValueError as e:
                return {'success': False, 'msg': str(e)}, 400
            except Exception as e:
                logger.exception("Error loading product-categories feed")
                return {'success': False, 'msg': f'Load failed: {str(e)}'}, 400
            return {
                'success': True, 'feed': feed, 'period': None,
                'period_label': 'product master', 'replaced': replaced,
                'inserted': applied, 'skipped': skipped,
                'error_count': len(errors), 'errors': errors[:200], 'warnings': warnings,
            }, 200

        # Sales loads by the dates inside the file — the month/year selector doesn't apply.
        if feed == 'sales':
            try:
                replaced, inserted, skipped, errors, warnings, covered = _load_sales(df, _company(current_user))
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
                    df, period_date, year, month, label, _company(current_user))
            elif feed == 'qty-targets':
                replaced, inserted, skipped, errors, warnings = _load_qty_targets(
                    df, period_date, year, month, label, _company(current_user))
            else:  # money-targets
                replaced, inserted, skipped, errors, warnings = _load_money_targets(
                    df, period_date, year, month, label, _company(current_user))
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
