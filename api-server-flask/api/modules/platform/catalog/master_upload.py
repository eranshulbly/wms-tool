# -*- encoding: utf-8 -*-
"""
Product master upload — merge-upsert of the catalogue and its packaging ladder.

Nine columns, and three tables written:

    product       identity      product_string, name, description, uom, category_id
    product_uom   the ladder    one row per rung, rebuilt from the pack columns
    categories    divisions     one per division code, created the first time one appears

Prices are deliberately NOT written. Every reader of fc_sku_price_details excludes
batch 0 (see product_pack.price_for), so a list rate loaded here would be stored and
never read. Pricing starts at the first GRN.

Merge-upsert, keyed on product_string: an existing product is UPDATED, a new one is
INSERTED, and nothing is ever deleted. Re-uploading a corrected or extended file is
always safe.

Reads Cadila's own rate list unmodified — the header is not on the first row, the
supplier's column names differ from ours, and division banners sit between product
rows. All three are handled here rather than asking the operator to reshape the file.
"""

import re
from io import BytesIO

import pandas as pd

from api.shared.db_manager import mysql_manager
from api.shared.upload_utils import _normalize_header
from api.modules.platform.catalog import product_pack
from api.core.logging import get_logger

logger = get_logger(__name__)


# ── The nine columns ─────────────────────────────────────────────────────────────
#
# field -> (canonical header, aliases, required). Aliases carry the supplier's own
# wording so Cadila's rate list needs no editing before upload.
# The older, longer headings stay on as aliases. A template downloaded before the
# rename still uploads — renaming a column must not invalidate the file someone
# already filled in.
COLUMNS = {
    'product_string':   ('Part Number',    ('PD. CODE', 'PD CODE', 'Part No', 'Product String'), True),
    'name':             ('Name',           ('NAME OF PRODUCTS', 'Product Name', 'Product'),      True),
    'strips_per_box':   ('Strips per Box',  ('STRIP', 'Selling Units per Box', 'Units per Box'),  True),
    'boxes_per_case':   ('Boxes per Case',  ('CASE',),                                           True),
    'tabs_per_strip':   ('Tabs per Strip',  ('TAB', 'Base Units per Selling Unit',
                                             'Units per Strip'),                                 False),
    'selling_label':    ('Pack',            ('PACK',),                                           False),
    'box_label':        ('Box Pack',        ('BOX PACK',),                                       False),
    'description':      ('Description',     ('COMPOSITION', 'Composition', 'Part Description'),  False),
    # Cadila's list heads this DIVN CODE. Stored as the product's category: a division
    # is how Cadila groups its catalogue, which is what category_id is for.
    'division':         ('Division',        ('DIVN CODE', 'Division Code', 'Div Code'),          False),
}

# Enough of these on one row and it is the header. Two distinct hits are required, so a
# data row holding the word "Pack" cannot win.
_HEADER_HINTS = ('Part Number', 'PD. CODE', 'Name', 'NAME OF PRODUCTS')
_HEADER_SCAN_ROWS = 25


# ── Selling unit ─────────────────────────────────────────────────────────────────
#
# There is no unit column in the supplier's list: the pack label carries it. "10 T" is a
# strip of tablets, "200 ML" a bottle, "5 GM" a tube. Read in this order because the
# product name is the stronger signal — an injection packed "2 ML" is a vial, not a
# bottle, and the name is the only place that says so.
_INJECTABLE = ('INJECTION', 'INJ.', ' INJ', 'AMPULE', 'AMPOULE', 'VIAL')
_PACK_RULES = (
    ('ML', 'BOTTLE'),
    ('GM', 'TUBE'),
    ('GRM', 'TUBE'),
    ('SACHET', 'SACHET'),
    ('T', 'STRIP'),
)
DEFAULT_SELLING_UNIT = 'STRIP'


def selling_unit_for(pack_label, name=None):
    """The unit one sellable item is counted in."""
    upper_name = (name or '').upper()
    if any(tok in upper_name for tok in _INJECTABLE):
        return 'VIAL'
    label = (pack_label or '').strip().upper()
    if not label:
        return DEFAULT_SELLING_UNIT
    for token, unit in _PACK_RULES:
        # Word-boundary match: "5 GM" must not be read as grams because of the G in a
        # longer word, and the bare "T" rule must not fire inside "TUBE".
        if re.search(r'\b%s\b' % re.escape(token), label):
            return unit
    return DEFAULT_SELLING_UNIT


# ── Parsing ──────────────────────────────────────────────────────────────────────

def _looks_like_header(cells):
    norm = [_normalize_header(str(c)) for c in cells if c is not None and str(c).strip()]
    hits = {h for h in _HEADER_HINTS if any(_normalize_header(h) in c for c in norm)}
    return len(hits) >= 2


def read_dataframe(uploaded_file):
    """The sheet, with the header row located wherever it actually is.

    Cadila's list carries a title block above the header and a second header row of
    qualifiers beneath it. Taking row 0 blindly yields 'Unnamed: 3' for every column.
    """
    filename = uploaded_file.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('csv', 'xls', 'xlsx'):
        raise ValueError('File must be CSV, XLS, or XLSX')
    raw = uploaded_file.read()
    if not raw:
        raise ValueError('The file is empty')

    def _read(header):
        if ext == 'csv':
            return pd.read_csv(BytesIO(raw), dtype=str, header=header)
        return pd.read_excel(BytesIO(raw), dtype=str, header=header)

    df = _read(0)
    df.columns = [str(c).strip() for c in df.columns]
    if not _looks_like_header(df.columns):
        probe = _read(None).head(_HEADER_SCAN_ROWS)
        for i in range(len(probe)):
            if _looks_like_header(probe.iloc[i].tolist()):
                df = _read(i)
                df.columns = [str(c).strip() for c in df.columns]
                logger.info("product master: header on row %d, %d title row(s) skipped",
                            i + 1, i)
                break
        else:
            raise ValueError(
                'Could not find a header row. The file needs a Part Number '
                '(or PD. CODE) column and a Name (or NAME OF PRODUCTS) column.')
    return df.where(pd.notna(df), None)


def resolve_headers(df):
    """{field: actual column name} for whichever of the nine the file carries."""
    lookup = {}
    for col in df.columns:
        lookup.setdefault(_normalize_header(str(col)), col)
    found = {}
    for field, (canonical, aliases, _required) in COLUMNS.items():
        for candidate in (canonical,) + tuple(aliases):
            hit = lookup.get(_normalize_header(candidate))
            if hit is not None:
                found[field] = hit
                break
    return found


def _text(val):
    if val is None:
        return None
    s = str(val).strip()
    return None if s.lower() in ('', 'nan', 'none', 'nat', '-') else s


def _count(val):
    """A pack count as a positive int, or None.

    Floats are accepted because a spreadsheet stores 30 as '30.0'; a fractional count is
    refused rather than truncated, since half a strip in a box is a typo, not a pack.
    """
    s = _text(val)
    if s is None:
        return None
    try:
        f = float(s.replace(',', ''))
    except ValueError:
        return None
    if f <= 0 or f != int(f):
        return None
    return int(f)


# ── The upload ───────────────────────────────────────────────────────────────────

def parse(df):
    """(parsed, errors, skipped) from a loaded sheet. Reads only — writes nothing.

    Split from `process` so the whole file-shape problem — header hunting, the
    supplier's column names, banner rows, bad counts — can be exercised against a real
    file without a database anywhere near it.
    """
    headers = resolve_headers(df)
    missing = [COLUMNS[f][0] for f, (_c, _a, required) in COLUMNS.items()
               if required and f not in headers]
    if missing:
        raise ValueError('Missing required column(s): ' + ', '.join(missing))

    parsed, errors, skipped = {}, [], 0
    for index, row in df.iterrows():
        row_num = int(index) + 2          # 1-based, plus the header row
        code = _text(row.get(headers['product_string']))
        name = _text(row.get(headers['name']))

        # Division banners and spacer rows carry neither, and are not errors — they are
        # part of how the supplier formats the sheet.
        if not code and not name:
            skipped += 1
            continue
        if not code:
            errors.append({'row': row_num, 'key': name or '', 'reason': 'No Part Number'})
            continue

        strips_per_box = _count(row.get(headers['strips_per_box']))
        boxes_per_case = _count(row.get(headers['boxes_per_case']))

        if not name:
            # A division banner ("PRIDE DIVISION") sits in the code column with nothing
            # else on the row. Reporting five of those as errors on every upload trains
            # the operator to ignore the error list, so a row carrying neither a name nor
            # any pack count is treated as formatting, not as a broken product.
            if strips_per_box is None and boxes_per_case is None:
                skipped += 1
                continue
            errors.append({'row': row_num, 'key': code, 'reason': 'No Name'})
            continue
        bad = [label for label, val in
               (('Strips per Box', strips_per_box), ('Boxes per Case', boxes_per_case))
               if val is None]
        if bad:
            errors.append({'row': row_num, 'key': code,
                           'reason': 'Missing or invalid: ' + ', '.join(bad)})
            continue

        pack_label = _text(row.get(headers['selling_label'])) if 'selling_label' in headers else None
        parsed[code.casefold()] = {
            'product_string':   code,
            'name':             name,
            'description':      _text(row.get(headers['description'])) if 'description' in headers else None,
            'strips_per_box':   strips_per_box,
            'boxes_per_case':   boxes_per_case,
            'tabs_per_strip':   (_count(row.get(headers['tabs_per_strip']))
                                 if 'tabs_per_strip' in headers else None) or 1,
            'selling_label':    pack_label,
            'box_label':        _text(row.get(headers['box_label'])) if 'box_label' in headers else None,
            'selling_unit':     selling_unit_for(pack_label, name),
            # Upper-cased so 'cg' and 'CG' cannot become two divisions.
            'division':         ((_text(row.get(headers['division'])) or '').upper() or None)
                                if 'division' in headers else None,
        }
        # A later row for the same code wins outright: the sheet is a statement of how
        # the product is packed today, and merging two of them invents a third pack.

    return parsed, errors, skipped


def _ensure_categories(cursor, names, created):
    """{division code: category_id}, creating a category for any code that has none.

    Created rather than refused: the master is Cadila's own statement of its divisions and
    there is no screen to add a category, so refusing an unknown code would reject every
    product in the first upload until someone edited the database by hand.

    Matched case-insensitively against every category, active or not. categories.name is
    UNIQUE under a case-insensitive collation, so inserting 'CG' beside an existing 'cg' —
    or beside a deactivated 'CG' — would fail the whole upload on the unique key.
    """
    if not names:
        return {}
    cursor.execute("SELECT category_id, name FROM categories")
    by_key = {}
    for r in cursor.fetchall():
        cid, name = (r['category_id'], r['name']) if isinstance(r, dict) else (r[0], r[1])
        by_key[(name or '').strip().upper()] = cid

    out = {}
    for name in names:
        cid = by_key.get(name.upper())
        if cid is None:
            cursor.execute("INSERT INTO categories (name, is_active) VALUES (%s, 1)", (name,))
            cid = cursor.lastrowid
            by_key[name.upper()] = cid
            created.append(name)
        out[name] = cid
    return out


def process(uploaded_file, company_id):
    """Merge-upsert the master. Returns (result_dict, http_status)."""
    try:
        df = read_dataframe(uploaded_file)
        parsed, errors, skipped = parse(df)
    except ValueError as e:
        return {'success': False, 'msg': str(e)}, 400

    if not parsed:
        return {'success': False,
                'msg': 'No product rows found in the file.',
                'error_count': len(errors), 'errors': errors[:200]}, 400

    profile = product_pack.profile_for_company_id(company_id)
    order_units = profile['order_units'] if profile else ('BOX', 'CASE')

    codes = [v['product_string'] for v in parsed.values()]
    placeholders = ','.join(['%s'] * len(codes))
    existing = {r['product_string'].casefold(): r['product_id'] for r in (
        mysql_manager.execute_query(
            f"SELECT product_id, product_string FROM product "
            f"WHERE product_string IN ({placeholders})", tuple(codes)) or [])}

    division_codes = sorted({v['division'] for v in parsed.values() if v['division']})

    inserted = updated = ladders = divisions = 0
    categories_created = []
    with mysql_manager.get_cursor() as cursor:
        # Inside the same transaction as the products, so an upload that fails partway
        # leaves no categories behind for products that were never written.
        category_ids = _ensure_categories(cursor, division_codes, categories_created)

        for key, v in parsed.items():
            product_id = existing.get(key)
            category_id = category_ids.get(v['division']) if v['division'] else None
            if product_id:
                # Blank cells mean "not supplied", never "clear this" — COALESCE keeps
                # whatever is on file when the column is absent from this upload.
                cursor.execute(
                    """UPDATE product
                          SET name        = %s,
                              description = COALESCE(%s, description),
                              uom         = %s,
                              category_id = COALESCE(%s, category_id),
                              updated_at  = NOW()
                        WHERE product_id  = %s""",
                    (v['name'], v['description'], v['selling_unit'].lower(), category_id,
                     product_id))
                updated += 1
            else:
                cursor.execute(
                    """INSERT INTO product
                         (product_string, name, description, uom, category_id, company_id,
                          is_active, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, 1, NOW(), NOW())""",
                    (v['product_string'], v['name'], v['description'],
                     v['selling_unit'].lower(), category_id, company_id))
                product_id = cursor.lastrowid
                inserted += 1
            if category_id:
                divisions += 1

            rungs = product_pack.build_ladder(
                v['selling_unit'], v['tabs_per_strip'], v['strips_per_box'],
                v['boxes_per_case'], v['selling_label'], v['box_label'], order_units)
            product_pack.replace_ladder(cursor, product_id, rungs)
            ladders += 1

    logger.info("product master upload", extra={
        'company_id': company_id, 'inserted': inserted, 'updated': updated,
        'ladders': ladders, 'divisions': divisions,
        'categories_created': categories_created, 'errors': len(errors)})

    return {
        'success': True,
        'inserted': inserted,
        'updated': updated,
        'ladders': ladders,
        'divisions': divisions,
        'categories_created': categories_created,
        'skipped': skipped,
        'error_count': len(errors),
        'errors': errors[:200],
    }, 200
