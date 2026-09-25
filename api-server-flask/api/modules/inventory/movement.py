# -*- encoding: utf-8 -*-
"""
Stock movement analytics — what is selling, how long the stock on hand will last, and
what will expire before it can clear.

Two tables answer all of it, and nothing here is stored:

    fc_entity_stock         what is on hand right now, per batch
    fc_entity_stock_ledger  every movement; a negative quantity_changed is stock leaving

Outbound is read from the ledger rather than from orders or invoices on purpose. The
ledger is the only record that outlives the document: an order can be deleted, re-uploaded
or corrected, but the units that physically left are still written here, once, at the
moment stock actually moved — whatever paperwork caused it.

A negative quantity_changed is not always a sale, though — the ledger also carries
administrative corrections that reduce stock without a dealer ever buying anything. An
ingestion credit/debit note explicitly marked as returning goods (movement_effect='OUT',
see ingestion/service.py:_ingest_document) writes a negative row with reference_type
'CN'/'DN' — a return to the vendor, not a sale. "Sale rate" is only ever computed from
rows whose reference_type names a real sale channel (SALE_REFERENCE_TYPES below); anything
else is excluded outright rather than trusted by its sign alone.

The derived figures (run rate, cover, risk band) are computed in Python rather than SQL.
They are the part a reader will argue with, so they are kept where they can be read.
"""

from datetime import date, datetime, timedelta

from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger
# Same coercion the costing report uses — MySQL hands back date and Decimal objects that
# Flask-RESTX's encoder refuses, so a populated table would 500 where an empty one passed.
from api.modules.inventory.ingestion.service import jsonable

logger = get_logger(__name__)

# A month, for turning a per-day rate into the per-month figure the trade quotes.
DAYS_PER_MONTH = 30.4375

# The only ledger reference_types that represent a genuine sale — real stock leaving to
# fill a dealer's order. Both close an actual order: 'INVOICE' when an order is closed
# directly on its invoice (fulfillment/invoice/repository.py -> inventory.service.
# deduct_batches), 'DMS' when an app-submitted order's parts are allocated against live
# stock for its DMS download (order/router_dashboard.py -> inventory.service.
# allocate_live). Everything else that can carry a negative quantity_changed is an
# administrative movement, not a sale — see the module docstring — and is excluded by
# name rather than trusted because its sign happens to be negative.
SALE_REFERENCE_TYPES = ('INVOICE', 'DMS')

# How far back the ledger is read for a product's sales, and the outer cap on how many
# days a product's rate can be divided by (_row's observed_days). This is a technical
# limit, not an analytical choice: MySQL prunes partitions older than this rather than
# scanning the archive, so it has to be some bound. It is deliberately NOT a "sale rate
# measured over N days" recency window — there is no such window any more (removed by
# request, along with the dropdown that used to pick a shorter one and the floor that
# used to protect a very new product's rate from one early order). Sale rate is simply
# every recorded sale within this reach, divided by however many of these days the
# product has actually existed for.
HISTORY_MONTHS = 24
HISTORY_DAYS = int(HISTORY_MONTHS * DAYS_PER_MONTH)

# Ordered worst-first: this is also the order the UI lists them in, and the order that
# decides which band a product falls into when more than one rule matches.
BANDS = (
    'Expired',
    'Will expire unsold',
    'Over 12 months cover',
    '4-12 months cover',
    '2-4 months cover',
    '1-2 months cover',
    'Under 30 days cover',
    'Nil stock',
    'No sale data',
)


# ── SQL ──────────────────────────────────────────────────────────────────────
# Stock on hand, folded to one row per product. Expiry is the EARLIEST among the
# batches that still hold stock — the batch that sets the deadline. Expiry is stored
# as an ISO date string inside batch_params, so MIN() over it sorts chronologically.
#
# Landed cost is averaged over only the units that actually have a price row, so a
# batch whose cost never arrived leaves the average alone instead of dragging it to zero.
_STOCK_SQL = """
SELECT  s.entity_id                                                AS product_id,
        SUM(s.quantity)                                            AS stock_units,
        COUNT(DISTINCT s.batch_id)                                 AS batches,
        MIN(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.expiry')), 'null'))
                                                                   AS first_expiry,
        SUM(CASE WHEN pr.id IS NOT NULL
                 THEN s.quantity * (pr.landing_price - pr.cn_rate) END)  AS costed_value,
        SUM(CASE WHEN pr.id IS NOT NULL THEN s.quantity END)             AS costed_units
  FROM  fc_entity_stock s
  LEFT JOIN sku_batch b
         ON b.id = s.batch_id
  LEFT JOIN fc_sku_price_details pr
         ON pr.entity_id = s.entity_id
        AND pr.batch_id  = s.batch_id
        AND pr.company_id = s.company_id
 WHERE  s.entity_type = 'sku'
   AND  s.quantity > 0
   AND  {company}
 GROUP BY s.entity_id
"""

# Movement, folded to one row per product. created_on is bounded so MySQL prunes the
# monthly partitions rather than reading the archive — HISTORY_DAYS, not a recency
# window (see its own note: there is no "measured over N days" choice any more). Every
# sale within that reach counts, once, with nothing narrower cutting it down further.
# reference_type is restricted to SALE_REFERENCE_TYPES (see its own note) — every row
# this query sees is already a real sale, so "quantity_changed < 0" only exists here to
# be defensive; nothing in SALE_REFERENCE_TYPES is ever expected to be positive, but a
# sign flip anywhere upstream should still fail closed (excluded) rather than be counted
# as a sale of the wrong sign.
_MOVE_SQL = """
SELECT  l.entity_id                                                AS product_id,
        SUM(CASE WHEN l.quantity_changed < 0
                 THEN -l.quantity_changed ELSE 0 END)              AS sold,
        MIN(l.created_on)                                          AS first_move,
        MAX(CASE WHEN l.quantity_changed < 0 THEN l.created_on END) AS last_sale
  FROM  fc_entity_stock_ledger l
 WHERE  l.entity_type = 'sku'
   AND  l.reference_type IN ({sale_types})
   AND  l.created_on >= %s
   AND  {company}
 GROUP BY l.entity_id
"""

# When this product's inventory first entered the system at all — sku_batch is a
# permanent batch-identity record, created once (resolve_batch(), ingestion/service.py)
# the first time a batch is ever received for a product, and never deleted even once
# that batch fully sells out. Unlike the ledger's own MIN(created_on) (_MOVE_SQL above),
# this is not bounded by HISTORY_MONTHS, and does not depend on a GRN ledger row
# existing at all — some older/migrated stock has a sku_batch row but no matching ledger
# entry (confirmed on this company's own data). This is the authoritative "first
# stocked" date; _MOVE_SQL's first_move is kept only as a fallback for a product with no
# sku_batch row at all (not batch-tracked).
_FIRST_STOCK_SQL = """
SELECT  sku_id AS product_id, MIN(created_on) AS first_stocked
  FROM  sku_batch
 WHERE  {company}
 GROUP BY sku_id
"""

# On-hand stock, one row per (product, batch) — the detail _STOCK_SQL folds away.
# Landing cost is net of any credit note, same as everywhere else it's read (see
# order/pricing.py) — a batch whose price never arrived leaves landing_price null
# rather than costing it at nothing.
_BATCH_SQL = """
SELECT  s.entity_id                                                AS product_id,
        s.batch_id,
        JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.batch_number')) AS batch_number,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.expiry')), 'null')
                                                                   AS expiry,
        SUM(s.quantity)                                            AS quantity,
        MAX(pr.landing_price - pr.cn_rate)                         AS landing_price
  FROM  fc_entity_stock s
  LEFT JOIN sku_batch b
         ON b.id = s.batch_id
  LEFT JOIN fc_sku_price_details pr
         ON pr.entity_id = s.entity_id
        AND pr.batch_id  = s.batch_id
        AND pr.company_id = s.company_id
 WHERE  s.entity_type = 'sku'
   AND  s.quantity > 0
   AND  {company}
 GROUP BY s.entity_id, s.batch_id, batch_number, expiry
"""

# Ingestion writes the description as 'PACK · MFR'; the pack size is its first part.
_PRODUCT_SQL = """
SELECT  p.product_id,
        p.name                                                     AS product_name,
        p.product_string                                           AS sku_code,
        p.product_use                                              AS product_use,
        SUBSTRING_INDEX(COALESCE(p.description, ''), ' · ', 1)      AS pack,
        p.uom                                                      AS uom,
        c.name                                                     AS category
  FROM  product p
  LEFT JOIN categories c ON c.category_id = p.category_id
 WHERE  p.product_id IN ({ids})
"""


def _in_clause(column, values):
    return '%s IN (%s)' % (column, ','.join(['%s'] * len(values)))


def _f(v):
    return float(v) if v is not None else None


def _months_between(day, other):
    return (day - other).days / DAYS_PER_MONTH


# ── Banding ──────────────────────────────────────────────────────────────────
def _band(stock, rate_month, months_cover, months_to_expiry, ever_sold):
    """Which risk band a product sits in.

    Read top to bottom — the first rule that matches wins, so the worse diagnosis
    always beats the milder one. 'Will expire unsold' is the important line: it fires
    when the stock cannot clear at its own selling rate before the earliest batch dies,
    which is a different question from simply holding a lot of stock.
    """
    if stock <= 0:
        return 'Nil stock'
    if months_to_expiry is not None and months_to_expiry <= 0:
        return 'Expired'
    if not ever_sold:
        return 'No sale data'
    if months_to_expiry is not None and (months_cover is None or months_cover > months_to_expiry):
        # months_cover is None when the rate is zero: at no sales it never clears.
        return 'Will expire unsold'
    if months_cover is None:
        # Not selling, but nothing forces a deadline — it is dead stock, not a write-off.
        return 'Over 12 months cover'
    if months_cover > 12:
        return 'Over 12 months cover'
    if months_cover > 4:
        return '4-12 months cover'
    if months_cover > 2:
        return '2-4 months cover'
    if months_cover >= 1:
        return '1-2 months cover'
    return 'Under 30 days cover'


def movement_report(company_ids=None, as_of=None):
    """One row per product: stock, run rate, cover, expiry and what it puts at risk.

    company_ids of [] means "scoped to nothing", which returns nothing rather than
    everything — the same rule the other admin reports follow. There is no recency
    window any more — sale rate uses every recorded sale within HISTORY_DAYS' reach
    (a technical bound, not an analytical one — see its own note).
    """
    if company_ids is not None and not company_ids:
        return {'rows': [], 'summary': _summary([])}

    today = as_of or date.today()
    now = datetime.combine(today, datetime.min.time()) + timedelta(days=1)
    history_start = now - timedelta(days=HISTORY_DAYS)

    # The sale-types IN-list, then history_start — must line up left-to-right with the
    # %s placeholders as they appear in _MOVE_SQL's text.
    sale_types_sql = ','.join(['%s'] * len(SALE_REFERENCE_TYPES))
    stock_where, stock_params = '1=1', []
    move_where, move_params = '1=1', [*SALE_REFERENCE_TYPES, history_start]
    first_stock_where, first_stock_params = '1=1', []
    if company_ids is not None:
        stock_where = _in_clause('s.company_id', company_ids)
        stock_params = list(company_ids)
        move_where = _in_clause('l.company_id', company_ids)
        move_params += list(company_ids)
        first_stock_where = _in_clause('company_id', company_ids)
        first_stock_params = list(company_ids)

    stock = {int(r['product_id']): r for r in (mysql_manager.execute_query(
        _STOCK_SQL.format(company=stock_where), tuple(stock_params)) or [])}
    moves = {int(r['product_id']): r for r in (mysql_manager.execute_query(
        _MOVE_SQL.format(company=move_where, sale_types=sale_types_sql), tuple(move_params)) or [])}
    first_stocked = {int(r['product_id']): r['first_stocked'] for r in (mysql_manager.execute_query(
        _FIRST_STOCK_SQL.format(company=first_stock_where), tuple(first_stock_params)) or [])}

    # A product belongs in the report if it holds stock or has moved. Products that do
    # neither are catalogue entries with no inventory story to tell, and listing all of
    # them would bury the ones that matter.
    ids = sorted(set(stock) | set(moves))
    if not ids:
        return {'rows': [], 'summary': _summary([])}

    products = {int(r['product_id']): r for r in (mysql_manager.execute_query(
        _PRODUCT_SQL.format(ids=','.join(['%s'] * len(ids))), tuple(ids)) or [])}

    rows = [_row(pid, stock.get(pid), moves.get(pid), products.get(pid, {}),
                 today, first_stocked.get(pid)) for pid in ids]

    # Worst first: the biggest money that will not clear before it expires. A planner
    # opening this report wants the top of the list to be the next thing to act on.
    # Then by stock value, so the tail — the products with no history to project from —
    # still leads with the largest money sitting on the shelf.
    rows.sort(key=lambda r: (-(r['value_at_risk'] or 0), -(r['stock_value'] or 0),
                             r['product_name'] or ''))

    return {'rows': jsonable(rows), 'summary': _summary(rows), 'as_of': today.isoformat()}


def _row(pid, st, mv, prod, today, first_stocked=None):
    stock_units = _f(st and st['stock_units']) or 0.0
    sold = _f(mv and mv['sold']) or 0.0

    # The rate is measured over the days the product has actually been available, not
    # HISTORY_DAYS in full. Stock received three weeks ago has three weeks of history;
    # dividing its sales by two years would report it as a sliver of its real rate and
    # hide a stockout. Capped at HISTORY_DAYS at the other end, since `sold` itself can't
    # see further back than that (_MOVE_SQL's own read bound) — a product older than
    # that must not be divided by more days than its sales figure can account for.
    #
    # "Available" means since this product's inventory first entered the system at all —
    # sku_batch's own created_on (first_stocked, from _FIRST_STOCK_SQL), not the first
    # SALE. The ledger's own MIN(created_on) (mv['first_move']) is kept only as a
    # fallback for a product with no sku_batch row (not batch-tracked) — see
    # _FIRST_STOCK_SQL's own note.
    observed_days = HISTORY_DAYS
    first_seen = first_stocked or (mv and mv['first_move'])
    if first_seen:
        if isinstance(first_seen, datetime):
            first_seen = first_seen.date()
        observed_days = min(HISTORY_DAYS, max((today - first_seen).days + 1, 1))

    # A product that has never shipped has no rate — not a rate of zero. The difference
    # matters downstream: a measured zero means the stock is provably not moving, while
    # no history at all means nothing can be projected from it yet.
    ever_sold = sold > 0
    rate_month = None
    if ever_sold:
        rate_month = sold / observed_days * DAYS_PER_MONTH

    months_cover = None
    if rate_month:
        months_cover = stock_units / rate_month

    expiry = st and st['first_expiry']
    months_to_expiry = None
    if expiry:
        if isinstance(expiry, str):
            expiry = datetime.strptime(expiry[:10], '%Y-%m-%d').date()
        elif isinstance(expiry, datetime):
            expiry = expiry.date()
        months_to_expiry = _months_between(expiry, today)

    # What it would take to clear the shelf before the earliest batch expires — the
    # number to compare against the rate the product is actually selling at.
    rate_to_clear = None
    if stock_units > 0 and months_to_expiry is not None and months_to_expiry > 0:
        rate_to_clear = stock_units / months_to_expiry

    # Units that will still be sitting there on expiry day at today's rate, and what they
    # cost to buy. This is the number the report exists to surface — so it is left null,
    # not set to the whole shelf, when there is no rate to project. Calling untested stock
    # "at risk" would put every new arrival in the total and drown the real cases.
    units_at_risk = None
    if stock_units > 0 and months_to_expiry is not None and rate_month is not None:
        will_sell = rate_month * max(months_to_expiry, 0)
        units_at_risk = max(stock_units - will_sell, 0.0)

    costed_units = _f(st and st['costed_units']) or 0.0
    costed_value = _f(st and st['costed_value']) or 0.0
    landed_unit = costed_value / costed_units if costed_units else None

    return {
        'product_id': pid,
        'product_name': prod.get('product_name') or f'#{pid}',
        'sku_code': prod.get('sku_code'),
        'product_use': prod.get('product_use'),
        'pack': prod.get('pack') or None,
        'uom': prod.get('uom'),
        'category': prod.get('category'),

        'stock_units': round(stock_units, 2),
        'batches': int((st and st['batches']) or 0),
        'stock_value': round(stock_units * landed_unit, 2) if landed_unit is not None else None,
        'landed_unit': round(landed_unit, 4) if landed_unit is not None else None,

        'sale_rate_month': round(rate_month, 1) if rate_month is not None else None,
        'sold': round(sold, 2),
        'observed_days': observed_days,
        'last_sale': mv and mv['last_sale'],

        'months_cover': round(months_cover, 2) if months_cover is not None else None,

        'first_expiry': expiry.isoformat() if expiry else None,
        'months_to_expiry': round(months_to_expiry, 2) if months_to_expiry is not None else None,
        'rate_to_clear': round(rate_to_clear) if rate_to_clear is not None else None,

        'units_at_risk': round(units_at_risk, 2) if units_at_risk is not None else None,
        'value_at_risk': (round(units_at_risk * landed_unit, 2)
                          if units_at_risk is not None and landed_unit is not None else None),

        'band': _band(stock_units, rate_month, months_cover, months_to_expiry, ever_sold),
    }


def _summary(rows):
    """Headline figures for the tiles. Every one of them is a count or a sum of the
    rows below it, so a reader can always find the tile's number in the table.

    'unmeasured' is reported alongside the risk total rather than folded into it. Stock
    with no sales history is not safe, but it is not measurable either, and adding it to
    the at-risk figure would make that figure move every time a delivery arrives.
    """
    at_risk = [r for r in rows if r['band'] in ('Expired', 'Will expire unsold')]
    unmeasured = [r for r in rows if r['band'] == 'No sale data']
    return {
        'products': len(rows),
        'stock_value': round(sum(r['stock_value'] or 0 for r in rows), 2),
        'value_at_risk': round(sum(r['value_at_risk'] or 0 for r in rows), 2),
        'units_at_risk': round(sum(r['units_at_risk'] or 0 for r in rows), 2),
        'at_risk_products': len(at_risk),
        'unmeasured_value': round(sum(r['stock_value'] or 0 for r in unmeasured), 2),
        'stockout_products': len([r for r in rows if r['band'] == 'Under 30 days cover']),
        'no_sale_products': len([r for r in rows if r['band'] == 'No sale data']),
        'bands': [{'band': b, 'products': len([r for r in rows if r['band'] == b])}
                  for b in BANDS],
    }


def batch_inventory(company_ids=None, as_of=None):
    """One row per (product, batch) currently on hand — the detail movement_report
    folds away into one row per product.

    Sorted nearest-expiry-first: a batch with 40 days left is the thing to act on
    regardless of how much of the shelf it is, which is exactly what a product-level
    view (MIN(expiry) per product) can hide behind a product's other, healthier batches.
    """
    if company_ids is not None and not company_ids:
        return []

    where, params = '1=1', []
    if company_ids is not None:
        where = _in_clause('s.company_id', company_ids)
        params = list(company_ids)

    batches = mysql_manager.execute_query(
        _BATCH_SQL.format(company=where), tuple(params)) or []
    if not batches:
        return []

    ids = sorted({int(r['product_id']) for r in batches})
    products = {int(r['product_id']): r for r in (mysql_manager.execute_query(
        _PRODUCT_SQL.format(ids=','.join(['%s'] * len(ids))), tuple(ids)) or [])}

    today = as_of or date.today()
    rows = []
    for r in batches:
        pid = int(r['product_id'])
        prod = products.get(pid, {})
        quantity = _f(r['quantity']) or 0.0
        landing_price = _f(r['landing_price'])

        expiry = r['expiry']
        months_to_expiry = None
        if expiry:
            expiry_date = datetime.strptime(expiry[:10], '%Y-%m-%d').date()
            months_to_expiry = _months_between(expiry_date, today)
            expiry = expiry_date.isoformat()

        rows.append({
            'product_id': pid,
            'product_name': prod.get('product_name') or f'#{pid}',
            'sku_code': prod.get('sku_code'),
            'product_use': prod.get('product_use'),
            'pack': prod.get('pack') or None,
            'uom': prod.get('uom'),
            'category': prod.get('category'),

            'batch_id': r['batch_id'],
            'batch_number': r['batch_number'] or '(no batch)',
            'expiry': expiry,
            'months_to_expiry': round(months_to_expiry, 2) if months_to_expiry is not None else None,

            'quantity': round(quantity, 2),
            'landing_price': round(landing_price, 4) if landing_price is not None else None,
            'stock_value': (round(quantity * landing_price, 2)
                            if landing_price is not None else None),
        })

    # Nulls (no batch, or no expiry on file) sort last — they are not the ones about to
    # expire, they are the ones nobody can say anything about, which is a different
    # problem worth seeing but not the most urgent one.
    rows.sort(key=lambda r: (r['months_to_expiry'] is None, r['months_to_expiry'] or 0,
                             r['product_name'] or ''))
    return rows
