# -*- encoding: utf-8 -*-
"""
inventory module — service layer (the module's cross-module API).

Backed by the bin- and batch-level model in GRN_STACKING_DESIGN.md:

    fc_entity_stock         live on-hand per (planogram, location, bin, sku, batch)
    fc_entity_stock_ledger  append-only audit of every change
    transferin_info         immutable GRN lines; unstacked_quantity per inbound
    entity_movement_*       the job engine: stacking | picking | stock moves

Key invariant (see the design doc §4.2): unstacked stock is held BOTH as an
fc_entity_stock row at location 8 AND as transferin_info.unstacked_quantity. They must
move together. On-hand therefore reads fc_entity_stock alone — adding unstacked_quantity
on top would double-count.

Internally everything works in the NUMERIC sku id (entity_id). The routers translate
to/from sku_code at the boundary.

Write flows (GRN receive, stacking, picking completion) are not implemented yet — they
raise NotImplementedError and their endpoints return 501. Reads are live.
"""

from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.modules.inventory.schema import Location
from api.permissions import company_filter_sql

logger = get_logger(__name__)

DEFAULT_PLANOGRAM_ID = 1


# ── Domain errors (routers map these to HTTP codes) ──────────────────────────
class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class InsufficientStock(Exception):
    pass


class MovementType:
    STACKING = "sku-stacking"
    PICKING = "picking"
    BINNING = "binning"
    STOCK_MOVE = "stock-move"


class RequestStatus:
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RecommendationStatus:
    PENDING = "pending"
    COMPLETED = "completed"


def planogram_for_warehouse(warehouse_id):
    """Planogram is 1:1 with a warehouse/FC (fc_planogram.unique_fc_id).

    Until fc_planogram rows are provisioned we treat the warehouse id as the
    planogram id, defaulting to 1.
    """
    return int(warehouse_id or DEFAULT_PLANOGRAM_ID)


# ── Warehouses ───────────────────────────────────────────────────────────────
def list_warehouses(active_only=True):
    where = "WHERE is_active = 1" if active_only else ""
    return mysql_manager.execute_query(
        f"""SELECT warehouse_id, code, name, location AS address, is_active, created_at
            FROM warehouse {where} ORDER BY name"""
    ) or []


def warehouse_exists(warehouse_id):
    rows = mysql_manager.execute_query(
        "SELECT warehouse_id, is_active FROM warehouse WHERE warehouse_id = %s", (warehouse_id,)
    )
    return bool(rows) and bool(rows[0]['is_active'])


def create_warehouse(code, name, address=None):
    if mysql_manager.execute_query("SELECT warehouse_id FROM warehouse WHERE code = %s", (code,)):
        raise ConflictError(f"warehouse code '{code}' already exists")
    mysql_manager.execute_query(
        "INSERT INTO warehouse (code, name, location, is_active) VALUES (%s, %s, %s, 1)",
        (code, name, address), fetch=False,
    )
    return mysql_manager.execute_query(
        """SELECT warehouse_id, code, name, location AS address, is_active, created_at
           FROM warehouse WHERE code = %s""", (code,)
    )[0]


def list_locations():
    return mysql_manager.execute_query(
        """SELECT id, location_type, is_picking_enabled, is_bulk_location, location_description
           FROM planogram_locations ORDER BY id"""
    ) or []


# ── Stock reads ──────────────────────────────────────────────────────────────
_STOCK_COLS = """id AS stock_id, planogram_id, location_id, bin_id, bin_location,
                 entity_id, entity_type, batch_id, bin_priority_order, quantity, updated_on"""


def list_stock(planogram_id=None, entity_id=None, location_id=None, bin_id=None,
               batch_id=None, limit=200, offset=0, company_ids=None):
    """Bin- and batch-level stock rows. This is the complete on-hand picture,
    including unstacked (location 8).

    `company_ids` is the caller's resolved tenant scope (permissions.resolve_company_scope).
    A warehouse holds stock for several companies at once, so planogram_id alone does NOT
    scope a tenant — the company filter is what keeps one company's stock out of another's
    view.
    """
    cf_sql, cf_params = company_filter_sql(company_ids)
    where, params = [cf_sql], list(cf_params)
    if planogram_id is not None:
        where.append("planogram_id = %s")
        params.append(planogram_id)
    if entity_id is not None:
        where.append("entity_id = %s")
        params.append(entity_id)
    if location_id is not None:
        where.append("location_id = %s")
        params.append(location_id)
    if bin_id is not None:
        where.append("bin_id = %s")
        params.append(bin_id)
    if batch_id is not None:
        where.append("batch_id = %s")
        params.append(batch_id)

    clause = "WHERE " + " AND ".join(where)
    params += [limit, offset]
    return mysql_manager.execute_query(
        f"""SELECT {_STOCK_COLS} FROM fc_entity_stock {clause}
            ORDER BY planogram_id, entity_id, location_id, bin_priority_order
            LIMIT %s OFFSET %s""",
        tuple(params),
    ) or []


def on_hand(entity_id, planogram_id=None, location_id=None, company_ids=None):
    """Total quantity for a SKU. Unstacked is included (it is a location-8 stock row)."""
    cf_sql, cf_params = company_filter_sql(company_ids)
    where, params = ["entity_id = %s", cf_sql], [entity_id, *cf_params]
    if planogram_id is not None:
        where.append("planogram_id = %s")
        params.append(planogram_id)
    if location_id is not None:
        where.append("location_id = %s")
        params.append(location_id)
    rows = mysql_manager.execute_query(
        f"SELECT COALESCE(SUM(quantity), 0) AS qty FROM fc_entity_stock WHERE {' AND '.join(where)}",
        tuple(params),
    )
    return float(rows[0]['qty']) if rows else 0.0


def pickable_on_hand(entity_id, planogram_id=None, company_ids=None):
    """Quantity in picking-enabled locations only (primary + unstacked)."""
    cf_sql, cf_params = company_filter_sql(company_ids, alias='s')
    where, params = ["s.entity_id = %s", cf_sql], [entity_id, *cf_params]
    if planogram_id is not None:
        where.append("s.planogram_id = %s")
        params.append(planogram_id)
    rows = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(s.quantity), 0) AS qty
            FROM fc_entity_stock s
            JOIN planogram_locations l ON l.id = s.location_id
            WHERE {' AND '.join(where)} AND l.is_picking_enabled = 1""",
        tuple(params),
    )
    return float(rows[0]['qty']) if rows else 0.0


def stock_breakdown(entity_id, planogram_id=None, company_ids=None):
    """Per-location/bin/batch rows for one SKU, plus the totals."""
    rows = list_stock(planogram_id=planogram_id, entity_id=entity_id, limit=1000,
                      company_ids=company_ids)
    return {
        'total_quantity': sum(float(r['quantity']) for r in rows),
        'pickable_quantity': pickable_on_hand(entity_id, planogram_id, company_ids=company_ids),
        'rows': rows,
    }


def unstacked_breakdown(entity_id, planogram_id=None, company_ids=None):
    """Which inbound lines the unstacked stock came from (FIFO / traceability).

    The quantities here must sum to the location-8 fc_entity_stock row for the same
    sku+batch — see the invariant in the design doc.
    """
    cf_sql, cf_params = company_filter_sql(company_ids)
    where = ["entity_id = %s", "unstacked_quantity > 0", cf_sql]
    params = [entity_id, *cf_params]
    if planogram_id is not None:
        where.append("planogram_id = %s")
        params.append(planogram_id)
    return mysql_manager.execute_query(
        f"""SELECT id AS transferin_info_id, transferin_id, transferin_type_id, batch_id,
                   quantity, unstacked_quantity, vbin_id, mrp, cost_price,
                   transferin_status, created_on
            FROM transferin_info WHERE {' AND '.join(where)}
            ORDER BY transferin_id, id""",
        tuple(params),
    ) or []


# ── Ledger reads ─────────────────────────────────────────────────────────────
def list_ledger(planogram_id=None, entity_id=None, batch_id=None, reference_type=None,
                limit=100, offset=0, company_ids=None):
    cf_sql, cf_params = company_filter_sql(company_ids)
    where, params = [cf_sql], list(cf_params)
    if planogram_id is not None:
        where.append("planogram_id = %s")
        params.append(planogram_id)
    if entity_id is not None:
        where.append("entity_id = %s")
        params.append(entity_id)
    if batch_id is not None:
        where.append("batch_id = %s")
        params.append(batch_id)
    if reference_type:
        where.append("reference_type = %s")
        params.append(reference_type)

    clause = "WHERE " + " AND ".join(where)   # always non-empty: the company filter is first
    params += [limit, offset]
    return mysql_manager.execute_query(
        f"""SELECT id AS ledger_id, planogram_id, location_id, bin_id, bin_location,
                   entity_id, entity_type, batch_id, quantity_changed, quantity_after_change,
                   reference_id, reference_type, cost_price, created_by, created_on
            FROM fc_entity_stock_ledger {clause}
            ORDER BY id DESC LIMIT %s OFFSET %s""",
        tuple(params),
    ) or []


# ── Movement requests (stacking | picking | moves) ───────────────────────────
def list_movement_requests(planogram_id=None, movement_type=None, request_status=None,
                           reference_type=None, request_identifier=None,
                           limit=50, offset=0, company_ids=None):
    cf_sql, cf_params = company_filter_sql(company_ids)
    where, params = [cf_sql], list(cf_params)
    if planogram_id is not None:
        where.append("planogram_id = %s")
        params.append(planogram_id)
    if movement_type:
        where.append("movement_type = %s")
        params.append(movement_type)
    if request_status:
        where.append("request_status = %s")
        params.append(request_status)
    if reference_type:
        where.append("reference_type = %s")
        params.append(reference_type)
    if request_identifier is not None:
        where.append("request_identifier = %s")
        params.append(request_identifier)

    clause = "WHERE " + " AND ".join(where)   # always non-empty: the company filter is first
    params += [limit, offset]
    return mysql_manager.execute_query(
        f"""SELECT id AS request_id, planogram_id, movement_type, request_status,
                   request_identifier, reference_type, metadata, created_by_id, created_on
            FROM entity_movement_request {clause}
            ORDER BY id DESC LIMIT %s OFFSET %s""",
        tuple(params),
    ) or []


def get_movement_request(request_id, company_ids=None):
    """A request with its detail lines and each line's recommendations.

    Scoped by company as well as id — otherwise a caller could read another tenant's
    request simply by guessing its id.
    """
    cf_sql, cf_params = company_filter_sql(company_ids)
    rows = mysql_manager.execute_query(
        f"""SELECT id AS request_id, planogram_id, movement_type, request_status,
                  request_identifier, reference_type, metadata, meta_info,
                  created_by_id, created_on, updated_on
           FROM entity_movement_request WHERE id = %s AND {cf_sql}""",
        (request_id, *cf_params),
    )
    if not rows:
        return None
    request = rows[0]
    request['details'] = _details_for(request_id)
    return request


def _details_for(request_id):
    details = mysql_manager.execute_query(
        """SELECT id AS detail_id, entity_id, entity_type, source_bin_id, source_location_id,
                  picked_quantity, underpick_reason_id, source_stock_info, created_on
           FROM entity_movement_details WHERE request_id = %s ORDER BY id""",
        (request_id,),
    ) or []
    for d in details:
        d['recommendations'] = _recommendations_for(d['detail_id'])
    return details


def _recommendations_for(detail_id):
    """EMR rows joined to their core fc_entity_recommendation instruction."""
    return mysql_manager.execute_query(
        """SELECT r.id AS recommendation_id, r.core_recommendation_id,
                  r.parent_recommendation_id, r.understack_reason_id,
                  r.recommendation_type, r.sequence, r.quantity,
                  c.source_location_id, c.destination_location_id,
                  c.source_bin_id, c.destination_bin_id,
                  c.source_bin_location, c.destination_bin_location,
                  c.operation, c.batch_id, c.bin_priority_order,
                  c.qty_to_process, c.qty_processed, c.status
           FROM entity_movement_recommendation r
           LEFT JOIN fc_entity_recommendation c ON c.id = r.core_recommendation_id
           WHERE r.request_detail_id = %s
           ORDER BY r.sequence, r.id""",
        (detail_id,),
    ) or []


def picking_request_for_order(order_id):
    """The picking job raised for an order, if any."""
    rows = list_movement_requests(
        movement_type=MovementType.PICKING, reference_type='ORDER',
        request_identifier=order_id, limit=1,
    )
    return get_movement_request(rows[0]['request_id']) if rows else None


def create_picking_request(order_id, warehouse_id, lines, created_by=None, cursor=None):
    """Raise the picking job for an order: request header + one detail per line.

    Idempotent per order. Recommendations (which bin to pick from) are generated by the
    picking flow, which is not built yet — see GRN_STACKING_DESIGN.md §2.
    """
    existing = picking_request_for_order(order_id)
    if existing:
        return existing

    planogram_id = planogram_for_warehouse(warehouse_id)

    def _create(cur):
        cur.execute(
            """INSERT INTO entity_movement_request
                 (planogram_id, movement_type, request_status, meta_info,
                  created_by_id, updated_by_id, request_identifier, reference_type)
               VALUES (%s, %s, %s, '', %s, %s, %s, 'ORDER')""",
            (planogram_id, MovementType.PICKING, RequestStatus.CREATED,
             created_by or 0, created_by or 0, order_id),
        )
        request_id = cur.lastrowid
        for line in lines:
            cur.execute(
                """INSERT INTO entity_movement_details
                     (request_id, entity_id, entity_type, source_bin_id, source_location_id,
                      picked_quantity, underpick_reason_id, source_stock_info,
                      created_by_id, updated_by_id)
                   VALUES (%s, %s, 'sku', 0, %s, 0, 0, '{}', %s, %s)""",
                (request_id, line['entity_id'], Location.PRIMARY,
                 created_by or 0, created_by or 0),
            )
        return request_id

    if cursor is not None:
        new_id = _create(cursor)
    else:
        with mysql_manager.get_cursor() as cur:
            new_id = _create(cur)

    logger.info("picking request %s raised for order %s", new_id, order_id)
    return get_movement_request(new_id)


# ── Write flows — not implemented yet ────────────────────────────────────────
_NOT_BUILT = (
    "not implemented yet: the GRN / stacking / picking write flows are the next step "
    "(see api/modules/inventory/GRN_STACKING_DESIGN.md)"
)


def receive_stock(*args, **kwargs):
    """GRN: write transferin_info + upsert fc_entity_stock at location 8 (unstacked)."""
    raise NotImplementedError(_NOT_BUILT)


def adjust_stock(*args, **kwargs):
    """Adjust a bin's quantity and append the ledger entry."""
    raise NotImplementedError(_NOT_BUILT)


def complete_movement_request(*args, **kwargs):
    """Acknowledge recommendations, move stock between bins, sync the order."""
    raise NotImplementedError(_NOT_BUILT)


# ── Allocation for DMS / dispatch ────────────────────────────────────────────
def uses_live_stock(company_id):
    """True when this company's stock is held in fc_entity_stock.

    Hero's stock arrives as a periodically uploaded sheet (temp_inventory), which is why
    downloads there are gated on its freshness. A company whose stock comes from goods
    receipts has no upload step and no staleness to check — the ledger IS current — so
    the two need different handling rather than one being bent to fit the other.
    """
    return bool(mysql_manager.execute_query(
        "SELECT 1 FROM fc_entity_stock WHERE company_id = %s LIMIT 1", (company_id,)))


def allocate_live(order_items, company_id, planogram_id=None, reference_id=0,
                  reference_type='DMS', user='dms'):
    """Take `order_items` out of fc_entity_stock, earliest expiry first.

    Returns (allocated, shortfalls), mirroring temp_inventory.allocate so the caller
    treats both sources the same way.

    FEFO, not FIFO: stock is batch-tracked with an expiry, and shipping a later-expiring
    batch while an earlier one sits on the shelf is how stock is written off. Batches with
    no expiry sort last — an unknown date must not jump the queue ahead of a known one.

    Everything happens in ONE transaction with the stock rows locked, so two operators
    downloading at the same moment cannot both be promised the last pack.
    """
    codes = [it['sku_code'] for it in order_items if it.get('sku_code')]
    if not codes:
        return [], []

    allocated, shortfalls = [], []
    with mysql_manager.get_cursor() as cursor:
        ph = ','.join(['%s'] * len(codes))
        params = [company_id, *codes]
        plano_sql = ''
        if planogram_id is not None:
            plano_sql = ' AND s.planogram_id = %s'
            params.append(planogram_id)

        # Ordered by expiry so the loop below can take rows in FEFO order as it walks.
        cursor.execute(
            f"""SELECT s.id, s.entity_id, s.batch_id, s.quantity, s.planogram_id,
                       s.location_id, s.bin_id, s.entity_type, p.product_string,
                       JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.expiry')) AS expiry
                  FROM fc_entity_stock s
                  JOIN product p ON p.product_id = s.entity_id
                  LEFT JOIN sku_batch b ON b.id = s.batch_id
                 WHERE s.company_id = %s AND p.product_string IN ({ph}){plano_sql}
                   AND s.quantity > 0
                 ORDER BY p.product_string, (expiry IS NULL), expiry, s.id
                 FOR UPDATE""",
            tuple(params))

        by_code = {}
        for r in cursor.fetchall():
            by_code.setdefault(r['product_string'], []).append(r)

        for it in order_items:
            code = it.get('sku_code')
            ordered = int(it.get('quantity') or 0)
            if not code or ordered <= 0:
                continue

            remaining = ordered
            for row in by_code.get(code, []):
                if remaining <= 0:
                    break
                take = min(remaining, int(float(row['quantity'])))
                if take <= 0:
                    continue
                after = float(row['quantity']) - take

                # The row is deleted when it empties: fc_entity_stock is a live working
                # set, and a zero row is stock that is not there.
                if after <= 0:
                    cursor.execute("DELETE FROM fc_entity_stock WHERE id = %s", (row['id'],))
                else:
                    cursor.execute(
                        "UPDATE fc_entity_stock SET quantity = %s WHERE id = %s",
                        (after, row['id']))

                cursor.execute(
                    """INSERT INTO fc_entity_stock_ledger
                         (planogram_id, location_id, bin_id, entity_id, entity_type,
                          batch_id, quantity_changed, quantity_after_change, reference_id,
                          reference_type, company_id, created_by, updated_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row['planogram_id'], row['location_id'], row['bin_id'],
                     row['entity_id'], row['entity_type'], row['batch_id'],
                     -take, after, reference_id, reference_type, company_id, user, user))
                remaining -= take

            supplied = ordered - remaining
            if supplied < ordered:
                shortfalls.append({'part_number': code, 'ordered': ordered,
                                   'supplied': supplied})
            if supplied > 0:
                allocated.append(dict(it, quantity=supplied))

    logger.info("live stock allocated", extra={'company_id': company_id,
                                               'lines': len(allocated),
                                               'shortfalls': len(shortfalls)})
    return allocated, shortfalls


# ── Deduction for a closing document ─────────────────────────────────────────
class StockShortfall(Exception):
    """A closing document asks for more of a batch than is on hand."""

    def __init__(self, shortfalls):
        self.shortfalls = shortfalls
        super().__init__('; '.join(
            f"{s['product']} batch {s['batch']}: needs {s['needed']:g}, on hand {s['on_hand']:g}"
            for s in shortfalls))


def deduct_batches(cursor, lines, company_id, planogram_id, reference_id,
                   reference_type='INVOICE', user='system'):
    """Take each line's quantity out of the exact batch it names, on the caller's cursor.

    Unlike allocate_live this chooses no batches: the document being closed already says
    which batch the customer received, and FEFO would record stock leaving from a batch
    that never left.

    All-or-nothing. Every line is checked against the locked stock rows before anything is
    written, and one short line raises StockShortfall with nothing deducted, so the caller's
    transaction rolls back and the order stays open rather than closing with part of its
    stock taken. A line with no batch is a shortfall too — there is no batch to take from.

    `lines`: dicts with product_id, batch_id, quantity, and optionally label/batch_number
    for the error message. Returns the number of ledger rows written.
    """
    lines = [ln for ln in lines if float(ln.get('quantity') or 0) > 0]
    if not lines:
        return 0

    shortfalls = [{'product': ln.get('label') or ln['product_id'], 'batch': '(none)',
                   'needed': float(ln['quantity']), 'on_hand': 0.0}
                  for ln in lines if not ln.get('batch_id')]
    if shortfalls:
        raise StockShortfall(shortfalls)

    # Two lines can name the same batch; they draw on one pool.
    needed, labels = {}, {}
    for ln in lines:
        key = (int(ln['product_id']), int(ln['batch_id']))
        needed[key] = needed.get(key, 0.0) + float(ln['quantity'])
        labels[key] = (ln.get('label') or ln['product_id'], ln.get('batch_number') or ln['batch_id'])

    match = ' OR '.join(['(entity_id = %s AND batch_id = %s)'] * len(needed))
    params = [company_id]
    for product_id, batch_id in needed:
        params += [product_id, batch_id]
    plano_sql = ''
    if planogram_id is not None:
        plano_sql = ' AND planogram_id = %s'
        params.append(planogram_id)

    cursor.execute(
        f"""SELECT id, planogram_id, location_id, bin_id, entity_id, entity_type,
                   batch_id, quantity
              FROM fc_entity_stock
             WHERE company_id = %s AND ({match}){plano_sql} AND quantity > 0
             ORDER BY id
             FOR UPDATE""",
        tuple(params))
    rows_by_key = {}
    for r in cursor.fetchall():
        rows_by_key.setdefault((int(r['entity_id']), int(r['batch_id'])), []).append(r)

    for key, qty in needed.items():
        on_hand = sum(float(r['quantity']) for r in rows_by_key.get(key, []))
        if on_hand + 1e-9 < qty:
            shortfalls.append({'product': labels[key][0], 'batch': labels[key][1],
                               'needed': qty, 'on_hand': on_hand})
    if shortfalls:
        raise StockShortfall(shortfalls)

    written = 0
    for key, qty in needed.items():
        remaining = qty
        for row in rows_by_key.get(key, []):
            if remaining <= 1e-9:
                break
            take = min(remaining, float(row['quantity']))
            after = float(row['quantity']) - take
            # An emptied row is deleted: fc_entity_stock is the live working set, and a
            # zero row is stock that is not there.
            if after <= 1e-9:
                after = 0.0
                cursor.execute("DELETE FROM fc_entity_stock WHERE id = %s", (row['id'],))
            else:
                cursor.execute("UPDATE fc_entity_stock SET quantity = %s WHERE id = %s",
                               (after, row['id']))
            cursor.execute(
                """INSERT INTO fc_entity_stock_ledger
                     (planogram_id, location_id, bin_id, entity_id, entity_type,
                      batch_id, quantity_changed, quantity_after_change, reference_id,
                      reference_type, company_id, created_by, updated_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (row['planogram_id'], row['location_id'], row['bin_id'], row['entity_id'],
                 row['entity_type'], row['batch_id'], -take, after, reference_id,
                 reference_type, company_id, user, user))
            remaining -= take
            written += 1

    logger.info("batch stock deducted", extra={'company_id': company_id,
                                               'reference_type': reference_type,
                                               'reference_id': reference_id,
                                               'ledger_rows': written})
    return written
