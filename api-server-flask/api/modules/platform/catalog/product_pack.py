# -*- encoding: utf-8 -*-
"""
Packaging ladder, prices and per-industry attributes for the product master upload.

Why this is a separate step rather than more columns in _PRODUCT_FIELDS: those write
straight onto `product`, and everything here belongs on a child row. A pharma master
carries a pack hierarchy (tabs in a strip, strips in a box, boxes in a case), four kinds
of price, and fields like composition that mean nothing to an auto-parts catalogue.

The company's PROFILE decides which columns its master carries. A company with no profile
is untouched by any of this — the upload behaves exactly as it did before, which is what
keeps the 60k Hero parts working.

Ordering vs pricing, the thing the whole model exists for:

    order 2 CASE -> x boxes_per_case -> x selling_units_per_box -> strips
    strips x price(per STRIP) = line value

so a rep orders in the unit the goods ship in, and the money is computed in the unit the
supplier quotes.
"""

from decimal import Decimal, InvalidOperation

from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)


# ── Company profiles ─────────────────────────────────────────────────────────────
#
# Keyed on the lower-cased company name, matched on the leading word so trading names
# ('Cadila Pharmaceuticals Ltd') resolve the same as the bare brand — the same rule the
# DMS layout lookup uses, and for the same reason: the company table holds trading names.

# header, meaning. Every column is optional on an UPDATE (a blank cell has always meant
# "not supplied" here); `required_for_new` below is what a NEW product must carry.
CADILA_COLUMNS = {
    'selling_unit':        ('Selling Unit',              ('Sales Unit',)),
    'base_per_selling':    ('Base Units per Selling Unit', ('Tabs per Strip', 'Units per Strip')),
    'selling_per_box':     ('Selling Units per Box',      ('Strips per Box', 'Strip')),
    'boxes_per_case':      ('Boxes per Case',             ('Case',)),
    'selling_label':       ('Pack',                       ()),
    'box_label':           ('Box Pack',                   ()),
    'price_billing':       ('Billing Price',              ('Billing Price per Strip',)),
    'price_landing':       ('Landing Price',              ('Landing Price per Strip', 'Landing Rate')),
    'price_net':           ('Net Rate',                   ()),
    'price_mrp':           ('MRP',                        ()),
    'composition':         ('Composition',                ()),
    'division':            ('Division',                   ('Divn Code',)),
}

CADILA_PROFILE = {
    'key': 'cadila',
    # What a product that does not yet exist must supply. An existing product can still be
    # updated one column at a time — refusing a partial update would make it impossible to
    # correct a single price without re-sending the whole master.
    'required_for_new': ('selling_per_box', 'boxes_per_case', 'price_billing'),
    # The rung prices are quoted against, and the rungs a rep may order in.
    'price_uom_default': 'STRIP',
    'order_units': ('BOX', 'CASE'),
    'attributes': (
        ('composition', 'Composition', 'text'),
        ('division',    'Division',    'text'),
    ),
}

_PROFILES = {'cadila': CADILA_PROFILE}


def profile_for_company(company_name):
    """The upload profile for a company, or None when it has no packaging model.

    Matched on the leading word, so 'Cadila Pharmaceuticals' resolves; guarded with a
    trailing space so an unrelated company that merely starts with the same letters does
    not inherit somebody else's master format.
    """
    norm = ' '.join(''.join(
        ch if (ch.isalnum() or ch.isspace()) else ' '
        for ch in str(company_name or '').lower()).split())
    for key, profile in _PROFILES.items():
        if norm == key or norm.startswith(key + ' '):
            return profile
    return None


def profile_for_company_id(company_id):
    row = mysql_manager.execute_query(
        "SELECT name FROM company WHERE company_id = %s", (company_id,))
    return profile_for_company(row[0]['name']) if row else None


# ── Value coercion ───────────────────────────────────────────────────────────────

def _text(val):
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def _decimal(val):
    """A positive Decimal, or None. Returns None rather than raising: the caller reports
    the row, and one unreadable price must not abort a 300-row master."""
    s = _text(val).replace(',', '')
    if not s:
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return d if d >= 0 else None


def _int(val):
    d = _decimal(val)
    if d is None:
        return None
    try:
        return int(d)
    except (ValueError, OverflowError):
        return None


# ── Ladder construction ──────────────────────────────────────────────────────────

def build_ladder(selling_unit, base_per_selling, selling_per_box, boxes_per_case,
                 selling_label=None, box_label=None, order_units=('BOX', 'CASE')):
    """The rungs for one product, as [(uom_code, factor_to_base, level, label, flags)].

    factor_to_base is absolute, so CASE already carries the whole multiplication and no
    reader has to walk the ladder. A missing rung collapses to 1, which is how a 200 ML
    syrup (no strip, one bottle per box) uses the same code path as a 30x10 tablet box
    rather than needing a branch of its own.
    """
    selling_unit = (selling_unit or 'STRIP').upper()
    base_per_selling = base_per_selling or 1
    selling_per_box = selling_per_box or 1
    boxes_per_case = boxes_per_case or 1

    base_code = 'TAB' if selling_unit == 'STRIP' else 'UNIT'
    per_box = base_per_selling * selling_per_box
    per_case = per_box * boxes_per_case

    rungs = [
        # The base rung is informational: nothing is ordered, priced or stocked in
        # tablets, but the count is what a strip's factor means.
        (base_code, Decimal(1), 0, None,
         {'order': 0, 'price': 0, 'stock': 0}),
        (selling_unit, Decimal(base_per_selling), 1, selling_label,
         {'order': int(selling_unit in order_units), 'price': 1, 'stock': 1}),
        ('BOX', Decimal(per_box), 2, box_label,
         {'order': int('BOX' in order_units), 'price': 0, 'stock': 0}),
        ('CASE', Decimal(per_case), 3, None,
         {'order': int('CASE' in order_units), 'price': 0, 'stock': 0}),
    ]
    # A degenerate rung (a "strip" of one, a "box" of one) is still written: the operator
    # ordering a BOX of syrup needs the rung to exist even though its factor is 1. Only a
    # duplicate CODE is dropped, which happens when the selling unit is itself named BOX.
    seen, out = set(), []
    for code, factor, level, label, flags in rungs:
        if code in seen:
            continue
        seen.add(code)
        out.append((code, factor, level, label, flags))
    return out


def replace_ladder(cursor, product_id, rungs):
    """Write a product's ladder, replacing whatever was there.

    Replaced rather than merged: the ladder is a single statement about how the product
    is packed, and merging would leave a stale CASE rung behind when a supplier drops a
    level. Prices are NOT touched here — they are dated history and outlive a repack.
    """
    cursor.execute("DELETE FROM product_uom WHERE product_id = %s", (product_id,))
    cursor.executemany(
        """INSERT INTO product_uom
             (product_id, uom_code, factor_to_base, level_no, label,
              is_order_unit, is_price_unit, is_stock_unit)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [(product_id, code, factor, level, label,
          flags['order'], flags['price'], flags['stock'])
         for code, factor, level, label, flags in rungs])


# ── Prices ───────────────────────────────────────────────────────────────────────
#
# Prices go to fc_sku_price_details — the table inventory.ingestion already writes when
# stock is received — NOT to a catalogue price table. Price belongs to the stock it was
# paid for; a second store would mean two answers to "what does this cost".
#
# A rate list has no batch: nothing has been received. It is written against batch_id 0,
# which the table's unique key (company_id, entity_id, entity_type, batch_id) accepts as
# an ordinary value, so this needs no schema change. Reading then has one rule:
#
#     most recent real batch  ->  else the batch-0 list rate  ->  else unpriced
#
# so a brand-new catalogue can be ordered on day one, and every receipt afterwards
# quietly takes precedence over the list.
#
# The one thing to know: anything reporting on ACTUAL receipts must exclude batch 0, or a
# rate that was never received shows up as stock that was. batch_costing_report does.
LIST_RATE_BATCH_ID = 0
LIST_RATE_REFERENCE = 'RATE LIST'


def upsert_list_rate(cursor, product_id, company_id, price_uom, prices, gst_percent=None,
                     reference=LIST_RATE_REFERENCE):
    """Write the supplier's list rate for a product as its batch-less price row.

    `landing_price` is the figure orders are valued at, so it takes the landing rate when
    the file supplies one and falls back to the billing rate — the sheet only carries a
    separate landing figure for some products, and a missing one means the two are equal
    rather than that the product is free.

    quantity_received stays 0 and cn_rate stays 0: no goods arrived and no credit note was
    raised. Both are honest zeroes, not placeholders.
    """
    landing = prices.get('landing') or prices.get('billing')
    if landing is None and prices.get('mrp') is None:
        return 0
    cursor.execute(
        """INSERT INTO fc_sku_price_details
             (company_id, planogram_id, entity_id, entity_type, batch_id,
              mrp, landing_price, cn_rate, gst_rate, uom,
              quantity_received, grn_reference, created_by, updated_by)
           VALUES (%s, 0, %s, 'sku', %s, %s, %s, 0, %s, %s, 0, %s, 'upload', 'upload')
           ON DUPLICATE KEY UPDATE
              mrp           = VALUES(mrp),
              landing_price = VALUES(landing_price),
              gst_rate      = VALUES(gst_rate),
              uom           = VALUES(uom),
              grn_reference = VALUES(grn_reference),
              updated_by    = VALUES(updated_by)""",
        (company_id, product_id, LIST_RATE_BATCH_ID,
         prices.get('mrp') or 0, landing or 0, gst_percent or 0,
         (price_uom or 'strip').lower(), reference))
    return 1


# ── Attributes ───────────────────────────────────────────────────────────────────

def ensure_attribute_defs(company_id, definitions):
    """{code: attribute_id}, creating any definition the company does not have yet."""
    if not definitions:
        return {}
    codes = [d[0] for d in definitions]
    ph = ','.join(['%s'] * len(codes))
    existing = {r['code']: r['attribute_id'] for r in (mysql_manager.execute_query(
        f"""SELECT attribute_id, code FROM attribute_def
             WHERE code IN ({ph}) AND (company_id = %s OR company_id IS NULL)""",
        (*codes, company_id)) or [])}
    missing = [d for d in definitions if d[0] not in existing]
    if missing:
        with mysql_manager.get_cursor() as cursor:
            cursor.executemany(
                """INSERT INTO attribute_def (code, label, data_type, company_id)
                   VALUES (%s,%s,%s,%s)""",
                [(code, label, dtype, company_id) for code, label, dtype in missing])
        existing.update({r['code']: r['attribute_id'] for r in (mysql_manager.execute_query(
            f"""SELECT attribute_id, code FROM attribute_def
                 WHERE code IN ({ph}) AND (company_id = %s OR company_id IS NULL)""",
            (*codes, company_id)) or [])})
    return existing


def upsert_attributes(cursor, product_id, values_by_attribute_id):
    """Write text attribute values. A blank value is skipped, not cleared — consistent
    with every other column in this upload, where an empty cell means "not supplied"."""
    rows = [(product_id, attr_id, value)
            for attr_id, value in values_by_attribute_id.items() if value]
    if not rows:
        return 0
    cursor.executemany(
        """INSERT INTO product_attribute (product_id, attribute_id, value_text)
           VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE value_text = VALUES(value_text)""", rows)
    return len(rows)


# ── Row validation ───────────────────────────────────────────────────────────────

def missing_required(profile, row_values, is_new):
    """Which required fields a NEW product's row failed to supply.

    Only enforced for products being created. An existing product is updatable column by
    column, so a file correcting one price does not have to restate the whole pack.
    """
    if not is_new:
        return []
    return [key for key in profile['required_for_new']
            if row_values.get(key) in (None, '', 0)]


def read_row(row, resolved_headers):
    """Pull this profile's fields out of a dataframe row, coerced.

    `resolved_headers` maps field key -> the actual column name found in the file, so the
    caller resolves aliases once for the whole file instead of per row.
    """
    def raw(key):
        col = resolved_headers.get(key)
        return row.get(col) if col else None

    return {
        'selling_unit':     _text(raw('selling_unit')).upper() or None,
        'base_per_selling': _int(raw('base_per_selling')),
        'selling_per_box':  _int(raw('selling_per_box')),
        'boxes_per_case':   _int(raw('boxes_per_case')),
        'selling_label':    _text(raw('selling_label')) or None,
        'box_label':        _text(raw('box_label')) or None,
        'price_billing':    _decimal(raw('price_billing')),
        'price_landing':    _decimal(raw('price_landing')),
        'price_net':        _decimal(raw('price_net')),
        'price_mrp':        _decimal(raw('price_mrp')),
        'composition':      _text(raw('composition')) or None,
        'division':         _text(raw('division')) or None,
    }


def apply_rows(profile, company_id, rows_by_product_id, gst_by_product_id=None,
               reference=LIST_RATE_REFERENCE):
    """Write ladders, list rates and attributes for every product in the upload.

    `rows_by_product_id` is {product_id: (row_values, is_new)}. Everything is written in
    one transaction so a master can never leave a product with a new ladder priced at the
    old rate.
    """
    if not rows_by_product_id:
        return {'ladders': 0, 'prices': 0, 'attributes': 0}

    gst_by_product_id = gst_by_product_id or {}
    attr_ids = ensure_attribute_defs(company_id, profile.get('attributes', ()))
    ladders = prices = attributes = 0

    with mysql_manager.get_cursor() as cursor:
        for product_id, (values, _is_new) in rows_by_product_id.items():
            # Only rewrite the ladder when the file actually described one. A price-only
            # correction must not collapse a 30x10 box to a 1x1 default.
            if any(values.get(k) for k in
                   ('selling_per_box', 'boxes_per_case', 'base_per_selling', 'selling_unit')):
                rungs = build_ladder(
                    values.get('selling_unit') or profile['price_uom_default'],
                    values.get('base_per_selling'),
                    values.get('selling_per_box'),
                    values.get('boxes_per_case'),
                    values.get('selling_label'),
                    values.get('box_label'),
                    profile['order_units'])
                replace_ladder(cursor, product_id, rungs)
                ladders += 1

            # The list rate. `net` is deliberately not written: fc_sku_price_details
            # models a discount as cn_rate against a real receipt, and a rate list has no
            # receipt to discount — recording one here would claim a credit note exists.
            price_uom = values.get('selling_unit') or profile['price_uom_default']
            prices += upsert_list_rate(cursor, product_id, company_id, price_uom, {
                'billing': values.get('price_billing'),
                'landing': values.get('price_landing'),
                'mrp':     values.get('price_mrp'),
            }, gst_by_product_id.get(product_id), reference)

            attributes += upsert_attributes(cursor, product_id, {
                attr_ids[code]: values.get(code)
                for code in ('composition', 'division') if code in attr_ids
            })

    logger.info("product pack/price applied", extra={
        'company_id': company_id, 'ladders': ladders,
        'prices': prices, 'attributes': attributes})
    return {'ladders': ladders, 'prices': prices, 'attributes': attributes}


# ── Reading back (what ordering and pricing will use) ────────────────────────────

def conversion(product_id, from_uom):
    """How many BASE units one `from_uom` is, or None when the product has no ladder.

    None is the signal to treat the product as single-unit, which is what every product
    predating this model is.
    """
    row = mysql_manager.execute_query(
        """SELECT factor_to_base FROM product_uom
            WHERE product_id = %s AND uom_code = %s""", (product_id, from_uom))
    return row[0]['factor_to_base'] if row else None


def price_for(product_id, company_id):
    """What one selling unit costs, for valuing an order at entry.

    The rule, in one query:

        the most recently received batch  ->  else the batch-0 list rate  ->  else None

    Received stock outranks the list because it is what was actually paid; the list rate
    exists so a catalogue can be ordered before anything has been received at all. A
    caller getting None has a product nobody has priced yet — that is a real state and it
    is reported rather than defaulted to zero, which would quietly value an order at nil.

    Returns {'amount', 'uom', 'gst_rate', 'batch_id', 'is_list_rate'}; `amount` is net of
    any credit note, matching how the ingestion module computes effective cost.
    """
    rows = mysql_manager.execute_query(
        """SELECT batch_id, uom, gst_rate, mrp,
                  (landing_price - cn_rate) AS amount
             FROM fc_sku_price_details
            WHERE entity_id = %s AND company_id = %s AND entity_type = 'sku'
            ORDER BY (batch_id = 0), created_on DESC
            LIMIT 1""", (product_id, company_id))
    if not rows:
        return None
    r = rows[0]
    return {'amount': r['amount'], 'uom': r['uom'], 'gst_rate': r['gst_rate'],
            'mrp': r['mrp'], 'batch_id': r['batch_id'],
            'is_list_rate': r['batch_id'] == LIST_RATE_BATCH_ID}


def order_value(product_id, company_id, order_uom, order_qty):
    """Value an order line placed in `order_uom` (BOX / CASE / …).

    This is the calculation the whole packaging model exists for:

        order_qty x factor(order_uom) / factor(price_uom)  ->  quantity in priced units
        x price per priced unit                            ->  line value

    Returns None when the product has no ladder or no price, so the caller can say which
    is missing instead of showing a confidently wrong number.
    """
    price = price_for(product_id, company_id)
    if not price:
        return None
    rungs = {r['uom_code']: r['factor_to_base'] for r in (mysql_manager.execute_query(
        "SELECT uom_code, factor_to_base FROM product_uom WHERE product_id = %s",
        (product_id,)) or [])}
    if not rungs:
        return None
    order_factor = rungs.get((order_uom or '').upper())
    price_factor = rungs.get((price['uom'] or '').upper())
    if not order_factor or not price_factor:
        return None
    priced_qty = (Decimal(order_qty) * order_factor) / price_factor
    return {
        'priced_qty': priced_qty,
        'price_uom': price['uom'],
        'unit_price': price['amount'],
        # Snapshot this: the factor is what makes the value reproducible if the supplier
        # repacks later, and without it a stored amount cannot be explained.
        'uom_factor': order_factor / price_factor,
        'amount': (priced_qty * price['amount']).quantize(Decimal('0.01')),
        'gst_rate': price['gst_rate'],
        'batch_id': price['batch_id'],
        'is_list_rate': price['is_list_rate'],
    }
