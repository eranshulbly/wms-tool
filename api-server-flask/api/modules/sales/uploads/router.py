# -*- encoding: utf-8 -*-
"""
Data Upload API (/api/admin/monthly/*) — admin only.

Feeds:
  products      -> product                  (the product master itself)

The product master is standing reference data, not a monthly fact: this merge-upserts
rows keyed on product_string rather than replacing a period, so the year/month selector
does not apply. Every feed is scoped to the uploading admin's company.
"""

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
# _normalize_header is private-by-convention, but header DETECTION must normalise
# exactly as column RESOLUTION does — a second copy would drift and reintroduce the
# "Qty." vs "Qty" class of mismatch.
from api.shared.upload_utils import (resolve_required_columns, _normalize_header,
                                     parse_litres)

logger = get_logger(__name__)


class CompanyRequired(ValueError):
    """No single company could be resolved, so the upload has no unambiguous owner."""


def _company(current_user, requested=None):
    """The company this upload's rows belong to.

    The company is chosen by the operator and sent with the file; it is never read from
    the uploaded sheet. `resolve_company_scope` decides whether the caller may use the
    one they asked for and raises CompanyAccessDenied if not, so a scoped admin cannot
    load another tenant's data by posting someone else's id.

    With nothing selected we fall back to the caller's own scope, but only when that is
    unambiguous. An unrestricted admin has no single "own" company — this used to answer
    a hardcoded 1, so every such upload silently landed on company 1 regardless of which
    tenant the operator meant. Now it asks instead.
    """
    from api.permissions import resolve_company_scope
    scope = resolve_company_scope(current_user, requested)
    if scope is None:
        raise CompanyRequired('Select a company for this upload.')
    if not scope:
        raise CompanyRequired('You are not assigned to any company.')
    if len(scope) > 1:
        raise CompanyRequired('Select a company for this upload — you have access to several.')
    return scope[0]


def _requested_company():
    """The company id the operator picked, from the form (POST) or query (GET)."""
    return request.form.get('company_id', type=int) or request.args.get('company_id', type=int)

# feed -> the table it (re)loads, keyed for the status endpoint
_FEEDS = ('products',)


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

# Distinctive column names per feed, used to locate the real header row. Some accounting
# exports put the firm name and the reporting period in the first rows, so the actual
# header sits further down and pandas would otherwise take the title as the header
# ("Om Marketing, Unnamed: 1, Unnamed: 2, …").
_FEED_HEADER_HINTS = {
    'products':      ('Part Number', 'Part No', 'Product String', 'Category'),
}

# How far down to look. Deep enough for a title block, shallow enough that a headerless
# file fails on its own merits instead of matching some stray cell far into the data.
_HEADER_SCAN_ROWS = 25


def _looks_like_header(cells, hints):
    """Whether `cells` carries enough of `hints` to be the header row.

    Uses the same normalisation as resolve_required_columns ('Qty.' == 'Qty'), and
    requires two distinct hits so a data row holding one word like "Date" can't win.
    """
    norm = [_normalize_header(str(c)) for c in cells if c is not None and str(c).strip()]
    hit = {h for h in hints if any(_normalize_header(h) in c for c in norm)}
    return len(hit) >= min(2, len(hints))


def _read_df(uploaded_file, feed=None, raw_rows=False):
    """Parse the uploaded CSV/Excel into a str DataFrame with trimmed headers.

    When the first row isn't the header — a title block above it — the header row is
    located by `feed`'s hints and the file re-read from there. Without a feed (or with no
    hints matching) the first row is used, exactly as before.

    raw_rows returns the sheet with NO header row taken at all, positionally indexed. The
    unified target feed needs it: its header is TWO rows (level band, then names), and
    pandas taking either one as the columns loses the other — it de-duplicates the band's
    repeated "Scheme" into "Scheme.1", which throws away which column it belonged to.
    """
    filename = uploaded_file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('csv', 'xls', 'xlsx'):
        raise ValueError('File must be CSV, XLS, or XLSX')
    raw = uploaded_file.read()

    def _read(header):
        if ext == 'csv':
            return pd.read_csv(BytesIO(raw), dtype=str, header=header)
        return pd.read_excel(BytesIO(raw), dtype=str, header=header)

    if raw_rows:
        sheet = _read(None)
        return sheet.where(pd.notna(sheet), None)

    df = _read(0)
    df.columns = [str(c).strip() for c in df.columns]

    hints = _FEED_HEADER_HINTS.get(feed or '')
    if hints and not _looks_like_header(df.columns, hints):
        probe = _read(None).head(_HEADER_SCAN_ROWS)
        for i in range(len(probe)):
            if _looks_like_header(probe.iloc[i].tolist(), hints):
                df = _read(i)
                df.columns = [str(c).strip() for c in df.columns]
                logger.info("%s: header found on row %d, skipped %d title row(s)",
                            feed, i + 1, i)
                break

    # dtype=str still leaves empty cells as NaN (a float), and `nan or ''` is truthy —
    # every `(row.get(...) or '').strip()` below would blow up on a blank cell.
    return df.where(pd.notna(df), None)


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
    # 'Subcategory' is the product table's own column name, so a file exported straight
    # from the database round-trips instead of silently dropping this column.
    ('Product Category',  'subcategory', 'text',    100,       ('Subcategory',)),
    ('UOM',               'uom',         'text',    20,        ('Unit of Measure',)),
    ('Size',              'size',        'text',    100,       ()),
    ('Weight',            'weight',      'decimal', (10, 3),   ('Net Weight',)),
    ('Price',             'price',       'decimal', (10, 2),   ()),
    ('Barcode',           'barcode',     'text',    100,       ()),
    ('HSN Code',          'hsn_code',    'text',    20,        ('HSN',)),
    # A core column beside hsn_code, which determines it. Written here so the price row
    # can gross a landing price up to an inc-GST figure without joining back to product.
    ('GST %',             'gst_percent', 'decimal', (5, 2),    ('GST', 'GST Percent')),
    ('is_active',         'is_active',   'bool',    None,      ()),
)

_PART_NUMBER_HEADERS = ('Part Number', 'Part No', 'Product String')

_NAME_HEADERS = ('Name', 'Product Name', 'Product')

# Column added to the frame when the file has no part number; never a real header, so it
# cannot collide with one the supplier supplied.
_DERIVED_KEY = '__derived_product_string'


def _codes_for_names(names, company_id):
    """A product_string for each name: the existing product's, else a generated one.

    Matching is by name WITHIN the company, which is how a master without part numbers
    identifies a product and how inventory.ingestion resolves one. Reusing the same
    <PREFIX>-<slug> shape for new codes is what keeps the two routes on one product row.
    """
    from api.modules.inventory.ingestion.service import _slug

    # pandas reads a blank cell as NaN, which str() turns into the string 'nan' — left
    # alone that becomes a real product called CADI-NAN. Blank rows are blank.
    cleaned = []
    for n in names:
        text = '' if n is None else str(n).strip()
        cleaned.append('' if text.lower() in ('', 'nan', 'none', 'nat') else text)
    wanted = [n for n in cleaned if n]
    known = {}
    if wanted:
        unique = list(dict.fromkeys(wanted))
        placeholders = ','.join(['%s'] * len(unique))
        rows = mysql_manager.execute_query(
            f"""SELECT name, product_string FROM product
                 WHERE company_id = %s AND name IN ({placeholders})
                   AND product_string IS NOT NULL""",
            (company_id, *unique)) or []
        known = {r['name']: r['product_string'] for r in rows}

    prefix_rows = mysql_manager.execute_query(
        "SELECT name FROM company WHERE company_id = %s", (company_id,))
    prefix = (_slug(prefix_rows[0]['name'], 4) if prefix_rows else '') or 'PROD'

    # Codes minted in this file are not yet visible to the database, so they are tracked
    # here as well — two products whose names slug identically would otherwise collide.
    taken, out = set(known.values()), []
    for name in cleaned:
        if not name:
            out.append('')
            continue
        if name in known:
            out.append(known[name])
            continue
        base = f"{prefix}-{_slug(name)}"[:90]
        candidate, n = base, 1
        while candidate in taken or mysql_manager.execute_query(
                "SELECT 1 FROM product WHERE product_string = %s LIMIT 1", (candidate,)):
            n += 1
            candidate = f"{base[:90 - len(str(n)) - 1]}-{n}"
        taken.add(candidate)
        known[name] = candidate
        out.append(candidate)
    return out



# The category is resolved by NAME against the categories table — a category_id column in
# the file is deliberately ignored, since an id is only meaningful in the database that
# issued it. _find_header matches on the normalised header, so these reduce to 'category'
# and 'categoryname': both stay distinct from 'productcategory' (the subcategory) and from
# 'categoryid', neither of which may be mistaken for this column.
_CATEGORY_HEADERS = ('Category', 'Category Name')

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
        # A master without part numbers is not a broken file — some suppliers identify
        # products by name alone (Cadila's master is Name + Description). The name within
        # the company becomes the key, and a code is derived for anything new.
        #
        # The derived code deliberately matches inventory.ingestion's convention, so a
        # product created from a supplier PDF and the same product loaded from the master
        # land on ONE row instead of splitting that product's stock across two codes.
        name_col = _find_header(df, _NAME_HEADERS)
        if not name_col:
            raise ValueError(
                'Missing required column: Part Number (also accepted: '
                + ', '.join(_PART_NUMBER_HEADERS[1:]) + '), or Name for masters that '
                'identify products by name. Available: ' + ', '.join(df.columns))
        df = df.copy()
        df[_DERIVED_KEY] = _codes_for_names(df[name_col], company_id)
        key_col = _DERIVED_KEY

    cmap = _category_map()
    category_col = _find_header(df, _CATEGORY_HEADERS)
    if category_col and not cmap:
        raise ValueError('No active categories exist yet — seed or create categories first.')

    # A company whose products are packed and priced in a hierarchy (Cadila: tabs in a
    # strip, strips in a box, boxes in a case, priced per strip) carries extra columns
    # that belong on child rows rather than on `product`. A company with no profile is
    # unaffected — `pack_profile` stays None and every branch below is skipped, which is
    # what keeps the part-numbered masters behaving exactly as before.
    from api.modules.platform.catalog import product_pack
    pack_profile = product_pack.profile_for_company_id(company_id)
    pack_headers, pack_rows = {}, {}
    if pack_profile:
        for field, (header, aliases) in product_pack.CADILA_COLUMNS.items():
            found = _find_header(df, (header,) + aliases)
            if found:
                pack_headers[field] = found

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
    # Pack-size coverage, reported at the end: a product with no volume contributes 0 to
    # a litres target, so the gap has to be visible rather than just smaller numbers.
    litres_found, litres_missing = 0, set()

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

        # Volume of one selling unit, so an Oil target set in litres has something to
        # measure against — Busy bills every oil in Pcs. and the master carries no volume
        # of its own, so it is read out of the product name here and stored.
        #
        # Only when this file actually supplies a name or description: a file carrying
        # just Part Number and Category has nothing new to say about pack size. And only
        # when the parse SUCCEEDS — a failed parse leaves the stored value alone rather
        # than nulling it, so a volume corrected by hand survives the next upload of a
        # master whose name still doesn't carry one.
        if 'name' in values or 'description' in values:
            litres = parse_litres(values.get('name'), values.get('description'))
            if litres is not None:
                values['litres_per_unit'] = litres
                litres_found += 1
            else:
                litres_missing.add(product_string)

        # Two rows for the same part — including two that differ only in case — are one
        # product, so they merge into a single write rather than colliding on the index.
        key = _pkey(product_string)
        prior = existing.get(key)

        # Pack and price columns, validated here so a row that cannot describe a NEW
        # product is reported with its row number and the product is never created
        # half-defined. An UPDATE stays partial: correcting one price must not require
        # restating the whole pack.
        if pack_profile:
            pack_values = product_pack.read_row(row, pack_headers)
            absent = product_pack.missing_required(pack_profile, pack_values, prior is None)
            if absent:
                labels = ', '.join(product_pack.CADILA_COLUMNS[f][0] for f in absent)
                errors.append({'row': row_num, 'key': product_string,
                               'reason': f'New product is missing required column(s): {labels}'})
                continue
            # A later row for the same part wins on the fields it supplies.
            pack_rows.setdefault(key, {}).update(
                {k: v for k, v in pack_values.items() if v is not None})

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

    # Ladders, prices and attributes go in AFTER the product write, because they are child
    # rows and a brand-new product has no id until its INSERT has run.
    pack_summary = None
    if pack_profile and pack_rows:
        wanted = list(pack_rows)
        ids = {}
        for i in range(0, len(wanted), 500):
            chunk = wanted[i:i + 500]
            ph = ','.join(['%s'] * len(chunk))
            for r in (mysql_manager.execute_query(
                    f"SELECT product_id, product_string FROM product "
                    f"WHERE product_string IN ({ph})", tuple(chunk)) or []):
                ids[_pkey(r['product_string'])] = r['product_id']
        resolved = {ids[k]: (v, k not in existing)
                    for k, v in pack_rows.items() if k in ids}
        # GST lives on `product` (it follows the HSN, not the price list), but the price
        # row carries its own copy so a landing price can be grossed up without a join.
        # Read it back rather than threading it through: the product write above may have
        # just set it, and this is the one place both are known.
        gst_by_product = {}
        if resolved:
            ph = ','.join(['%s'] * len(resolved))
            gst_by_product = {r['product_id']: r['gst_percent'] for r in (
                mysql_manager.execute_query(
                    f"SELECT product_id, gst_percent FROM product "
                    f"WHERE product_id IN ({ph})", tuple(resolved)) or [])}
        pack_summary = product_pack.apply_rows(
            pack_profile, company_id, resolved, gst_by_product)

    warnings = []
    if pack_summary:
        warnings.append(
            f"Packaging written for {pack_summary['ladders']} product(s), "
            f"{pack_summary['prices']} price row(s) and "
            f"{pack_summary['attributes']} attribute value(s). Prices are dated today — "
            f"orders already placed keep the rate they were priced at.")
    if pack_profile and not pack_headers:
        warnings.append(
            'This company expects packaging and price columns and the file carried none, '
            'so only the product names were updated. Expected: '
            + ', '.join(h for h, _ in product_pack.CADILA_COLUMNS.values()) + '.')
    if not present and not category_col and not pack_headers:
        warnings.append(
            'The file carried only Part Number, so existing products were left unchanged. '
            'Recognised columns are: '
            + ', '.join(f[0] for f in _PRODUCT_FIELDS)
            + ', ' + ' / '.join(_CATEGORY_HEADERS) + '.')
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
    if litres_missing:
        listed = ', '.join(sorted(litres_missing)[:10])
        if len(litres_missing) > 10:
            listed += f'; and {len(litres_missing) - 10} more'
        warnings.append(
            f'Pack size was read from the product name for {litres_found} product(s) but '
            f'not for {len(litres_missing)}. Those count as 0 towards any target set in '
            f'litres. Most are items with no volume (wax, cloths, brushes) and can be '
            f'ignored; a real oil in this list needs its size added to its name: {listed}.')

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
        from api.permissions import CompanyAccessDenied

        # Same company the upload will use, so "already loaded" always describes the
        # rows this operator is about to replace. Before this, the counts were read
        # from company 1 (or unfiltered) no matter who asked, so a second tenant saw
        # Hero's periods marked as loaded and its own as empty.
        try:
            company_id = _company(current_user, _requested_company())
        except CompanyRequired as e:
            # Nothing selected yet — the page renders before the operator picks a
            # company, so this is an empty state, not a failure.
            return {
                'success': True, 'company_id': None, 'needs_company': True,
                'msg': str(e), 'sales_coverage': None,
                'status': {f: {} for f in _FEEDS},
                'category_coverage': None,
            }, 200
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        try:
            # The product master isn't period-scoped — report its size and how much of it
            # is categorised, plus the category list the upload will accept.
            pc = mysql_manager.execute_query(
                "SELECT COUNT(*) total, COUNT(category_id) mapped "
                "FROM product WHERE company_id=%s", (company_id,)) or [{}]
            cats = mysql_manager.execute_query(
                "SELECT name FROM categories WHERE is_active = 1 ORDER BY name") or []
            cat_coverage = {
                'total': pc[0].get('total') or 0,
                'mapped': pc[0].get('mapped') or 0,
                'categories': [c['name'] for c in cats],
            }
            return {
                'success': True,
                'company_id': company_id,
                'sales_coverage': None,
                'status': {
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
        from api.permissions import CompanyAccessDenied

        if feed not in _FEEDS:
            return {'success': False, 'msg': f'Unknown feed "{feed}"'}, 404

        # Resolved once, before the file is read: every feed below writes company-scoped
        # rows, so there is no point parsing a spreadsheet we have no owner for.
        try:
            company_id = _company(current_user, _requested_company())
        except CompanyRequired as e:
            return {'success': False, 'msg': str(e)}, 422
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        uploaded_file = request.files.get('file')
        if not uploaded_file:
            return {'success': False, 'msg': 'No file uploaded'}, 400
        try:
            df = _read_df(uploaded_file, feed)
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 400

        # Products merge-upsert into the product master — no period involved. This is the
        # only monthly feed (see _FEEDS); the feed guard above rejects anything else.
        try:
            updated, inserted, skipped, errors, warnings, recategorised = _load_products(
                df, company_id)
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
