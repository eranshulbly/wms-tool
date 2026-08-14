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
  targets       -> dealer_target (EVERY dealer target, any level, any unit)
  products      -> product                  (the product master itself)

`targets` is a single wide sheet carrying a dealer's category, scheme and part-group
targets together, in rupees or units, which is how they are actually decided. It replaced
two narrow per-shape feeds (`qty-targets`, `money-targets`), which have been removed —
rows they wrote are still readable, since all three always wrote this one table.

Every feed is scoped to the uploading admin's company; dealers are matched by name
within that company.

Two feeds are NOT month-scoped and ignore the period selector:
  * sales — the dates inside the file decide what gets replaced.
  * products — the product master is standing reference data, not a monthly fact, so
    this merge-upserts rows keyed on product_string rather than replacing a period.
"""

import calendar
import difflib
import re
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
_FEEDS = ('sales', 'part-groups', 'targets', 'products')

# Feeds that ignore the year/month selector (see module docstring).
_PERIODLESS_FEEDS = ('sales', 'products')

# The unified target feed has a two-row header and is read positionally, so the
# header-hint machinery below does not apply to it.
_RAW_HEADER_FEEDS = ('targets',)


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


# Distinctive column names per feed, used to locate the real header row. Busy and most
# accounting exports put the firm name and the reporting period in the first rows, so the
# actual header sits further down and pandas would otherwise take the title as the header
# ("Om Marketing, Unnamed: 1, Unnamed: 2, …").
_FEED_HEADER_HINTS = {
    'sales':         ('Date', 'Particulars', 'Item Details', 'Qty.', 'Amount'),
    'part-groups':   ('Part number', 'Part Group'),
    'products':      ('Part Number', 'Part No', 'Product String', 'Category'),
}

# How far down to look. Deep enough for a title block, shallow enough that a headerless
# file fails on its own merits instead of matching some stray cell far into the data.
_HEADER_SCAN_ROWS = 25

# Rows per executemany. Big enough that 150k lines finish well inside the request
# timeout, small enough to stay under MySQL's max_allowed_packet and to keep the
# retry-row-by-row fallback cheap when a chunk fails.
_INSERT_CHUNK = 1000


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


def _norm_dealer(name):
    """Normalise a dealer name for matching: trim, collapse inner runs of whitespace,
    casefold.

    The database join these uploads feed (`busy_sales_data.particulars = dealer.name`)
    runs under utf8mb4_unicode_ci, which is case-INsensitive. Matching here used to be a
    plain Python dict lookup, which is case-sensitive — so "ABC Motors" in a file was
    reported as an unknown dealer even though it joins perfectly in the analytics. Lining
    the two up removes that false mismatch, and stops the create-missing path below from
    minting a duplicate of a dealer that already exists under different capitalisation.
    """
    return ' '.join((name or '').split()).casefold()


def _dealer_map(company_id):
    """Normalised dealer name -> dealer_id within one company.

    Keys are normalised by `_norm_dealer`, so every lookup must normalise too.
    """
    rows = mysql_manager.execute_query(
        "SELECT dealer_id, name FROM dealer WHERE company_id = %s", (company_id,)) or []
    return {_norm_dealer(r['name']): r['dealer_id'] for r in rows}


def _create_dealers(names, company_id):
    """Create dealers for `names` (original spelling preserved) under one company.

    Returns {normalised name: dealer_id} for what was created. Only `name` and `status`
    are NOT NULL on dealer, and `dealer_code` is UNIQUE but nullable — MySQL permits many
    NULLs in a unique index — so a name and a company are enough to make a valid row.

    `sales_executive_id` is deliberately left NULL: nothing in a Busy export says who
    owns the dealer, and guessing would silently attribute someone's sales to the wrong
    executive. Until it is set, these dealers match by name but attribute to no one, which
    is why the upload reports exactly which ones it created.
    """
    created = {}
    if not names:
        return created
    with mysql_manager.get_cursor() as cur:
        for name in names:
            try:
                cur.execute(
                    "INSERT INTO dealer (name, company_id, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (name, company_id, datetime.utcnow(), datetime.utcnow()))
                created[_norm_dealer(name)] = cur.lastrowid
            except Exception:
                logger.exception("could not auto-create dealer %r", name)
    return created


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

def _dates_look_transposed(values):
    """Whether this file's datetime-typed Date cells were mangled by Excel.

    Decided ONCE per file, not per cell, because the per-cell test is unsound.

    The mangling being corrected: Excel opens a Busy export, reads a text 'DD-MM-YYYY'
    as its own locale's MM-DD, and stores a real date with day and month swapped. That
    misread can only succeed when DD <= 12 — a day of 29 would mean month 29, which is
    invalid, so such a cell stays TEXT.

    So a datetime-typed cell whose day is > 12 is proof the column was never misread:
    under the mangling theory that cell could not exist as a date at all. One such cell
    settles it for the whole column, since Excel applies its locale uniformly.

    Judging cell-by-cell instead meant every date with day <= 12 got transposed even in a
    perfectly good export — turning 2 Apr into 4 Feb, and pushing sales into the future.
    """
    saw_datetime = False
    for v in values:
        if v is None:
            continue
        iso = pd.to_datetime(str(v).strip(), format='%Y-%m-%d %H:%M:%S', errors='coerce')
        if pd.isna(iso):
            continue
        saw_datetime = True
        if iso.day > 12:
            return False
    # All datetime cells have day <= 12: consistent with a misread, so correct it.
    return saw_datetime


def _parse_sale_date(raw, transposed=True):
    """Busy writes sale dates as DD-MM-YYYY. Returns (Timestamp|None, was_unswapped).

    Two shapes reach us, because the Date column is only *sometimes* text:
      * text 'DD-MM-YYYY'  — parse day-first, as Busy wrote it.
      * a real datetime    — either a genuine date, or one Excel transposed on open.
        `transposed` comes from `_dates_look_transposed`, which decides that for the
        whole file; when False the cell is taken exactly as it stands.
    The swap is reported so a caller can warn rather than silently move a sale's date.
    """
    if raw is None:
        return None, False
    s = str(raw).strip()
    if not s:
        return None, False

    # A real (Excel-coerced) datetime cell arrives stringified as ISO with a time part.
    iso = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    if not pd.isna(iso):
        if transposed and iso.day <= 12:   # undo Excel's MM-DD misread
            return pd.Timestamp(year=iso.year, month=iso.day, day=iso.month), True
        return iso.normalize(), False

    for fmt in ('%d-%m-%Y', '%Y-%m-%d'):   # Busy's own format, then plain ISO
        d = pd.to_datetime(s, format=fmt, errors='coerce')
        if not pd.isna(d):
            return d, False
    # Anything else (other separators, month names): day-first, as Busy writes dates.
    d = pd.to_datetime(s, errors='coerce', dayfirst=True)
    return (None, False) if pd.isna(d) else (d, False)


# Busy closes its export with a grand-total line, and prints sub-totals mid-report. On
# those lines Date, Vch No and Particulars are all blank — but the ffill in _load_sales
# inherits them from the voucher above, so a total arrives looking like an ordinary line
# item and loads as one: an `item_code` of 'Total' carrying the whole report's amount and
# quantity, attributed to whichever dealer happened to be last. That single row roughly
# doubles every SUM over the feed.
_SUMMARY_ITEM_LABELS = frozenset({
    'total', 'grandtotal', 'subtotal', 'openingbalance', 'closingbalance',
})


def _is_summary_item(item):
    """True when an 'Item Details' cell is one of Busy's total lines, not a real part.

    Matched as a whole label against a closed set, deliberately not as a prefix — real
    part descriptions can legitimately begin with a listed word, and a prefix rule would
    silently drop genuine sales.
    """
    return ''.join(ch for ch in item.lower() if ch.isalnum()) in _SUMMARY_ITEM_LABELS


def _load_sales(df, company_id, create_missing_dealers=False):
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

    # Busy prints a voucher's Date / Vch No / Particulars on its first line only; the
    # rest of that voucher's line items leave them blank and inherit from above. Without
    # this the date check below drops every line but the first of each voucher.
    for col in ('Date', 'Vch/Bill No', 'Particulars'):
        if col in df.columns:
            df[col] = df[col].ffill()

    # Decided once for the whole file — see _dates_look_transposed.
    transposed = _dates_look_transposed(df['Date']) if 'Date' in df.columns else True

    dealers = set(_dealer_map(company_id).keys())
    skipped, errors, unmatched = 0, [], 0
    summary_rows = 0   # Busy total lines dropped — reported, never silently swallowed
    # Original spelling of each unmatched name, keyed by its normalised form, so a name
    # appearing on 200 voucher lines is reported (and created) exactly once.
    unknown_names = {}
    # Excel-mangled dates, reported per *date* rather than per row: one bad voucher cell
    # forward-fills onto all of that voucher's lines, so a row count wildly overstates it.
    swaps = {}   # raw cell -> [corrected Timestamp, rows affected]
    rows = []    # parsed, valid rows awaiting insert

    # First pass: parse + validate every row (no DB writes yet).
    for idx, row in df.iterrows():
        row_num = idx + 2
        raw_date = row.get('Date')
        particulars = (row.get('Particulars') or '').strip()
        item = (row.get('Item Details') or '').strip()
        if not raw_date or not item:
            skipped += 1
            continue
        # Checked before the date parse: the total line's own Date cell is blank and only
        # looks valid because of the ffill, so parsing it would just launder a bad row.
        if _is_summary_item(item):
            summary_rows += 1
            continue
        d, swapped = _parse_sale_date(raw_date, transposed)
        if d is None:
            errors.append({'row': row_num, 'key': str(raw_date), 'reason': 'Unparseable date'})
            continue
        if swapped:
            swaps.setdefault(str(raw_date), [d, 0])[1] += 1
        if particulars and _norm_dealer(particulars) not in dealers:
            unmatched += 1
            unknown_names.setdefault(_norm_dealer(particulars), particulars)
        rows.append({
            'row_num': row_num,
            'date': d.strftime('%Y-%m-%d'),
            'vch': (row.get('Vch/Bill No') or '').strip() or None,
            'particulars': particulars, 'item': item,
            'qty': _num(row.get('Qty.')) or 0,
            'unit': (row.get('Unit') or '').strip() or None,
            # `or 0` like quantity/amount below: Price is documented optional and the
            # column is NOT NULL DEFAULT 0. A column default does not apply when the
            # INSERT passes an explicit NULL, so a blank Price used to fail the row with
            # "Column 'price' cannot be null" while the upload still reported success.
            'price': _num(row.get('Price')) or 0,
            'amount': _num(row.get('Amount')) or 0,
        })

    dates = sorted({r['date'] for r in rows})
    inserted, replaced = 0, 0

    # Opt-in: turn the names this file mentions but the master doesn't have into dealers.
    # Done before the sales insert so a later failure can't leave dealers created for rows
    # that never landed.
    created_dealers = []
    if create_missing_dealers and unknown_names:
        made = _create_dealers(list(unknown_names.values()), company_id)
        created_dealers = sorted(unknown_names[k] for k in made)
        dealers.update(made.keys())
        unmatched = sum(1 for r in rows
                        if r['particulars'] and _norm_dealer(r['particulars']) not in dealers)

    with mysql_manager.get_cursor() as cur:
        # Replace only the dates the file actually covers.
        if dates:
            placeholders = ','.join(['%s'] * len(dates))
            cur.execute(
                f"DELETE FROM busy_sales_data WHERE company_id=%s AND sale_date IN ({placeholders})",
                (company_id, *dates))
            replaced = cur.rowcount
        # Batched: a year of Busy data is ~150k lines, and one round-trip to RDS per row
        # takes far longer than the 120s gunicorn/nginx timeout, so the upload died
        # mid-insert. executemany sends a chunk per round-trip instead.
        sql = ("""INSERT INTO busy_sales_data
                  (sale_date, voucher_no, particulars, item_code, quantity,
                   unit, price, amount, company_id, created_at)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""")
        now = datetime.utcnow()

        def params(r):
            return (r['date'], r['vch'], r['particulars'], r['item'], r['qty'],
                    r['unit'], r['price'], r['amount'], company_id, now)

        for start in range(0, len(rows), _INSERT_CHUNK):
            chunk = rows[start:start + _INSERT_CHUNK]
            try:
                cur.executemany(sql, [params(r) for r in chunk])
                inserted += len(chunk)
            except Exception:
                # One bad row fails its whole chunk, so retry the chunk row by row to
                # attribute the error to the actual line — the per-row error report is
                # what makes a 150k-line upload diagnosable.
                for r in chunk:
                    try:
                        cur.execute(sql, params(r))
                        inserted += 1
                    except Exception as e:
                        errors.append({'row': r['row_num'], 'key': r['item'],
                                       'reason': str(e)})

    warnings = []
    if summary_rows:
        warnings.append(
            f'Ignored {summary_rows} total line(s) from the report footer. Loading one '
            f'would add the whole report\'s amount and quantity as a single line item, '
            f'roughly doubling every sales figure.')
    if created_dealers:
        shown = ', '.join(created_dealers[:10])
        if len(created_dealers) > 10:
            shown += f'; and {len(created_dealers) - 10} more'
        warnings.append(
            f'Created {len(created_dealers)} dealer(s) from names in this file: {shown}. '
            f'They have no sales executive assigned yet, so their sales still will not be '
            f'attributed until you set one.')
    if unmatched:
        # Names, not just a count — a bare number gives no way to tell a real missing
        # dealer from an accounting ledger line like "Cash" or a typo.
        names = sorted(unknown_names[k] for k in unknown_names
                       if k not in dealers)
        listed = ', '.join(names[:10]) + (f'; and {len(names) - 10} more'
                                          if len(names) > 10 else '')
        warnings.append(f'{unmatched} row(s) have a "Particulars" that matches no dealer '
                        f'— they are stored but will not be attributed to an executive. '
                        f'Unmatched: {listed}')
    if swaps:
        # Name each date that moved so the correction can be eyeballed; keep the list short.
        shown = sorted(swaps.items(), key=lambda kv: kv[1][0])[:5]
        pairs = '; '.join(f"{pd.to_datetime(raw):%d %b %Y} → {fixed:%d %b %Y}"
                          for raw, (fixed, _n) in shown)
        if len(swaps) > len(shown):
            pairs += f'; and {len(swaps) - len(shown)} more'
        n_rows = sum(n for _f, n in swaps.values())
        warnings.append(
            f'Corrected {len(swaps)} date{"" if len(swaps) == 1 else "s"} mangled by Excel: '
            f'{pairs} ({n_rows} row{"" if n_rows == 1 else "s"}). '
            f'Save the Date column as Text to avoid this.')
    covered = {'min': dates[0], 'max': dates[-1]} if dates else None
    return replaced, inserted, skipped, errors, warnings, covered, created_dealers


def _load_part_groups(df, period_date, year, month, label, company_id, scheme):
    """Load one scheme's part-group mapping for one period.

    The scheme is chosen in the UI, not read from the file: a single upload is one
    basket, and taking it from a column let a file quietly write into schemes the
    uploader never intended.

    The file supplies Part number and, optionally, Part Group. A row with no part group
    takes the SCHEME NAME as its group — that is the case where a basket is not broken
    into groups, and it keeps every row groupable rather than leaving nulls that fall out
    of every roll-up.

    Replacement is scoped to (period, scheme): loading Basket 1 leaves Basket 2 and PG
    for that month untouched.
    """
    required = ['Part number']
    df, err = resolve_required_columns(df, required)
    if err:
        raise ValueError(err)
    # Part Group is optional; Sr. No. / Description / Scheme columns are ignored if
    # present, so an older file still loads.
    df, _ = resolve_required_columns(df, ['Part Group'])

    scheme = (scheme or '').strip()
    if not scheme:
        raise ValueError('A scheme must be selected for this upload')

    def _cell(row, name):
        value = row.get(name)
        return '' if value is None or pd.isna(value) else str(value).strip()

    # A part maps to exactly one row per period, and uq_period_part enforces that — so a
    # file naming the same part on several rows fails every row after the first with a
    # duplicate-key error the operator cannot act on. Decide the winner here instead: the
    # later row is the correction, so keep the last occurrence of each part and report the
    # ones it supersedes as a warning. Without this the file's own repeats look identical
    # to a collision with data already in the table.
    last_row_for = {}
    for idx, row in df.iterrows():
        part = _cell(row, 'Part number')
        if part:
            last_row_for[part] = idx
    superseded = []

    inserted, skipped, errors, moved = 0, 0, [], 0
    with mysql_manager.get_cursor() as cur:
        cur.execute(
            "DELETE FROM part_groups WHERE time_period=%s AND company_id=%s AND scheme=%s",
            (period_date, company_id, scheme))
        replaced = cur.rowcount

        # Which parts already sit in a DIFFERENT scheme this period. uq_period_part means
        # a part belongs to exactly one scheme per month, so loading it here moves it —
        # counted and reported rather than done silently.
        existing = {r['part_number']: r['scheme'] for r in (mysql_manager.execute_query(
            "SELECT part_number, scheme FROM part_groups WHERE time_period=%s AND company_id=%s",
            (period_date, company_id)) or [])}

        for idx, row in df.iterrows():
            row_num = idx + 2
            part = _cell(row, 'Part number')
            group = _cell(row, 'Part Group')
            if not part:
                skipped += 1
                continue
            if last_row_for[part] != idx:
                superseded.append((row_num, part))
                skipped += 1
                continue
            if part in existing:
                moved += 1
            try:
                cur.execute(
                    """INSERT INTO part_groups
                       (part_number, part_group, scheme, time_period,
                        company_id, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         part_group = VALUES(part_group), scheme = VALUES(scheme)""",
                    (part, group or scheme, scheme,
                     period_date, company_id, datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': part, 'reason': str(e)})

    warnings = [f'Replaced the "{scheme}" mapping for {label}; other schemes in this '
                f'period were left untouched.']
    if moved:
        warnings.append(f'{moved} part(s) were already mapped to another scheme this '
                        f'period and have been moved into "{scheme}".')
    if superseded:
        listed = '; '.join(f'row {r} ({p})' for r, p in superseded[:10])
        if len(superseded) > 10:
            listed += f'; and {len(superseded) - 10} more'
        n_parts = len({p for _r, p in superseded})
        warnings.append(
            f'{len(superseded)} row(s) repeat a part number listed again later in the file '
            f'({n_parts} part{"" if n_parts == 1 else "s"} affected). The last row for each '
            f'part was loaded and these earlier ones were ignored: {listed}')
    return replaced, inserted, skipped, errors, warnings


# ---------------------------------------------------------------------------
# The unified target feed
#
# One wide sheet carrying every target a dealer has, at every level, in either unit. Two
# header rows, because a column needs to declare two things a name alone cannot:
#
#   row 1  the LEVEL, and for a part-group column the scheme it belongs to
#          "Category" | "Scheme" | "Part Group : PG"
#   row 2  the NAME, and the unit in brackets
#          "Parts (Rs)" | "Basket 1 (Rs)" | "Break Shoe (Qty)" | "Oil (Litres)"
#
# The level band is not decoration. "Basket 2" is both a scheme AND a part group in the
# mapping — _load_part_groups writes `part_group = group or scheme` for a basket nobody
# broke into groups, so the two are the same string — and no amount of looking the name up
# can say which was meant. The band says. Likewise the scheme after the colon: the part
# group is "Brake Shoe", the scheme is "PG", and gluing them into one header ("PG Brake
# Shoe") would put the loader back to stripping prefixes and guessing where one ends.
# ---------------------------------------------------------------------------

# Level word (normalised) -> the target_level stored. The sheet is written by hand, so
# both the singular and the run-together spellings are accepted.
_LEVEL_WORDS = {
    'category': 'category',
    'categories': 'category',
    'scheme': 'scheme',
    'schemes': 'scheme',
    'partgroup': 'part_group',
    'partgroups': 'part_group',
    'group': 'part_group',
}

# Unit in brackets -> (target_type, target_uom). 'Rs' measures against GST-inclusive
# rupees billed; 'Qty' against units billed; 'Litres' against units billed scaled by
# product.litres_per_unit. Every one of these is spelled several ways in practice.
_UNIT_WORDS = {
    'rs': ('value', ''), 'rs.': ('value', ''), '₹': ('value', ''), 'inr': ('value', ''),
    'rupees': ('value', ''), 'value': ('value', ''), 'amount': ('value', ''),
    'qty': ('qty', ''), 'qty.': ('qty', ''), 'quantity': ('qty', ''), 'nos': ('qty', ''),
    'nos.': ('qty', ''), 'units': ('qty', ''), 'pcs': ('qty', ''), 'pcs.': ('qty', ''),
    'litres': ('qty', 'litres'), 'liters': ('qty', 'litres'), 'litre': ('qty', 'litres'),
    'liter': ('qty', 'litres'), 'ltr': ('qty', 'litres'), 'ltrs': ('qty', 'litres'),
    'l': ('qty', 'litres'),
}


def _parse_level_band(text):
    """"Part Group : PG" -> ('part_group', 'PG'). Returns (level, scheme) or (None, None).

    The scheme after the colon is only meaningful for a part-group column; anywhere else
    it is ignored rather than rejected, so an operator who labels a scheme column
    "Scheme : Basket 1" gets what they meant instead of an error.
    """
    raw = _txt(text)
    if not raw:
        return None, None
    head, _, tail = raw.partition(':')
    level = _LEVEL_WORDS.get(_normalize_header(head))
    return level, tail.strip()


def _parse_target_header(text):
    """"Break Shoe (Qty)" -> ('Break Shoe', 'qty', ''). Raises ValueError if unreadable.

    The unit is REQUIRED. A column with no bracket cannot be loaded on a guess: the same
    number under "Basket 1" means ₹3,750 or 3,750 units depending on nothing the sheet
    says, and picking one silently is how a rupee target ends up in a quantity total.
    """
    raw = _txt(text)
    if not raw:
        raise ValueError('blank column header')
    m = re.match(r'^(.*?)\s*\(([^)]*)\)\s*$', raw)
    if not m:
        raise ValueError(f'"{raw}" has no unit — expected a name followed by (Rs), '
                         f'(Qty) or (Litres)')
    name, unit = m.group(1).strip(), m.group(2).strip().lower()
    if not name:
        raise ValueError(f'"{raw}" has a unit but no name')
    if unit not in _UNIT_WORDS:
        raise ValueError(f'"{raw}" — unknown unit "{m.group(2).strip()}". '
                         f'Use (Rs), (Qty) or (Litres)')
    target_type, uom = _UNIT_WORDS[unit]
    return name, target_type, uom


def _period_target_masters(period_date, company_id):
    """What the period's part-group mapping says a target may be set on.

    Returns (schemes, groups, scheme_categories, group_categories) where the two category
    maps give the set of category_ids each scheme / (scheme, part_group) covers. A target
    row carries exactly one category_id, so a name covering more than one category cannot
    be loaded — the caller reports that rather than picking one.
    """
    rows = mysql_manager.execute_query(
        """SELECT pg.scheme, pg.part_group, p.category_id
             FROM part_groups pg
             LEFT JOIN product p ON p.product_string = pg.part_number
                                AND p.company_id = %s
            WHERE pg.time_period = %s AND pg.company_id = %s""",
        (company_id, period_date, company_id)) or []

    schemes, groups = {}, {}
    scheme_cats, group_cats = {}, {}
    for r in rows:
        scheme = (r['scheme'] or '').strip()
        group = (r['part_group'] or '').strip()
        if scheme:
            schemes[scheme.lower()] = scheme
            if r['category_id']:
                scheme_cats.setdefault(scheme.lower(), set()).add(r['category_id'])
        if group:
            groups[(scheme.lower(), group.lower())] = (scheme, group)
            if r['category_id']:
                group_cats.setdefault((scheme.lower(), group.lower()), set()).add(r['category_id'])
    return schemes, groups, scheme_cats, group_cats


def _suggest(name, candidates):
    """' Did you mean "Brake Shoe"?' for a near-miss, or '' when nothing is close.

    A misspelled column is the expensive failure here: it would create a target that
    matches no sales at all and show every dealer at 0% against it. Naming the closest
    real value turns a silent wrong number into a one-word fix.
    """
    close = difflib.get_close_matches(name.lower(), [c.lower() for c in candidates], 1, 0.7)
    if not close:
        return ''
    actual = next((c for c in candidates if c.lower() == close[0]), close[0])
    return f' Did you mean "{actual}"?'


def _resolve_target_columns(band_row, name_row, period_date, company_id):
    """Header pair -> one resolved spec per target column. Returns (columns, errors).

    Each spec is a dict the row loop can write straight out. Resolution is strict: a name
    must match the period's own masters exactly once, or the column is rejected and no
    target is written for it. Nothing here creates a category, scheme or part group —
    inventing one would produce a target that no sale can ever roll up to.
    """
    cmap = _category_id_map()
    schemes, groups, scheme_cats, group_cats = _period_target_masters(period_date, company_id)
    columns, errors = [], []

    for idx in range(1, len(name_row)):
        band, name_cell = band_row[idx] if idx < len(band_row) else '', name_row[idx]
        if not _txt(name_cell) and not _txt(band):
            continue  # trailing empty column — Excel adds them freely

        col_label = f'column {idx + 1}'
        level, band_scheme = _parse_level_band(band)
        if not level:
            errors.append({'row': 1, 'key': col_label,
                           'reason': f'"{_txt(band)}" is not a level — row 1 must say '
                                     f'Category, Scheme or "Part Group : <scheme>"'})
            continue
        try:
            name, target_type, uom = _parse_target_header(name_cell)
        except ValueError as e:
            errors.append({'row': 2, 'key': col_label, 'reason': str(e)})
            continue

        spec = {'index': idx, 'level': level, 'type': target_type, 'uom': uom,
                'label': f'{name} ({"Rs" if target_type == "value" else uom or "Qty"})'}

        if level == 'category':
            category_id = cmap.get(name.lower())
            if not category_id:
                errors.append({'row': 2, 'key': name,
                               'reason': 'Unknown category.' + _suggest(name, cmap.keys())})
                continue
            spec.update(category_id=category_id, scheme='', part_group='')

        elif level == 'scheme':
            key = name.lower()
            if key not in schemes:
                errors.append({'row': 2, 'key': name,
                               'reason': f'No scheme "{name}" in the part-group mapping for '
                                         f'this period.' + _suggest(name, schemes.values())})
                continue
            cats = scheme_cats.get(key, set())
            if len(cats) != 1:
                errors.append({'row': 2, 'key': name, 'reason': _multi_category_reason(
                    f'Scheme "{schemes[key]}"', cats)})
                continue
            spec.update(category_id=next(iter(cats)), scheme=schemes[key], part_group='')

        else:  # part_group
            if not band_scheme:
                errors.append({'row': 1, 'key': name,
                               'reason': 'A part-group column must name its scheme — '
                                         'write "Part Group : PG" in row 1.'})
                continue
            key = (band_scheme.lower(), name.lower())
            if key not in groups:
                in_scheme = [g for (s, _), (_, g) in groups.items() if s == band_scheme.lower()]
                if not in_scheme:
                    reason = (f'No scheme "{band_scheme}" in the part-group mapping for this '
                              f'period.' + _suggest(band_scheme, schemes.values()))
                else:
                    reason = (f'No part group "{name}" under scheme "{band_scheme}" this '
                              f'period.' + _suggest(name, in_scheme))
                errors.append({'row': 2, 'key': name, 'reason': reason})
                continue
            cats = group_cats.get(key, set())
            if len(cats) != 1:
                errors.append({'row': 2, 'key': name, 'reason': _multi_category_reason(
                    f'Part group "{groups[key][1]}"', cats)})
                continue
            scheme, group = groups[key]
            spec.update(category_id=next(iter(cats)), scheme=scheme, part_group=group)

        columns.append(spec)

    return columns, errors


def _multi_category_reason(what, cats):
    """Why a scheme / part group can't carry a target: its parts span categories, or none."""
    if not cats:
        return (f'{what} has no categorised products this period, so its target has no '
                f'category to sit under. Load the product master first.')
    names = mysql_manager.execute_query(
        f"SELECT name FROM categories WHERE category_id IN ({_in_list(cats)})",
        tuple(cats)) or []
    listed = ', '.join(sorted(r['name'] for r in names))
    return (f'{what} spans several categories ({listed}), so a single target on it is '
            f'ambiguous. Split the column, or map its parts to one category.')


def _in_list(values):
    return ','.join(['%s'] * len(values))


def _load_targets(raw, period_date, year, month, label, company_id):
    """Load the wide target sheet: every level, every unit, one file.

    Replacement is per SLOT, not per period or per category. The slots are exactly the
    columns the file declares — (level, scheme, part group, category, type) — so a sheet
    covering Parts and the baskets leaves an Oil target from a different file alone, and
    re-uploading a corrected sheet replaces precisely what it covers.
    """
    band_idx = _find_band_row(raw)
    if band_idx is None:
        raise ValueError(
            'Could not find the level row. Row 1 must label each target column with '
            'Category, Scheme or "Part Group : <scheme>", and row 2 must carry the names.')
    if band_idx + 1 >= len(raw):
        raise ValueError('The level row has no header row beneath it.')

    band_row = [_txt(v) for v in raw.iloc[band_idx].tolist()]
    name_row = [_txt(v) for v in raw.iloc[band_idx + 1].tolist()]
    body = raw.iloc[band_idx + 2:]

    columns, errors = _resolve_target_columns(band_row, name_row, period_date, company_id)
    if not columns:
        raise ValueError(
            'No target column could be resolved. '
            + (errors[0]['reason'] if errors else 'The sheet has no target columns.'))

    dmap = _dealer_map(company_id)
    inserted, skipped = 0, 0
    rows = []  # parsed + validated, awaiting the write

    for offset, (_, row) in enumerate(body.iterrows()):
        row_num = band_idx + 3 + offset          # 1-based sheet row, for the error report
        cells = row.tolist()
        dealer = _txt(cells[0]) if cells else ''
        if not dealer:
            skipped += 1
            continue
        dealer_id = dmap.get(_norm_dealer(dealer))
        if not dealer_id:
            errors.append({'row': row_num, 'key': dealer, 'reason': 'Unknown dealer'})
            continue

        wrote = False
        for spec in columns:
            value = _num(cells[spec['index']]) if spec['index'] < len(cells) else None
            if value is None:
                # A blank cell is "no target for this dealer here", which is different
                # from zero and must not be written as one — a stored 0 would show the
                # dealer failing a target nobody set (§3.3).
                continue
            if value < 0:
                errors.append({'row': row_num, 'key': f'{dealer} / {spec["label"]}',
                               'reason': 'Target cannot be negative'})
                continue
            rows.append((row_num, dealer_id, spec, value,
                         f'{dealer} / {spec["label"]}'))
            wrote = True
        if not wrote:
            skipped += 1

    # The slots this file speaks for. A dealer with every cell blank does not clear
    # anyone else's target, but a column present in the file DOES replace that slot for
    # every dealer — that is what makes a corrected re-upload idempotent.
    slots = sorted({(c['level'], c['scheme'], c['part_group'], c['category_id'], c['type'])
                    for c in columns})

    replaced = 0
    with mysql_manager.get_cursor() as cur:
        if slots:
            tuples = ','.join(['(%s,%s,%s,%s,%s)'] * len(slots))
            flat = [v for slot in slots for v in slot]
            cur.execute(
                f"""DELETE FROM dealer_target
                     WHERE target_period=%s AND company_id=%s
                       AND (target_level, scheme, part_group, category_id, target_type)
                           IN ({tuples})""",
                (period_date, company_id, *flat))
            replaced = cur.rowcount

        for row_num, dealer_id, spec, value, key in rows:
            qty = value if spec['type'] == 'qty' else 0
            val = value if spec['type'] == 'value' else 0
            try:
                cur.execute(
                    """INSERT INTO dealer_target
                       (dealer_id, category_id, product_id, part_group, scheme,
                        target_level, target_type, target_uom, target_qty, target_value,
                        month, target_period, company_id, created_at, updated_at)
                       VALUES (%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (dealer_id, spec['category_id'], spec['part_group'], spec['scheme'],
                     spec['level'], spec['type'], spec['uom'], qty, val,
                     label, period_date, company_id, datetime.utcnow(), datetime.utcnow()))
                inserted += 1
            except Exception as e:
                errors.append({'row': row_num, 'key': key, 'reason': str(e)})

    warnings = _target_load_warnings(columns, slots, label, period_date, company_id)
    return replaced, inserted, skipped, errors, warnings


def _find_band_row(raw):
    """Index of the level row, or None. Tolerates a title block above the header pair."""
    for i in range(min(len(raw), _HEADER_SCAN_ROWS)):
        cells = [_txt(v) for v in raw.iloc[i].tolist()]
        hits = sum(1 for c in cells if _LEVEL_WORDS.get(_normalize_header(c.partition(':')[0])))
        if hits >= 2:
            return i
    return None


def _target_load_warnings(columns, slots, label, period_date, company_id):
    """What the operator needs to know about a load that otherwise looks clean.

    Two of these report a number that is RIGHT but smaller than it looks, which is the
    class of problem nobody notices on their own.
    """
    warnings = []
    by_level = {}
    for c in columns:
        by_level.setdefault(c['level'], []).append(c['label'])
    parts = [f'{len(v)} {k.replace("_", "-")}' for k, v in sorted(by_level.items())]
    warnings.append(f'Replaced {len(slots)} target slot(s) for {label} '
                    f'({", ".join(parts)}); anything this file does not name was left '
                    f'untouched.')

    # A litres target counts volume, and volume is parsed out of the product name at
    # product-upload time. Products it could not be read from contribute nothing, so the
    # dealer looks worse than they are — say so, with the number, before that happens.
    if any(c['uom'] == 'litres' for c in columns):
        cats = {c['category_id'] for c in columns if c['uom'] == 'litres'}
        gap = mysql_manager.execute_query(
            f"""SELECT COUNT(*) AS total,
                       SUM(CASE WHEN litres_per_unit IS NULL THEN 1 ELSE 0 END) AS unknown
                  FROM product
                 WHERE company_id = %s AND category_id IN ({_in_list(cats)})""",
            (company_id, *cats)) or [{}]
        unknown = gap[0].get('unknown') or 0
        if unknown:
            warnings.append(
                f'{unknown} of {gap[0].get("total") or 0} product(s) in the litres-targeted '
                f'categor{"y" if len(cats) == 1 else "ies"} have no pack size on record, so '
                f'their sales count as 0 litres. Re-upload the product master to refresh it, '
                f'and set the rest by hand if the size is not in the product name.')

    # Levels are never added together, so a scheme target inside a category target is a
    # breakdown, not an addition — but only if it is actually smaller. A basket bigger
    # than the category that contains it is a data-entry slip worth catching at load.
    over = mysql_manager.execute_query(
        """SELECT COUNT(*) AS n FROM (
               SELECT s.dealer_id
                 FROM dealer_target s
                 JOIN dealer_target c
                      ON c.dealer_id = s.dealer_id AND c.category_id = s.category_id
                     AND c.target_period = s.target_period AND c.company_id = s.company_id
                     AND c.target_level = 'category' AND c.target_type = 'value'
                WHERE s.company_id = %s AND s.target_period = %s
                  AND s.target_level = 'scheme' AND s.target_type = 'value'
                GROUP BY s.dealer_id, s.category_id, c.target_value
               HAVING SUM(s.target_value) > MAX(c.target_value)
           ) x""", (company_id, period_date)) or [{}]
    if over[0].get('n'):
        warnings.append(
            f'{over[0]["n"]} dealer/category combination(s) have scheme targets adding up to '
            f'more than the category target above them. Schemes are a breakdown of the '
            f'category, so the analytics will not add them together — but one of the two '
            f'numbers is probably wrong.')
    return warnings


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
        pack_summary = product_pack.apply_rows(pack_profile, company_id, resolved)

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
            def periods(sql):
                return {r['p']: r['c']
                        for r in (mysql_manager.execute_query(sql, (company_id,)) or [])}
            # Sales isn't month-scoped — report its overall coverage (min/max date + total).
            cov = mysql_manager.execute_query(
                "SELECT MIN(sale_date) mn, MAX(sale_date) mx, COUNT(*) c "
                "FROM busy_sales_data WHERE company_id=%s", (company_id,)) or [{}]
            sales_coverage = {
                'min': str(cov[0]['mn']) if cov[0].get('mn') else None,
                'max': str(cov[0]['mx']) if cov[0].get('mx') else None,
                'total': cov[0].get('c') or 0,
            }
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
                'sales_coverage': sales_coverage,
                'status': {
                    'sales': periods(
                        "SELECT DATE_FORMAT(sale_date,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM busy_sales_data WHERE company_id=%s GROUP BY p"),
                    'part-groups': periods(
                        "SELECT DATE_FORMAT(time_period,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM part_groups WHERE company_id=%s GROUP BY p"),
                    # Counts the whole table, including rows written by the two narrow
                    # feeds this replaced — they wrote here too, so they stay counted.
                    'targets': periods(
                        "SELECT DATE_FORMAT(target_period,'%%Y-%%m-01') p, COUNT(*) c "
                        "FROM dealer_target WHERE company_id=%s GROUP BY p"),
                    # Not period-scoped — coverage is reported separately below.
                    'products': {},
                },
                'category_coverage': cat_coverage,
            }, 200
        except Exception as e:
            logger.exception("Error in /api/admin/monthly/status")
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/admin/monthly/schemes')
class MonthlySchemes(Resource):
    """Scheme names already in use, for the Part Group Mapping dropdown.

    There is no scheme master table — a scheme exists because part_groups rows name it.
    So this lists what is actually in use and the UI also allows a new name to be typed,
    which is the only way a new basket can ever be introduced.
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        try:
            rows = mysql_manager.execute_query(
                """SELECT scheme, COUNT(DISTINCT part_number) AS parts,
                          COUNT(DISTINCT time_period) AS periods
                   FROM part_groups
                   WHERE company_id = %s AND scheme IS NOT NULL AND scheme <> ''
                   GROUP BY scheme ORDER BY scheme""",
                (_company(current_user, request.args.get('company_id', type=int)),)) or []
            return {'success': True, 'schemes': [
                {'name': r['scheme'], 'parts': r['parts'], 'periods': r['periods']}
                for r in rows]}, 200
        except Exception as e:
            logger.exception('Error listing schemes')
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
            df = _read_df(uploaded_file, feed, raw_rows=(feed in _RAW_HEADER_FEEDS))
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 400

        # Products merge-upsert into the product master — no period involved.
        if feed == 'products':
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

        # Sales loads by the dates inside the file — the month/year selector doesn't apply.
        if feed == 'sales':
            # Off unless the operator ticks it: "Particulars" is free ledger text, so
            # blind creation would turn accounting lines ("Cash", GST rows) and typos
            # into dealers that then show up in every dealer picker.
            create_missing = (request.form.get('create_missing_dealers') or '').strip().lower() \
                in ('1', 'true', 'yes', 'on')
            try:
                replaced, inserted, skipped, errors, warnings, covered, created_dealers = \
                    _load_sales(df, company_id, create_missing)
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
                'created_dealers': created_dealers,
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
                    df, period_date, year, month, label, company_id,
                    request.form.get('scheme'))
            else:  # targets
                replaced, inserted, skipped, errors, warnings = _load_targets(
                    df, period_date, year, month, label, company_id)
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
