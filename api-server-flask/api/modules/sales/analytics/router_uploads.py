# -*- encoding: utf-8 -*-
"""
Monthly Data Upload API (/api/admin/monthly/*) — admin only.

The four recurring monthly feeds that drive sales analytics. For every feed the
admin first picks a period (year + month) in the UI, then uploads the file; the
selected period — not any per-row date — decides which period the data belongs to,
and each upload *replaces* that period's existing rows (never appends duplicates).

Feeds:
  sales         -> busy_sales_data          (Hero sales actuals from Busy)
  part-groups   -> part_groups              (part -> part-group + scheme mapping)
  qty-targets   -> dealer_part_group_target (dealer x part-group quantity targets)
  money-targets -> dealer_money_target      (dealer rupee targets)
  products      -> product                  (the product master itself)

Every feed is scoped to the uploading admin's company; dealers are matched by name
within that company.

Two feeds are NOT month-scoped and ignore the period selector:
  * sales — the dates inside the file decide what gets replaced.
  * products — the product master is standing reference data, not a monthly fact, so
    this merge-upserts rows keyed on product_string rather than replacing a period.
"""

import calendar
import difflib
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
_FEEDS = ('sales', 'part-groups', 'qty-targets', 'money-targets', 'products')

# Feeds that ignore the year/month selector (see module docstring).
_PERIODLESS_FEEDS = ('sales', 'products')


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
    """Active category name -> category_id, keeping the master's own spelling.

    The name is preserved as stored (not lower-cased) so a caller can tell an exact match
    apart from one it had to widen the search for, and report the assumption it made.
    """
    rows = mysql_manager.execute_query(
        "SELECT category_id, name FROM categories WHERE is_active = 1") or []
    return {(r['name'] or '').strip(): r['category_id'] for r in rows}


def _norm_cat(name):
    """Category name reduced to a comparison key: lower-cased, alphanumerics only."""
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def _resolve_category(name, cmap):
    """Category name from a file -> (category_id, matched_db_name) or (None, None).

    Source files spell the categories inconsistently — real uploads carry 'Accesories',
    'Publication' and 'Oils' against a master of 'Accessories', 'Publications' and 'Oil'.
    Erroring on those would fail thousands of otherwise-good rows, so the match widens in
    stages: exact -> case/punctuation-insensitive -> plural-insensitive -> a high-cutoff
    close match. Anything resolved past the exact stage is reported in the upload warnings,
    so an assumed mapping is always visible rather than silent.
    """
    raw = (name or '').strip()
    if not raw:
        return None, None

    key = _norm_cat(raw)
    by_key = {_norm_cat(n): (cid, n) for n, cid in cmap.items()}
    if key in by_key:
        return by_key[key]

    # 'Oils' vs 'Oil', 'Publication' vs 'Publications'.
    depluralised = {k.rstrip('s'): v for k, v in by_key.items()}
    if key.rstrip('s') in depluralised:
        return depluralised[key.rstrip('s')]

    # 'Accesories' vs 'Accessories' — a typo, not a plural. Cutoff is deliberately high
    # so unrelated names still fail rather than landing in the wrong category.
    close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.85)
    if close:
        return by_key[close[0]]
    return None, None


# Every writable column of the product master, as (file header, product column, value
# kind, limit, other accepted headers). Only the columns actually present in the uploaded
# file are written; everything else on an existing row is left exactly as it was.
#
# `limit` is the varchar length for text and (digits, decimal places) for a number — both
# are enforced per row, because one over-long or over-precise value would otherwise abort
# the whole executemany batch rather than failing just its own row.
#
# The aliases let one feed take either of the two shapes the master arrives in: the parts
# category mapping ('Part Number', 'Name', …) and the Hero part master dump ('Part No',
# 'Part Description', 'Net Weight', …).
_PRODUCT_FIELDS = (
    # header,             column,        kind,      limit,     aliases
    ('Name',              'name',        'text',    255,       ()),
    ('Description',       'description', 'text',    None,      ('Part Description',)),
    ('Product Category',  'subcategory', 'text',    100,       ()),
    ('Nickname',          'nickname',    'text',    200,       ()),
    ('UOM',               'uom',         'text',    20,        ('Unit of Measure',)),
    ('Size',              'size',        'text',    100,       ()),
    ('Weight',            'weight',      'decimal', (10, 3),   ('Net Weight',)),
    ('Price',             'price',       'decimal', (10, 2),   ()),
    ('Barcode',           'barcode',     'text',    100,       ()),
    ('HSN Code',          'hsn_code',    'text',    20,        ('HSN',)),
    ('is_active',         'is_active',   'bool',    None,      ()),
)

_PART_NUMBER_HEADERS = ('Part Number', 'Part No', 'Product String')

_TRUEISH = {'y', 'yes', '1', 'true', 't', 'active'}
_FALSEISH = {'n', 'no', '0', 'false', 'f', 'inactive'}


def _pkey(product_string):
    """Merge key for a part number, matching the collation of product.product_string."""
    return (product_string or '').strip().casefold()


def _norm_header(name):
    """Column header reduced to a comparison key: lower-cased, alphanumerics only."""
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def _find_header(df, names):
    """The df column matching any of `names`, ignoring case and punctuation.

    Deliberately an exact match on the normalised header rather than the substring match
    resolve_required_columns() does — 'Category' is a substring of 'Product Category', and
    letting those two collide would silently write a sub-category into category_id.
    """
    wanted = {_norm_header(n) for n in names}
    for col in df.columns:
        if _norm_header(col) in wanted:
            return col
    return None


def _coerce(val, kind, limit):
    """File cell -> stored value. Returns (value, error_message)."""
    if kind == 'bool':
        low = val.lower()
        if low in _TRUEISH:
            return 1, None
        if low in _FALSEISH:
            return 0, None
        return None, f'must be Y or N, got "{val}"'

    if kind == 'decimal':
        digits, places = limit
        try:
            num = round(float(val.replace(',', '')), places)
        except ValueError:
            return None, f'must be a number, got "{val}"'
        if abs(num) >= 10 ** (digits - places):
            return None, f'{val} is out of range (max {10 ** (digits - places) - 1})'
        return num, None

    if limit and len(val) > limit:
        return None, f'is longer than {limit} characters ({len(val)})'
    return val, None


def _load_products(df, company_id):
    """Merge-upsert the product master from a Part Number -> attributes file.

    Keyed on product_string: a part already in the master is UPDATED, a new one is
    INSERTED, and nothing is ever deleted. Re-uploading a corrected or extended file is
    therefore always safe — this is the merge_upsert behaviour every subsequent upload
    gets, in contrast to the month-scoped feeds that replace a whole period.

    Only the columns present in the file are written, and a blank cell means "no value
    supplied" rather than "clear this field" — a file carrying just Part Number and
    Category updates categories and leaves names, descriptions and subcategories intact.
    """
    key_col = _find_header(df, _PART_NUMBER_HEADERS)
    if not key_col:
        raise ValueError(
            'Missing required column: Part Number (also accepted: '
            + ', '.join(_PART_NUMBER_HEADERS[1:]) + '). Available: ' + ', '.join(df.columns))

    cmap = _category_map()
    category_col = _find_header(df, ('Category',))
    if category_col and not cmap:
        raise ValueError('No active categories exist yet — seed or create categories first.')

    # Which of the writable columns this particular file carries.
    present = [(_find_header(df, (header,) + aliases), column, kind, limit)
               for header, column, kind, limit, aliases in _PRODUCT_FIELDS]
    present = [p for p in present if p[0]]

    # Keyed the way MySQL keys the unique index, not the way Python compares strings:
    # product_string is utf8mb4_unicode_ci, so '…000S' and '…000s' are the SAME product.
    # Matching case-sensitively here would classify an existing part as new and the INSERT
    # would then die on a duplicate-key error partway through the batch.
    existing = {_pkey(r['product_string']): r for r in (mysql_manager.execute_query(
        "SELECT product_string, category_id FROM product WHERE product_string IS NOT NULL")
        or [])}

    # barcode carries its own UNIQUE index, so a barcode already spoken for by a different
    # part has to fail its own row here rather than abort the batch at write time.
    barcode_owner = {}
    if any(c == 'barcode' for _, c, _, _ in present):
        barcode_owner = {(r['barcode'] or '').casefold(): _pkey(r['product_string'])
                         for r in (mysql_manager.execute_query(
                             "SELECT barcode, product_string FROM product "
                             "WHERE barcode IS NOT NULL") or [])}

    inserts, updates, errors = {}, {}, []
    skipped, recategorised = 0, 0
    unknown_categories, fuzzy_categories = set(), {}

    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-based + header row
        product_string = _txt(row.get(key_col))
        if not product_string:
            skipped += 1
            continue
        key = _pkey(product_string)

        values, row_failed = {}, False
        for src, column, kind, limit in present:
            val = _txt(row.get(src))
            if not val:
                continue                      # blank == not supplied
            coerced, why = _coerce(val, kind, limit)
            if why:
                errors.append({'row': row_num, 'key': product_string,
                               'reason': f'{src} {why}'})
                row_failed = True
                break
            if column == 'barcode':
                owner = barcode_owner.get(coerced.casefold())
                if owner and owner != key:
                    errors.append({'row': row_num, 'key': product_string,
                                   'reason': f'Barcode "{coerced}" already belongs to {owner}'})
                    row_failed = True
                    break
                barcode_owner[coerced.casefold()] = key
            values[column] = coerced
        if row_failed:
            continue

        if category_col:
            category_name = _txt(row.get(category_col))
            if category_name:
                category_id, matched = _resolve_category(category_name, cmap)
                if not category_id:
                    unknown_categories.add(category_name)
                    errors.append({'row': row_num, 'key': product_string,
                                   'reason': f'Unknown category "{category_name}"'})
                    continue
                if matched != category_name:
                    fuzzy_categories[category_name] = matched
                values['category_id'] = category_id

        # Two rows for the same part — including two that differ only in case — are one
        # product, so they merge into a single write rather than colliding on the index.
        key = _pkey(product_string)
        prior = existing.get(key)
        if prior:
            # A later row for the same part wins, but its columns merge with the earlier one.
            updates.setdefault(key, {'product_string': prior['product_string']}).update(values)
            if values.get('category_id') and prior['category_id'] \
                    and prior['category_id'] != values['category_id']:
                recategorised += 1
        else:
            # name is NOT NULL — fall back to the description, then the part number itself.
            row_values = dict(values)
            row_values.setdefault('name', row_values.get('description') or product_string)
            inserts.setdefault(key, {'product_string': product_string}).update(row_values)

    with mysql_manager.get_cursor() as cur:
        now = datetime.utcnow()

        if inserts:
            cols = sorted({c for v in inserts.values() for c in v} - {'product_string'})
            placeholders = ', '.join(['%s'] * (len(cols) + 3))
            sql = (f"INSERT INTO product (product_string, company_id, {', '.join(cols)}, updated_at) "
                   f"VALUES ({placeholders})")
            cur.executemany(sql, [
                (v['product_string'], company_id, *[v.get(c) for c in cols], now)
                for v in inserts.values()
            ])

        # Group by the exact column set so each batch is one executemany.
        by_shape = {}
        for v in updates.values():
            cols = tuple(sorted(set(v) - {'product_string'}))
            if cols:
                by_shape.setdefault(cols, []).append(v)
        for cols, rows in by_shape.items():
            assignments = ', '.join(f"{c} = %s" for c in cols)
            sql = (f"UPDATE product SET {assignments}, updated_at = %s "
                   f"WHERE product_string = %s")
            cur.executemany(
                sql, [(*[v[c] for c in cols], now, v['product_string']) for v in rows])

    warnings = []
    if not present and not category_col:
        warnings.append(
            'The file carried only Part Number, so existing products were left unchanged. '
            'Recognised columns are: '
            + ', '.join(f[0] for f in _PRODUCT_FIELDS) + ', Category.')
    if fuzzy_categories:
        warnings.append(
            'These category names did not match exactly and were mapped to the closest '
            'existing category: '
            + ', '.join(f'"{k}" -> {v}' for k, v in sorted(fuzzy_categories.items())) + '.')
    if unknown_categories:
        warnings.append(
            'These categories do not exist and their rows were skipped: '
            + ', '.join(sorted(unknown_categories))
            + '. Valid categories: ' + ', '.join(sorted(cmap)) + '.')
    if recategorised:
        warnings.append(f'{recategorised} product(s) moved to a different category.')

    # Only parts that actually had a column to write count as updated — a row carrying
    # nothing but a Part Number touches nothing and shouldn't inflate the total.
    updated = sum(1 for v in updates.values() if set(v) - {'product_string'})
    return updated, len(inserts), skipped, errors, warnings, recategorised


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
            # The product master isn't period-scoped — report its size and how much of it
            # is categorised, plus the category list the upload will accept.
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
                    'products': {},
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

        # Products merge-upsert into the product master — no period involved.
        if feed == 'products':
            try:
                updated, inserted, skipped, errors, warnings, recategorised = _load_products(
                    df, _company(current_user))
            except ValueError as e:
                return {'success': False, 'msg': str(e)}, 400
            except Exception as e:
                logger.exception("Error loading products feed")
                return {'success': False, 'msg': f'Load failed: {str(e)}'}, 400
            return {
                'success': True, 'feed': feed, 'period': None,
                'period_label': 'product master',
                # 'replaced' is what the shared upload card renders; for a merge-upsert the
                # meaningful counterpart to "new" is how many existing rows were updated.
                'replaced': updated, 'updated': updated, 'inserted': inserted,
                'recategorised': recategorised, 'skipped': skipped,
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
