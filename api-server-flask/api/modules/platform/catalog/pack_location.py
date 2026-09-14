# -*- encoding: utf-8 -*-
"""Bin locations and packaging ladders, learned from the inventory sheet.

The stock upload used to answer one question — how many of this part are there — and the
picklist needs two more: where is it kept, and how many make a case. All three arrive on
the same sheet, so they are applied from the same upload rather than asking an operator to
keep a second file in step with the first.

The three are stored apart because they change at different rates and mean different
things:

  * quantity      -> temp_inventory   a snapshot, replaced wholesale every upload
  * bin location  -> product_location where the part BELONGS, per warehouse
  * pack sizes    -> product_uom      the conversion ladder, shared by orders and pricing

Only what the sheet actually states is written. A sheet with no pack columns leaves an
existing ladder alone rather than flattening it to one unit, because "this column is
absent" is not the same statement as "this part comes loose".
"""

import re

from datetime import datetime

from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)

# Bin codes are written A-04-C-02. The sheet is typed by hand, so the same bin turns up as
# "A-04 - C-02", "A-04- C-02" and "A-04 -C-02", and stored verbatim those are four
# different bins as far as any grouping, sorting or lookup is concerned. Whitespace INSIDE
# a code is therefore always a typo and is removed; a comma still separates genuinely
# different bins, and survives.
_BIN_SEPARATOR = re.compile(r'\s*,\s*')
_INNER_SPACE = re.compile(r'\s+')


def normalise_bin_location(raw):
    """'A-04 - c-02, B-10 - B-01' -> 'A-04-C-02, B-10-B-01'.

    Upper-cased for the same reason the spaces go: a bin typed 'A-01-c-01' and one typed
    'A-01-C-01' are the same shelf, and keeping both spellings makes them sort apart on a
    picklist and count as two bins in any grouping. Bin codes are codes, not prose.
    """
    text = str(raw or '').strip()
    if not text:
        return ''
    codes = [_INNER_SPACE.sub('', part).upper()
             for part in _BIN_SEPARATOR.split(text) if part.strip()]
    return ', '.join(code for code in codes if code)

# Matches temp_inventory's chunking: these sheets run to tens of thousands of parts, and
# the cost of the whole sync should stay flat in the number of rows.
_CHUNK = 1000

# The rungs this sheet can describe. The base is always PCS at factor 1 — every other
# factor on the sheet ("50 per case") is expressed in these, which is what makes
# factor_to_base absolute and a conversion a single multiply.
_BASE_UOM = 'PCS'
_BOX_UOM = 'BOX'
_CASE_UOM = 'CASE'


def _product_ids(part_numbers, cursor=None):
    """product_string -> product_id, in chunks. Unknown parts are simply absent.

    `cursor` matters when this is called after creating products in the same transaction:
    the inserts are not committed yet, so a pooled connection of its own would not see
    them and every part just created would look unknown all over again.
    """
    found = {}
    parts = list(part_numbers)
    for i in range(0, len(parts), _CHUNK):
        chunk = parts[i:i + _CHUNK]
        placeholders = ','.join(['%s'] * len(chunk))
        sql = (f"SELECT product_id, product_string FROM product "
               f"WHERE product_string IN ({placeholders})")
        if cursor is not None:
            cursor.execute(sql, tuple(chunk))
            rows = cursor.fetchall() or []
        else:
            rows = mysql_manager.execute_query(sql, tuple(chunk)) or []
        for row in rows:
            found[row['product_string']] = row['product_id']
    return found


def _create_missing_products(cursor, items, ids, company_id):
    """Create catalogue products for parts the sheet names but the master lacks.

    The inventory sheet IS the product master here — it is the only document that lists
    every part with its bin and its pack sizes. Earlier this function refused to create
    products, on the reasoning that a stock sheet's job is to count things and letting it
    write the catalogue would import its typos. That was wrong for how this is actually
    used: it meant a part only ever got a bin and a case size if some challan had already
    created it, so a sheet of 101 parts attached data to 3 and every other picklist line
    printed blank.

    Only identity is written — code and name. HSN, GST, price and UOM are left for the
    challan and invoice, which print them properly; `product_sync` fills those blanks
    later without overwriting anything.
    """
    now = datetime.utcnow()
    rows = []
    for item in items:
        part = item['part_number']
        if part in ids:
            continue
        # name is NOT NULL. A sheet with no Product Name column falls back to the code
        # rather than failing the upload on a blank cell.
        name = (str(item.get('name') or '').strip() or part)[:255]
        rows.append((part, name, name, company_id, now, now))
    if not rows:
        return 0
    for i in range(0, len(rows), _CHUNK):
        # IGNORE because product_string is UNIQUE: a part listed twice in one sheet, or
        # created by a challan between the read above and this write, must not abort the
        # whole upload.
        cursor.executemany(
            """INSERT IGNORE INTO product
                   (product_string, name, description, company_id, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            rows[i:i + _CHUNK])
    return len(rows)


def _sync_locations(cursor, items, ids, warehouse_id, company_id):
    """Upsert one bin location per (product, warehouse). Returns rows written.

    A blank Location cell is skipped, not written as an empty string: the sheet not saying
    where a part is does not mean the part has no home, and overwriting a known bin with
    '' would lose it on the next upload of a sheet whose location column happened to be
    incomplete.
    """
    rows = []
    for it in items:
        if it['part_number'] not in ids:
            continue
        bin_location = normalise_bin_location(it.get('location'))
        if not bin_location:
            continue
        rows.append((ids[it['part_number']], warehouse_id, company_id, bin_location))
    if not rows:
        return 0
    for i in range(0, len(rows), _CHUNK):
        cursor.executemany(
            """INSERT INTO product_location
                   (product_id, warehouse_id, company_id, bin_location)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   bin_location = VALUES(bin_location),
                   company_id   = VALUES(company_id)""",
            rows[i:i + _CHUNK])
    return len(rows)


def _ladder_rows(item, product_id):
    """The product_uom rows this sheet's pack columns imply for one part.

    Always includes the PCS base so a part with a case size has a complete ladder to
    convert against — without it `factor_to_base` has no unit to be relative to, and a
    reader would have to guess that the unnamed base is pieces.

    A rung is emitted only when the sheet gives a factor for it, and a factor of 1 for a
    case is dropped: "1 per case" is what a blank column looks like once a spreadsheet has
    filled it in, and treating it as a real rung would make every loose part orderable
    "by the case" of one.
    """
    rows = [(product_id, _BASE_UOM, 1, 0, 'Piece', 1)]
    per_box = item.get('units_per_box')
    per_case = item.get('units_per_case')
    if per_box and per_box > 1:
        rows.append((product_id, _BOX_UOM, per_box, 1, 'Box', 0))
    if per_case and per_case > 1:
        rows.append((product_id, _CASE_UOM, per_case, 2, 'Case', 0))
    return rows


def _sync_uoms(cursor, items, ids):
    """Upsert the packaging ladder. Returns the number of products given one."""
    rows, touched = [], set()
    for item in items:
        pid = ids.get(item['part_number'])
        if pid is None:
            continue
        if not (item.get('units_per_case') or item.get('units_per_box')):
            continue          # nothing stated — leave any existing ladder alone
        rows.extend(_ladder_rows(item, pid))
        touched.add(pid)
    if not rows:
        return 0
    for i in range(0, len(rows), _CHUNK):
        cursor.executemany(
            """INSERT INTO product_uom
                   (product_id, uom_code, factor_to_base, level_no, label, is_stock_unit)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   factor_to_base = VALUES(factor_to_base),
                   level_no       = VALUES(level_no),
                   label          = VALUES(label),
                   is_stock_unit  = VALUES(is_stock_unit)""",
            rows[i:i + _CHUNK])
    return len(touched)


def sync_pack_and_location(items, warehouse_id, company_id=None):
    """Apply the location and pack columns of an inventory upload.

    `items` are parse_inventory_sheet's rows. Returns
    {'created': n, 'located': n, 'packed': n, 'unknown_parts': n}.

    Parts the catalogue does not have are CREATED, then given their bin and pack ladder in
    the same pass. That ordering is the whole point: attaching only to pre-existing
    products made the result depend on whether a challan happened to mention the part
    first, so the same sheet uploaded twice gave different answers. `unknown_parts` is
    therefore whatever could still not be resolved after creating — normally zero, and
    non-zero only if a write was refused.
    """
    stated = [it for it in items
              if it.get('location') or it.get('units_per_case') or it.get('units_per_box')]
    if not stated:
        return {'created': 0, 'located': 0, 'packed': 0, 'unknown_parts': 0}

    parts = {it['part_number'] for it in stated}
    with mysql_manager.get_cursor() as cursor:
        ids = _product_ids(parts, cursor)
        created = _create_missing_products(cursor, stated, ids, company_id)
        if created:
            # Re-read through the SAME cursor to pick up the ids just assigned — the rows
            # written above carry only codes, and the inserts are still uncommitted.
            ids = _product_ids(parts, cursor)
        unknown = sum(1 for it in stated if it['part_number'] not in ids)

        located = _sync_locations(cursor, stated, ids, warehouse_id, company_id)
        packed = _sync_uoms(cursor, stated, ids)

    logger.info("inventory upload: catalogue, locations and pack sizes applied", extra={
        'warehouse_id': warehouse_id, 'company_id': company_id,
        'products_created': created, 'located': located, 'packed': packed,
        'unknown_parts': unknown})
    return {'created': created, 'located': located, 'packed': packed,
            'unknown_parts': unknown}
