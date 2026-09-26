# -*- encoding: utf-8 -*-
"""
Every SQL statement the packing module issues.

Packing owns no tables. It writes `entity_movement_request` (the job) and
`entity_movement_details` (boxes, SKUs-in-boxes, shortfalls) — both owned by the
inventory module and both `PARTITION BY RANGE COLUMNS(created_on)` with a PK of
`(id, created_on)`.

> **Every statement against those two tables carries `created_on`.**
> `UPDATE ... WHERE id = %s` cannot prune partitions: MySQL probes all ~13 monthly
> partitions for a single-row update. Rows this module inserted carry their exact
> `created_on` in memory, so their updates hit one partition; rows it merely reads
> fall back to the `partition_filter` window. Nothing here omits it.
> (PACKING_DESIGN.md §6.3.)

Reads that only touch order/catalogue tables are here too, so the service layer
holds business rules and nothing else.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from api.permissions import company_filter_sql
from api.shared.db_manager import mysql_manager, partition_filter
from api.shared.logging import get_logger
from api.modules.fulfillment.order.constants import OrderStatus
from api.modules.fulfillment.packing import constants as C

logger = get_logger(__name__)

# Boxes and their SKU rows both live at the delivery location — packing happens at
# the bench, not in a storage bin. Mirrored from inventory's Location master rather
# than imported: a cross-module import of another module's schema is the boundary
# rule this codebase does not break, and the id is a seeded semantic constant.
LOCATION_DELIVERY = 6


def db_now() -> datetime:
    """`utcnow()` with the microseconds removed. Mint every `created_on` here.

    `entity_movement_details.created_on` is DATETIME with **precision 0**, so MySQL
    silently truncates the fractional seconds on the way in. A caller that keeps the
    un-truncated value in memory and later says `WHERE created_on = %s` is comparing
    `…:12.837451` against the stored `…:12` and matches **nothing**.

    That failure is quiet rather than loud, which is what makes it worth a helper:
    the expected-weight aggregate reads `WHERE b.id = %s AND b.created_on = %s`, so a
    truncated-away microsecond made it return no row, and the caller's
    `else tare` fallback then weighed a full carton as an empty one — an
    8 kg understatement presented as a confident number.
    """
    return datetime.utcnow().replace(microsecond=0)


def _placeholders(values: Sequence) -> str:
    return ','.join(['%s'] * len(values))


def _loads(value: Any, default: Optional[dict] = None) -> dict:
    """Decode a JSON column that PyMySQL may hand back as str, dict or None."""
    if isinstance(value, dict):
        return value
    if not value:
        return dict(default or {})
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        logger.warning("packing: unreadable JSON document, falling back to default")
        return dict(default or {})
    return parsed if isinstance(parsed, dict) else dict(default or {})


# ── Picklists (potential_order) ──────────────────────────────────────────────

def list_picklists(warehouse_id: int, company_ids: Optional[List[int]], q: Optional[str] = None,
                   limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """The pool: orders sitting at `Picking`, newest first, plus the total.

    Search is server-side because the pool is shared and self-serve — a stale local
    copy filtered on the device sends two packers at the same picklist.
    """
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')

    where = [pf_sql, cf_sql, "po.status = %s", "po.warehouse_id = %s"]
    params: List[Any] = [*pf_params, *cf_params, OrderStatus.PICKING.value, warehouse_id]

    if q:
        term = q.strip()
        like = f"%{term}%"
        # The display id is a rendering of potential_order_id ("PL-4821"), so a
        # packer typing digits is searching the id; typing letters is searching the
        # merchant. Matching both keeps one search box honest for both habits.
        #
        # The card shows "PL-5", so that is what a packer types — and matching only
        # the bare id meant searching for the exact string on screen returned
        # nothing, which reads as "this picklist is gone" rather than "wrong search".
        # Strip the display prefix and search the id underneath it too.
        id_term = term[3:] if term[:3].upper() == 'PL-' else term
        id_like = f"%{id_term}%"
        where.append("(po.original_order_id LIKE %s OR d.name LIKE %s "
                     "OR CAST(po.potential_order_id AS CHAR) LIKE %s)")
        params += [like, like, id_like]

    clause = " AND ".join(where)
    total_rows = mysql_manager.execute_query(
        f"""SELECT COUNT(*) AS total
            FROM potential_order po
            LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
            WHERE {clause}""",
        tuple(params),
    )
    total = int(total_rows[0]['total']) if total_rows else 0

    rows = mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.company_id,
                   po.warehouse_id, po.order_date, po.status, po.dealer_id,
                   d.name AS merchant
            FROM potential_order po
            LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
            WHERE {clause}
            ORDER BY po.order_date DESC, po.potential_order_id DESC
            LIMIT %s OFFSET %s""",
        tuple(params + [limit, offset]),
    ) or []
    return {'items': rows, 'total': total}


def get_picklist(potential_order_id: int, company_ids: Optional[List[int]]) -> Optional[dict]:
    """One order header, company-scoped.

    Scope is applied here rather than in the router so a caller cannot read another
    tenant's order by guessing its id — the same reason `inventory.service` scopes
    `get_movement_request`.
    """
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    rows = mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.company_id,
                   po.warehouse_id, po.order_date, po.status, po.dealer_id,
                   po.box_count, d.name AS merchant
            FROM potential_order po
            LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
            WHERE {pf_sql} AND {cf_sql} AND po.potential_order_id = %s""",
        (*pf_params, *cf_params, potential_order_id),
    )
    return rows[0] if rows else None


def order_lines(potential_order_ids: Sequence[int]) -> List[dict]:
    """Every line of several orders with its product snapshot, in ONE query.

    Batched by design: the pool screen renders 50 picklists and a per-order query
    would be 50 round trips for one screen.
    """
    ids = [int(i) for i in dict.fromkeys(potential_order_ids or [])]
    if not ids:
        return []
    pf_sql, pf_params = partition_filter('potential_order_product', alias='pop')
    return mysql_manager.execute_query(
        f"""SELECT pop.potential_order_id, pop.product_id, pop.quantity,
                   pop.quantity_packed, pop.quantity_remaining,
                   p.product_string AS sku_code, p.name, p.barcode, p.weight
            FROM potential_order_product pop
            LEFT JOIN product p ON p.product_id = pop.product_id
            WHERE {pf_sql} AND pop.potential_order_id IN ({_placeholders(ids)})
            ORDER BY pop.potential_order_id, pop.potential_order_product_id""",
        (*pf_params, *ids),
    ) or []


def lock_order(cursor, potential_order_id: int) -> Optional[dict]:
    """Row-lock the order inside an open transaction; returns its header or None.

    This is what makes job creation safe. `entity_movement_request` has no unique
    key on `request_identifier` — it cannot have one, being partitioned — so
    `SELECT ... FOR UPDATE` on a job that does not exist yet locks nothing and two
    packers tapping the same card would each insert a job. Locking the ORDER row
    instead gives the two racers one row to queue on, which exists in every case
    including the first. (PACKING_SCREEN_API_CONTRACTS.md §6.1.)
    """
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    # `FOR UPDATE OF po` — not a bare FOR UPDATE. The dealer is joined only to
    # carry its name into the job response (the packing screen heads itself with
    # the merchant and never re-reads the picklist), and locking it as well would
    # make two packers claiming two different orders for the same dealer queue on
    # each other for no reason.
    cursor.execute(
        f"""SELECT po.potential_order_id, po.company_id, po.warehouse_id,
                   po.dealer_id, po.status, d.name AS merchant
            FROM potential_order po
            LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
            WHERE {pf_sql} AND po.potential_order_id = %s
            FOR UPDATE OF po""",
        (*pf_params, potential_order_id),
    )
    rows = cursor.fetchall()
    return rows[0] if rows else None


def short_reasons() -> List[dict]:
    """The one shared shortfall list — `entity_movement_details.underpick_reason_id`
    resolves against it for packing exactly as it does for stacking."""
    return mysql_manager.execute_query(
        "SELECT id AS reason_id, reason FROM understack_reason WHERE is_active = 1 ORDER BY id"
    ) or []


def reason_exists(reason_id: int) -> bool:
    rows = mysql_manager.execute_query(
        "SELECT 1 FROM understack_reason WHERE id = %s AND is_active = 1", (reason_id,)
    )
    return bool(rows)


# ── Catalogue resolution ─────────────────────────────────────────────────────

def products_for_codes(codes: Iterable[str]) -> Dict[str, dict]:
    """{code: product row} for a batch of scanned part numbers, in ONE query.

    Resolution is extract-then-seek. NEVER search for the whole scanned string in
    `product`: the composite code equals no `barcode` value, so a `LIKE '%...%'`
    or a catalogue scan is the only way it could ever "work" — on 60k rows that is
    exactly the expensive search to avoid. The extracted part number hits
    `idx_product_string` or `uq_product_barcode` as a plain equality seek.
    A batch of 20 scans of one SKU costs one seek, not twenty (design §6.7.6).
    """
    wanted = [c for c in dict.fromkeys(codes or []) if c]
    if not wanted:
        return {}
    ph = _placeholders(wanted)
    rows = mysql_manager.execute_query(
        f"""SELECT product_id, product_string, name, barcode, weight, company_id
            FROM product
            WHERE product_string IN ({ph}) OR barcode IN ({ph})""",
        (*wanted, *wanted),
    ) or []

    resolved: Dict[str, dict] = {}
    for row in rows:
        # product_string wins over barcode when both match different rows: the
        # printed part number is what the label's product field carries, and the
        # barcode column is the fallback for catalogues that never populated it.
        if row.get('product_string'):
            resolved.setdefault(row['product_string'], row)
    for row in rows:
        if row.get('barcode'):
            resolved.setdefault(row['barcode'], row)
    return {code: resolved[code] for code in wanted if code in resolved}


def uom_rung(product_id: int, factor_to_base) -> Optional[dict]:
    """The packaging rung whose `factor_to_base` matches the scanned quantity.

    This is how the scanned pack is identified with no new barcode field: §6.7
    established the printed labels carry no pack-level indicator, so field 5
    (`000001` vs `000200`) is what picks the retail rung out of the ladder from the
    wholesale one — and the same row carries that rung's `pack_tare_kg`.
    """
    rows = mysql_manager.execute_query(
        """SELECT product_uom_id, uom_code, factor_to_base, level_no, pack_tare_kg
           FROM product_uom
           WHERE product_id = %s AND factor_to_base = %s
           ORDER BY level_no LIMIT 1""",
        (product_id, factor_to_base),
    )
    return rows[0] if rows else None


# ── entity_movement_request — the packing job ────────────────────────────────

_JOB_COLS = """id AS request_id, planogram_id, company_id, movement_type, request_status,
               request_identifier, reference_type, metadata, created_by_id, created_on,
               updated_by_id, updated_on"""


def find_job(potential_order_id: int, cursor=None, for_update: bool = False) -> Optional[dict]:
    """The packing job for an order, if one exists. `metadata` comes back decoded."""
    pf_sql, pf_params = partition_filter('entity_movement_request')
    sql = f"""SELECT {_JOB_COLS}
              FROM entity_movement_request
              WHERE {pf_sql} AND movement_type = %s AND reference_type = 'ORDER'
                AND request_identifier = %s
              ORDER BY id DESC LIMIT 1"""
    if for_update:
        sql += " FOR UPDATE"
    params = (*pf_params, C.MovementType.PACKING, potential_order_id)

    if cursor is not None:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    else:
        rows = mysql_manager.execute_query(sql, params)
    if not rows:
        return None
    job = rows[0]
    job['metadata'] = _loads(job.get('metadata'))
    return job


def jobs_for_orders(potential_order_ids: Sequence[int]) -> Dict[int, dict]:
    """{potential_order_id: job} for the pool screen, in ONE query."""
    ids = [int(i) for i in dict.fromkeys(potential_order_ids or [])]
    if not ids:
        return {}
    pf_sql, pf_params = partition_filter('entity_movement_request')
    rows = mysql_manager.execute_query(
        f"""SELECT {_JOB_COLS}
            FROM entity_movement_request
            WHERE {pf_sql} AND movement_type = %s AND reference_type = 'ORDER'
              AND request_identifier IN ({_placeholders(ids)})
            ORDER BY id""",
        (*pf_params, C.MovementType.PACKING, *ids),
    ) or []
    out: Dict[int, dict] = {}
    for row in rows:
        row['metadata'] = _loads(row.get('metadata'))
        out[int(row['request_identifier'])] = row   # last (highest id) wins
    return out


def get_job(request_id: int) -> Optional[dict]:
    pf_sql, pf_params = partition_filter('entity_movement_request')
    rows = mysql_manager.execute_query(
        f"SELECT {_JOB_COLS} FROM entity_movement_request WHERE {pf_sql} AND id = %s",
        (*pf_params, request_id),
    )
    if not rows:
        return None
    job = rows[0]
    job['metadata'] = _loads(job.get('metadata'))
    return job


def insert_job(cursor, planogram_id: int, company_id: Optional[int], potential_order_id: int,
               metadata: dict, user_id: int, created_on: datetime) -> int:
    """Create the job header and return its id.

    `created_on` is supplied rather than defaulted so the caller keeps the exact
    value in memory: every later UPDATE of this row needs it to hit one partition
    instead of probing thirteen.
    """
    cursor.execute(
        """INSERT INTO entity_movement_request
             (planogram_id, company_id, movement_type, request_status, meta_info,
              created_by_id, updated_by_id, request_identifier, reference_type,
              metadata, created_on)
           VALUES (%s, %s, %s, %s, '', %s, %s, %s, 'ORDER', %s, %s)""",
        (planogram_id, company_id, C.MovementType.PACKING, C.RequestStatus.CREATED,
         user_id, user_id, potential_order_id, json.dumps(metadata), created_on),
    )
    return cursor.lastrowid


def update_job(cursor, request_id: int, created_on: datetime, user_id: int,
               request_status: Optional[str] = None,
               metadata: Optional[dict] = None) -> None:
    """Patch the job header. `created_on` is mandatory — it is the partition key."""
    sets, params = ["updated_by_id = %s", "updated_on = %s"], [user_id, datetime.utcnow()]
    if request_status is not None:
        sets.append("request_status = %s")
        params.append(request_status)
    if metadata is not None:
        sets.append("metadata = %s")
        params.append(json.dumps(metadata))
    cursor.execute(
        f"UPDATE entity_movement_request SET {', '.join(sets)} "
        f"WHERE id = %s AND created_on = %s",
        (*params, request_id, created_on),
    )


# ── entity_movement_details — boxes, SKUs-in-boxes and shortfalls ────────────

_DETAIL_COLS = """id AS detail_id, request_id, company_id, entity_id, entity_type,
                  source_bin_id, source_location_id, picked_quantity,
                  tare_weight_kg, weight_kg, expected_weight_kg, variance_g,
                  underpick_reason_id, source_stock_info, created_by_id, created_on,
                  updated_on"""


def boxes_for_job(request_id: int) -> List[dict]:
    """Every box row on a job, oldest first, with its JSON decoded.

    Served by the existing `request_id` key. A job holds at most
    MAX_BOXES_PER_PICKLIST boxes, so this is deliberately unpaged — the callers
    all need the whole set to answer "is anything still open".
    """
    pf_sql, pf_params = partition_filter('entity_movement_details')
    rows = mysql_manager.execute_query(
        f"""SELECT {_DETAIL_COLS} FROM entity_movement_details
            WHERE {pf_sql} AND request_id = %s AND entity_type = %s
            ORDER BY id""",
        (*pf_params, request_id, C.EntityType.BOX),
    ) or []
    for row in rows:
        row['box_info'] = _loads(row.get('source_stock_info'))
    return rows


def get_box(box_id: int) -> Optional[dict]:
    pf_sql, pf_params = partition_filter('entity_movement_details')
    rows = mysql_manager.execute_query(
        f"""SELECT {_DETAIL_COLS} FROM entity_movement_details
            WHERE {pf_sql} AND id = %s AND entity_type = %s""",
        (*pf_params, box_id, C.EntityType.BOX),
    )
    if not rows:
        return None
    box = rows[0]
    box['box_info'] = _loads(box.get('source_stock_info'))
    return box


def label_owner(label_code: str) -> Optional[dict]:
    """Which box already carries this label, if any — the single-use check (D6).

    An application check over `idx_emd_entity`, not a UNIQUE constraint: EMD is
    partitioned, and MySQL requires the partition column in every unique index, so
    a global `UNIQUE(entity_id)` is impossible and one including `created_on` would
    only be unique per month. That is sufficient — there is exactly one physical
    sticker, so two packers cannot bind the same label at the same instant.

    `entity_id = ''` (a box between insert and bind) can never reach here because
    the caller only ever passes a real scanned code.
    """
    pf_sql, pf_params = partition_filter('entity_movement_details', alias='d')
    rows = mysql_manager.execute_query(
        f"""SELECT d.id AS detail_id, d.request_id, r.request_identifier
            FROM entity_movement_details d
            LEFT JOIN entity_movement_request r ON r.id = d.request_id
            WHERE {pf_sql} AND d.entity_id = %s AND d.entity_type = %s
            LIMIT 1""",
        (*pf_params, label_code, C.EntityType.BOX),
    )
    return rows[0] if rows else None


def sku_rows_in_boxes(request_id: int, box_ids: Sequence[int]) -> List[dict]:
    """SKU rows sitting in the given boxes, in ONE query.

    Callers pass the boxes they consider live (abandoned boxes excluded), so the
    "is it abandoned" decision stays in the service where the JSON is understood
    rather than becoming a `LIKE '%abandoned%'` over a TEXT column.
    Served by `idx_request_source (request_id, source_bin_id)`.
    """
    ids = [int(b) for b in dict.fromkeys(box_ids or [])]
    if not ids:
        return []
    pf_sql, pf_params = partition_filter('entity_movement_details')
    return mysql_manager.execute_query(
        f"""SELECT {_DETAIL_COLS} FROM entity_movement_details
            WHERE {pf_sql} AND request_id = %s AND entity_type = %s
              AND source_bin_id IN ({_placeholders(ids)})
            ORDER BY source_bin_id, id""",
        (*pf_params, request_id, C.EntityType.SKU, *ids),
    ) or []


def short_rows_for_job(request_id: int) -> List[dict]:
    """Shortfall rows — SKU rows in no box (`source_bin_id = 0`)."""
    pf_sql, pf_params = partition_filter('entity_movement_details')
    return mysql_manager.execute_query(
        f"""SELECT {_DETAIL_COLS} FROM entity_movement_details
            WHERE {pf_sql} AND request_id = %s AND entity_type = %s AND source_bin_id = %s
            ORDER BY id""",
        (*pf_params, request_id, C.EntityType.SKU, C.NO_BOX),
    ) or []


def sealed_box_counts(request_ids: Sequence[int]) -> Dict[int, int]:
    """{request_id: sealed box count} for the pool screen, in ONE query.

    A sealed box is one with a recorded `weight_kg` — the column is only written at
    close, so it doubles as the seal marker without parsing any JSON.
    """
    ids = [int(i) for i in dict.fromkeys(request_ids or [])]
    if not ids:
        return {}
    pf_sql, pf_params = partition_filter('entity_movement_details')
    rows = mysql_manager.execute_query(
        f"""SELECT request_id, COUNT(*) AS sealed
            FROM entity_movement_details
            WHERE {pf_sql} AND request_id IN ({_placeholders(ids)})
              AND entity_type = %s AND weight_kg IS NOT NULL
            GROUP BY request_id""",
        (*pf_params, *ids, C.EntityType.BOX),
    ) or []
    return {int(r['request_id']): int(r['sealed']) for r in rows}


def expected_weight_kg(box_id: int, box_created_on: datetime, cursor=None) -> Optional[float]:
    """`tare + SUM(unit weight x quantity)` for one box — ONE SQL aggregate.

    **This is the anti-fraud number.** It is recomputed here, from the unit weights
    snapshotted onto each SKU row when they were written, and never from anything
    the client sent. The snapshot is what makes a box's arithmetic reproducible: if
    `product.weight` is corrected next month — a routine master-data fix — a live
    join would silently re-derive a different expected weight for every historical
    box, and boxes that passed would start reading as mismatches.
    (PACKING_DESIGN.md §4.5, §6.1.)

    `cursor` must be passed when the SKU rows being weighed were written by the
    same still-uncommitted transaction — a second pooled connection cannot see
    them, and would silently weigh an empty box.
    """
    pf_sql, pf_params = partition_filter('entity_movement_details', alias='s')
    sql = f"""SELECT b.tare_weight_kg
                   + COALESCE(SUM(s.weight_kg * s.picked_quantity), 0) AS expected_kg
              FROM      entity_movement_details b
              LEFT JOIN entity_movement_details s
                     ON s.request_id = b.request_id AND s.source_bin_id = b.id
                    AND s.entity_type = %s AND {pf_sql}
              WHERE b.id = %s AND b.created_on = %s
              GROUP BY b.id, b.tare_weight_kg"""
    params = (C.EntityType.SKU, *pf_params, box_id, box_created_on)
    if cursor is not None:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    else:
        rows = mysql_manager.execute_query(sql, params)
    return float(rows[0]['expected_kg']) if rows and rows[0]['expected_kg'] is not None else None


def insert_detail(cursor, request_id: int, company_id: Optional[int], entity_id: str,
                  entity_type: str, source_bin_id: int, picked_quantity, user_id: int,
                  created_on: datetime, source_stock_info: str = '{}',
                  tare_weight_kg=None, weight_kg=None, expected_weight_kg_=None,
                  variance_g=None, underpick_reason_id: int = 0) -> int:
    """Insert one EMD row (box, SKU-in-box or shortfall) and return its id.

    `created_on` is passed in, not defaulted, for the same reason as on the job
    header: the caller keeps it and every later UPDATE of this row prunes to one
    partition.
    """
    cursor.execute(
        """INSERT INTO entity_movement_details
             (request_id, company_id, entity_id, entity_type, source_bin_id,
              source_location_id, picked_quantity, tare_weight_kg, weight_kg,
              expected_weight_kg, variance_g, underpick_reason_id, source_stock_info,
              created_by_id, updated_by_id, created_on)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (request_id, company_id, entity_id, entity_type, source_bin_id,
         LOCATION_DELIVERY, picked_quantity, tare_weight_kg, weight_kg,
         expected_weight_kg_, variance_g, underpick_reason_id, source_stock_info,
         user_id, user_id, created_on),
    )
    return cursor.lastrowid


def update_detail(cursor, detail_id: int, created_on: datetime, user_id: int,
                  entity_id: Optional[str] = None, picked_quantity=None,
                  source_stock_info: Optional[str] = None, weight_kg=None,
                  expected_weight_kg_=None, variance_g=None,
                  underpick_reason_id: Optional[int] = None) -> None:
    """Patch one EMD row. `created_on` is mandatory — it is the partition key.

    Only the fields passed are written, so a scan batch updating a quantity does not
    also rewrite the audit JSON it did not touch.
    """
    sets, params = ["updated_by_id = %s", "updated_on = %s"], [user_id, datetime.utcnow()]
    for column, value in (('entity_id', entity_id),
                          ('picked_quantity', picked_quantity),
                          ('source_stock_info', source_stock_info),
                          ('weight_kg', weight_kg),
                          ('expected_weight_kg', expected_weight_kg_),
                          ('variance_g', variance_g),
                          ('underpick_reason_id', underpick_reason_id)):
        if value is not None:
            sets.append(f"{column} = %s")
            params.append(value)
    cursor.execute(
        f"UPDATE entity_movement_details SET {', '.join(sets)} "
        f"WHERE id = %s AND created_on = %s",
        (*params, detail_id, created_on),
    )


def bind_label(cursor, detail_id: int, created_on: datetime, label_code: str,
               source_stock_info: str, user_id: int) -> int:
    """Write the scanned label into `entity_id`, but only while it is still blank.

    The `entity_id = ''` guard is the concurrency check the missing UNIQUE key
    cannot provide: two binds racing on one box row means exactly one UPDATE
    matches, and the loser sees `rowcount = 0` and is told the box is already bound
    rather than silently overwriting a label that is already on a carton.
    """
    cursor.execute(
        """UPDATE entity_movement_details
              SET entity_id = %s, source_stock_info = %s, updated_by_id = %s, updated_on = %s
            WHERE id = %s AND created_on = %s AND entity_id = ''""",
        (label_code, source_stock_info, user_id, datetime.utcnow(), detail_id, created_on),
    )
    return cursor.rowcount
