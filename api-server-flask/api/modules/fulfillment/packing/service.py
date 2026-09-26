# -*- encoding: utf-8 -*-
"""
packing module — service layer. Every rule that must survive a modified client.

The handheld enforces the same rules locally, and it has to: the Bluetooth scale
is paired to the Zebra, so the live red/green reconciliation runs on the device on
every scale sample and no round trip could make it arrive sooner. But a client-side
lock is a suggestion — a modified APK, a replayed request or a hand-rolled HTTP
call seals any box. The rules that matter therefore live here, and this layer
treats the client as an untrusted reporter of physical events:

  * **Quantity comes from the server's own parse of `raw`**, never from a client
    field. A code says how many units it is; that value is what a modified client
    would inflate first (PACKING_DESIGN.md §6.7.1).
  * **The tolerance check recomputes `expected` from snapshotted unit weights** as
    one SQL aggregate, and ignores any client-supplied expected value (§6.1).
  * **Routing is validated on both sides** — `/scans` rejects a carton code and
    `/cartons` rejects a retail code, so 200 units cannot be absorbed into a
    hand-built box whose weight the client then controls (§6.8.3).
  * **The shortfall is derived, never declared.** Submit computes
    `quantity - quantity_packed` from the job's own rows (§6.10.1).

Domain errors are raised here and mapped to HTTP codes by `router_v1`, mirroring
`inventory/service.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from api.shared.auth_v1 import company_scope
from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.modules.fulfillment.order.constants import OrderStatus
from api.modules.fulfillment.packing import constants as C
from api.modules.fulfillment.packing import events as packing_events
from api.modules.fulfillment.packing import repository as repo
from api.modules.fulfillment.packing.barcode import BarcodeFormat, ParsedCode, parse

logger = get_logger(__name__)

DEFAULT_PLANOGRAM_ID = 1


def _order_service():
    """The order module's service, imported on first use.

    Deliberately lazy. `order/service.py` is also the order UPLOAD service, so
    importing it at module level drags pandas, chardet and the whole upload pipeline
    into every process that merely wants to serve `/packing/config`. Only `/submit`
    needs it, and only when a job actually finishes.
    """
    from api.modules.fulfillment.order import service as order_service
    return order_service


# ── Domain errors (routers map these to HTTP codes) ──────────────────────────
class PackingError(Exception):
    """Base for every business rejection.

    Carries a machine-readable `code` and an optional `payload` because the app
    switches on the code and, for `shortfall_requires_ack` and `weight_mismatch`,
    renders its dialog from numbers only the server can compute. Putting them on
    the exception keeps the router a pure translation layer.
    """

    def __init__(self, detail: str, code: Optional[str] = None,
                 payload: Optional[dict] = None):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.payload = payload or {}

    def body(self) -> dict:
        out = {"detail": self.detail}
        if self.code:
            out["code"] = self.code
        out.update(self.payload)
        return out


class ValidationError(PackingError):
    """422 — the request cannot be interpreted or breaks an input rule."""


class NotFoundError(PackingError):
    """404 — no such row, or it is outside the caller's company scope. The two are
    deliberately the same answer: distinguishing them lets a caller probe for
    other tenants' order ids."""


class ConflictError(PackingError):
    """409 — the request is well-formed but the world is not in the required state."""


class _SealRejected(Exception):
    """Internal: the tolerance check failed, so the close transaction must roll
    back before the rejection is recorded. Never escapes this module."""

    def __init__(self, expected_kg: float, sealed_kg: float, variance_g: int):
        super().__init__("weight mismatch")
        self.expected_kg = expected_kg
        self.sealed_kg = sealed_kg
        self.variance_g = variance_g


# ── Small helpers ────────────────────────────────────────────────────────────

def planogram_for_warehouse(warehouse_id: Optional[int]) -> int:
    """Planogram is 1:1 with a warehouse/FC; defaults to 1, as inventory does."""
    return int(warehouse_id or DEFAULT_PLANOGRAM_ID)


def display_id(potential_order_id: int) -> str:
    """`PL-4821`. A rendering of `potential_order_id`, not an id of its own — there
    is no picklist entity and no second id space (design D1)."""
    return f"PL-{potential_order_id}"


def _num(value) -> Optional[float]:
    return float(value) if value is not None else None


def _kg(value) -> float:
    """Round to the scale's resolution. DECIMAL(12,3) is the column, and letting a
    float's tail through would make two identical weights compare unequal."""
    return round(float(value or 0), 3)


def _unit_kg(line_or_product) -> Optional[float]:
    """One unit's weight in KILOGRAMS, from a product/line row.

    `product.weight` is in grams (see C.PRODUCT_WEIGHT_PER_KG for the evidence).
    Every weight this module compares against a scale is kilograms, so the
    conversion happens here — once — and no call site is left to remember it.
    """
    if line_or_product is None:
        return None
    raw = line_or_product.get('weight')
    if raw is None:
        return None
    return float(raw) / C.PRODUCT_WEIGHT_PER_KG


def _units(value) -> int:
    """A count of physical items, as an integer.

    `picked_quantity` is DECIMAL(16,4) because the movement engine also carries
    weight-based stock, so pymysql hands back a Decimal and every quantity went out
    as `202.0`. Packing counts discrete things — you cannot pack half a spark plug —
    and the app's models type these as `int`, which a JSON double does not satisfy:
    the client throws when it parses the response rather than when anyone made the
    mistake. Coerce at the point the number is produced, not at the wire, so the
    types are right for internal callers too.
    """
    return int(round(float(value or 0)))


def _grams(kg_delta: float) -> int:
    return int(round(kg_delta * C.G_PER_KG))


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _user_id(current_user: dict) -> int:
    return int(current_user.get('user_id') or 0)


def _scope(current_user: dict) -> Optional[List[int]]:
    return company_scope(current_user)


def _weight_verifiable(unit_weight_kg: Optional[float], quantity: float = 1) -> bool:
    """Can the scale prove this line is present?

    Applied to `quantity x unit weight`, not to the unit weight alone: 200 units of
    a 5 g part is a kilogram and highly verifiable, even though one of them is not
    (design §6.7.2). A SKU with no unit weight is never verifiable — saying so beats
    letting everyone downstream believe a box of 5 g hinges passed a real check.
    """
    if not unit_weight_kg or unit_weight_kg <= 0:
        return False
    return (unit_weight_kg * max(quantity, 1)) * C.G_PER_KG >= C.WEIGHT_VERIFY_FLOOR_G


def _new_box_info(box_no: int, tolerance_g: int, kind: str, packed_by: int,
                  status: str, captured_at: Optional[str]) -> dict:
    """The box row's `source_stock_info` document at creation.

    `v` is a schema version: a JSON document living in a TEXT column changes shape
    over its life, and without a marker the reader has to guess which shape it holds.
    """
    return {
        "v": C.JSON_SCHEMA_VERSION,
        "box_no": box_no,
        "kind": kind,
        "status": status,
        "tolerance_g": tolerance_g,
        "packed_by": packed_by,
        "tare_at": captured_at,
        "bound_at": None,
        "sealed_at": None,
        # A deliberate summary block. It is the part a future reporting job can
        # extract cheaply without parsing every scans[] array (design §5).
        "flags": {"reject_scans": 0, "seal_attempts": 0, "max_variance_g": 0,
                  "scans_truncated": 0},
        "scans": [],
        "weight_events": [],
    }


def _dump_box_info(info: dict) -> str:
    """Serialise the box document, truncating the scan trail if it would overflow.

    `source_stock_info` is TEXT — 65,535 bytes — and a 350-unit box approaches it.
    Past the budget the OLDEST scans are dropped and `flags.scans_truncated` is set.
    `weight_events` and `flags` are never touched: they carry the fraud signal.

    **This never raises and never fails a close.** A packer blocked from sealing a
    physically correct box because an audit field overflowed is a worse outcome
    than a shortened trail (design §5).
    """
    payload = json.dumps(info, default=str)
    if len(payload.encode('utf-8')) <= C.SOURCE_STOCK_INFO_MAX_BYTES:
        return payload

    scans = list(info.get('scans') or [])
    dropped = 0
    while scans and len(payload.encode('utf-8')) > C.SOURCE_STOCK_INFO_MAX_BYTES:
        # Drop in blocks: re-serialising per removed entry on a 5,000-scan trail is
        # thousands of dumps for one close.
        cut = max(1, len(scans) // 10)
        del scans[:cut]
        dropped += cut
        info = dict(info, scans=scans)
        payload = json.dumps(info, default=str)

    flags = dict(info.get('flags') or {})
    flags['scans_truncated'] = int(flags.get('scans_truncated') or 0) + dropped
    info = dict(info, flags=flags)
    logger.warning("packing: box trail truncated", extra={'dropped_scans': dropped})
    return json.dumps(info, default=str)


def _live_boxes(boxes: Sequence[dict]) -> List[dict]:
    """Boxes that still count towards the order.

    An abandoned box keeps every row and its whole trail — nothing is ever deleted,
    because a box abandoned right after a weight mismatch is exactly the pattern
    worth being able to see — but its contents are physically back on the bench and
    must not be counted as packed.
    """
    return [b for b in boxes
            if (b.get('box_info') or {}).get('status') != C.BoxStatus.ABANDONED]


def _open_boxes(boxes: Sequence[dict]) -> List[dict]:
    return [b for b in boxes
            if (b.get('box_info') or {}).get('status') in (C.BoxStatus.SETUP, C.BoxStatus.OPEN)]


def _sealed_boxes(boxes: Sequence[dict]) -> List[dict]:
    return [b for b in boxes
            if (b.get('box_info') or {}).get('status') == C.BoxStatus.SEALED]


def _packed_by_product(request_id: int, boxes: Sequence[dict]) -> Dict[int, float]:
    """{product_id: base units packed} across the job's live boxes.

    Two queries regardless of box count — the box rows are already in hand and
    their SKU rows come back in one `source_bin_id IN (...)` seek over
    `idx_request_source`.
    """
    live = _live_boxes(boxes)
    if not live:
        return {}
    totals: Dict[int, float] = {}
    for row in repo.sku_rows_in_boxes(request_id, [b['detail_id'] for b in live]):
        product_id = _product_id(row)
        if product_id is None:
            continue
        totals[product_id] = totals.get(product_id, 0.0) + float(row['picked_quantity'] or 0)
    return totals


def _line_index(lines: Sequence[dict]) -> Tuple[Dict[int, dict], Dict[str, dict]]:
    """(by product_id, by sku_code) for the order's lines.

    The code index is what makes scanning cost zero catalogue lookups in the steady
    state: a scanned part number is almost always on the picklist already
    (design §6.7.6).
    """
    by_id = {int(l['product_id']): l for l in lines if l.get('product_id') is not None}
    by_code = {}
    for line in lines:
        if line.get('sku_code'):
            by_code[str(line['sku_code'])] = line
        if line.get('barcode'):
            by_code.setdefault(str(line['barcode']), line)
    return by_id, by_code


def _job_totals(lines: Sequence[dict], packed: Dict[int, float]) -> Dict[str, int]:
    """Job-level unit counts. Integers — see [_units]; these reach the app's
    `int` fields and flow into most other responses through this one function."""
    required = sum(float(l['quantity'] or 0) for l in lines)
    packed_units = sum(packed.values())
    return {
        "required": _units(required),
        "packed": _units(packed_units),
        "short": _units(max(required - packed_units, 0)),
    }


def _require_job_writable(job: dict) -> None:
    status = job['request_status']
    if status in C.RequestStatus.TERMINAL_STATUSES:
        raise ConflictError(
            f"{display_id(int(job['request_identifier']))} has already been submitted.",
            C.ErrorCode.JOB_ALREADY_SUBMITTED)


def _load_job_or_404(request_id: int, current_user: dict) -> dict:
    job = repo.get_job(request_id)
    if not job or job['movement_type'] != C.MovementType.PACKING:
        raise NotFoundError(f"packing job {request_id} not found")
    order = repo.get_picklist(int(job['request_identifier']), _scope(current_user))
    if not order:
        # Scope is enforced through the order, not the job: EMR carries company_id
        # but it is nullable on rows written before the tenant column landed, and a
        # NULL must not read as "everyone's".
        raise NotFoundError(f"packing job {request_id} not found")
    job['order'] = order
    return job


def _load_box_or_404(box_id: int, current_user: dict) -> Tuple[dict, dict]:
    box = repo.get_box(box_id)
    if not box:
        raise NotFoundError(f"box {box_id} not found")
    job = _load_job_or_404(int(box['request_id']), current_user)
    return box, job


# ── SCREEN 3 — config ────────────────────────────────────────────────────────

def config_payload(warehouse_id: int) -> dict:
    """Every operational threshold, read from app config rather than a table.

    Tuning tolerance is therefore a config redeploy — which leaves a trace in the
    deployment history — not an UPDATE someone can run against a row (§6.4).
    """
    return {
        "warehouse_id": warehouse_id,
        "tolerance_g": C.TOLERANCE_G,
        "gross_overage_multiplier": C.GROSS_OVERAGE_MULTIPLIER,
        "settle_window_ms": C.SETTLE_WINDOW_MS,
        "weight_verify_floor_g": C.WEIGHT_VERIFY_FLOOR_G,
        "scan_batch_size": C.SCAN_BATCH_SIZE,
        "scan_flush_ms": C.SCAN_FLUSH_MS,
        "max_boxes_per_picklist": C.MAX_BOXES_PER_PICKLIST,
        "alert_volume": C.ALERT_VOLUME,
        "alert_repeat_ms": C.ALERT_REPEAT_MS,
        "barcode_format": BarcodeFormat.from_config().as_dict(),
    }


# ── SCREENS 4 & 5 — the picklist pool ────────────────────────────────────────

def list_picklists(current_user: dict, warehouse_id: int, q: Optional[str] = None,
                   limit: int = 50, offset: int = 0) -> dict:
    """The pool of orders at `Picking`, with each one's packing progress.

    Four queries for the whole screen regardless of page size: the pool, its lines,
    the jobs, the sealed-box counts. A per-order query would be 50 round trips.
    """
    page = repo.list_picklists(warehouse_id, _scope(current_user), q, limit, offset)
    orders = page['items']
    if not orders:
        return {"items": [], "total": page['total']}

    order_ids = [int(o['potential_order_id']) for o in orders]
    lines_by_order: Dict[int, List[dict]] = {}
    for line in repo.order_lines(order_ids):
        lines_by_order.setdefault(int(line['potential_order_id']), []).append(line)

    jobs = repo.jobs_for_orders(order_ids)
    sealed = repo.sealed_box_counts([int(j['request_id']) for j in jobs.values()])

    items = []
    for order in orders:
        order_id = int(order['potential_order_id'])
        lines = lines_by_order.get(order_id, [])
        job = jobs.get(order_id)
        totals = (job or {}).get('metadata', {}).get('totals') or {}
        items.append({
            "potential_order_id": order_id,
            "display_id": display_id(order_id),
            "merchant": order.get('merchant'),
            "company_id": order.get('company_id'),
            "warehouse_id": order.get('warehouse_id'),
            "sku_count": len(lines),
            "total_units": sum(int(l['quantity'] or 0) for l in lines),
            # Computed here, once, so there is a single definition of the
            # arithmetic the fraud check later depends on.
            #
            # Includes the box tare, per requirements §3.3 ("carton tare + Sum(unit
            # weight x required qty)"). It is what the packer sanity-checks the
            # loaded box against, so leaving the carton out would read low by the
            # weight of the thing they are looking at.
            "estimated_weight_kg": _kg(C.DEFAULT_BOX_TARE_KG
                                       + sum(float(l['quantity'] or 0) * (_unit_kg(l) or 0)
                                             for l in lines)),
            "default_box_tare_kg": C.DEFAULT_BOX_TARE_KG,
            "state": "resume" if job and job['request_status'] in C.RequestStatus.OPEN_STATUSES
                     else "pending",
            "packed_units": _units(totals.get('packed')),
            "request_id": int(job['request_id']) if job else None,
            "boxes_sealed": sealed.get(int(job['request_id']), 0) if job else 0,
            "weight_verifiable": bool(lines) and all(
                _weight_verifiable(_unit_kg(l), float(l['quantity'] or 1)) for l in lines),
            "order_date": _iso(order.get('order_date')),
        })
    return {"items": items, "total": page['total']}


def _line_out(line: dict, packed_now: Optional[float] = None) -> dict:
    required = int(line['quantity'] or 0)
    packed = int(packed_now) if packed_now is not None else int(line['quantity_packed'] or 0)
    return {
        "sku_code": line.get('sku_code'),
        "product_id": int(line['product_id']) if line.get('product_id') is not None else None,
        "name": line.get('name'),
        "barcode": line.get('barcode'),
        "unit_weight_kg": _unit_kg(line),
        "quantity_required": required,
        "quantity_packed": packed,
        "quantity_remaining": max(required - packed, 0),
        "weight_verifiable": _weight_verifiable(_unit_kg(line), max(required, 1)),
    }


def _box_out(box: dict, with_items: bool = False,
             sku_rows: Optional[Sequence[dict]] = None,
             codes: Optional[Dict[int, str]] = None) -> dict:
    info = box.get('box_info') or {}
    out = {
        "box_id": int(box['detail_id']),
        "box_no": info.get('box_no'),
        "kind": info.get('kind', C.BoxKind.BUILT),
        "label_code": box['entity_id'] or None,
        "status": info.get('status'),
        "units": _units(box['picked_quantity']),
        "tare_kg": _num(box['tare_weight_kg']),
        "sealed_kg": _num(box['weight_kg']),
        "expected_kg": _num(box['expected_weight_kg']),
        "variance_g": box['variance_g'],
        "within_tolerance": info.get('within_tolerance'),
        "sealed_at": info.get('sealed_at'),
    }
    if with_items:
        codes = codes or {}
        out['items'] = [{
            "sku_code": codes.get(_product_id(r)),
            "quantity": _units(r['picked_quantity']),
        } for r in (sku_rows or []) if str(r['source_bin_id']) == str(box['detail_id'])]
    return out


def _product_id(row: dict) -> Optional[int]:
    """The numeric product id off a SKU row's VARCHAR `entity_id`.

    None rather than an exception for anything non-numeric: `entity_id` is
    polymorphic and a row this module did not write is not ours to interpret — but a
    read endpoint must not 500 because one row in a job looks unfamiliar.
    """
    try:
        return int(row['entity_id'])
    except (KeyError, TypeError, ValueError):
        return None


def get_picklist_detail(current_user: dict, potential_order_id: int) -> dict:
    """The pre-flight read behind a tapped card, before any job exists.

    404 both for an unknown order and for one outside the caller's scope or past
    `Picking` — the same body either way, so the endpoint cannot be used to probe
    for other tenants' order ids.
    """
    order = repo.get_picklist(potential_order_id, _scope(current_user))
    if not order or order['status'] != OrderStatus.PICKING.value:
        raise NotFoundError(f"picklist {potential_order_id} not found")

    lines = repo.order_lines([potential_order_id])
    job = repo.find_job(potential_order_id)
    boxes = repo.boxes_for_job(int(job['request_id'])) if job else []
    packed = _packed_by_product(int(job['request_id']), boxes) if job else {}

    payload = {
        "potential_order_id": potential_order_id,
        "display_id": display_id(potential_order_id),
        "merchant": order.get('merchant'),
        "company_id": order.get('company_id'),
        "warehouse_id": order.get('warehouse_id'),
        "status": order['status'],
        "default_box_tare_kg": C.DEFAULT_BOX_TARE_KG,
        "tolerance_g": (job or {}).get('metadata', {}).get('tolerance_g', C.TOLERANCE_G),
        "items": [_line_out(l, packed.get(int(l['product_id']), 0) if job else None)
                  for l in lines],
        "job": None,
        "boxes": [_box_out(b) for b in boxes],
    }
    if job:
        totals = _job_totals(lines, packed)
        payload['job'] = {
            "request_id": int(job['request_id']),
            "request_status": job['request_status'],
            "box_seq": job['metadata'].get('box_seq', len(boxes)),
            "packed_units": totals['packed'],
            "total_units": totals['required'],
            "tolerance_g": job['metadata'].get('tolerance_g', C.TOLERANCE_G),
            "last_packer": job['metadata'].get('last_packer'),
            "updated_on": _iso(job.get('updated_on')),
        }
    return payload


def list_short_reasons() -> dict:
    return {"items": repo.short_reasons()}


# ── SCREEN 6.1 — create or resume the job ────────────────────────────────────

def create_or_resume_job(current_user: dict, potential_order_id: int,
                         station: Optional[str] = None) -> dict:
    """Start packing an order, or pick up where a previous session stopped.

    **Serialised on the order row.** `entity_movement_request` has no unique key on
    `request_identifier` — it cannot have one, being partitioned — so a
    `SELECT ... FOR UPDATE` on a job that does not exist yet locks nothing, and two
    packers tapping the same card would create two jobs and both pack the same
    picklist. Locking the ORDER row first gives them one row to queue on, which
    exists in every case including the first
    (PACKING_SCREEN_API_CONTRACTS.md §6.1).
    """
    scoped = _scope(current_user)
    if repo.get_picklist(potential_order_id, scoped) is None:
        raise NotFoundError(f"picklist {potential_order_id} not found")

    user_id = _user_id(current_user)
    now = repo.db_now()

    with mysql_manager.get_cursor() as cur:
        order = repo.lock_order(cur, potential_order_id)
        if not order:
            raise NotFoundError(f"picklist {potential_order_id} not found")
        if order['status'] != OrderStatus.PICKING.value:
            raise ConflictError(
                f"{display_id(potential_order_id)} is no longer in Picking.",
                C.ErrorCode.ORDER_NOT_PACKABLE)

        lines = repo.order_lines([potential_order_id])
        job = repo.find_job(potential_order_id, cursor=cur, for_update=True)

        if job and job['request_status'] in C.RequestStatus.TERMINAL_STATUSES:
            raise ConflictError(
                f"{display_id(potential_order_id)} has already been submitted.",
                C.ErrorCode.JOB_ALREADY_SUBMITTED)

        if job:
            _guard_job_in_use(job, user_id, now)
            metadata = dict(job['metadata'])
            metadata['station'] = station or metadata.get('station')
            metadata['last_packer'] = current_user.get('username')
            boxes = repo.boxes_for_job(int(job['request_id']))
            packed = _packed_by_product(int(job['request_id']), boxes)
            metadata['totals'] = _job_totals(lines, packed)
            repo.update_job(cur, int(job['request_id']), job['created_on'], user_id,
                            request_status=C.RequestStatus.IN_PROGRESS, metadata=metadata)
            request_id, resumed = int(job['request_id']), True
        else:
            metadata = {
                "v": C.JSON_SCHEMA_VERSION,
                "display_id": display_id(potential_order_id),
                "dealer_id": order.get('dealer_id') or None,
                # SNAPSHOT, not a live read: an audit months later must answer
                # "was this box within tolerance BY THE RULE THAT APPLIED THAT DAY".
                "tolerance_g": C.TOLERANCE_G,
                "weight_verify_floor_g": C.WEIGHT_VERIFY_FLOOR_G,
                # Survives save/resume — this is what keeps box numbering
                # continuous across a paused session (requirements §7).
                "box_seq": 0,
                "station": station,
                "last_packer": current_user.get('username'),
                "totals": _job_totals(lines, {}),
                "saved_at": None,
                "submitted_at": None,
            }
            request_id = repo.insert_job(
                cur, planogram_for_warehouse(order.get('warehouse_id')),
                order.get('company_id'), potential_order_id, metadata, user_id, now)
            packed, resumed = {}, False
            # Inserted as `created` (the state a job exists in before anyone works
            # it) and flipped in the same transaction, because the caller of this
            # endpoint IS the packer opening it. Two statements rather than one so
            # the row passes through the status every other movement type starts in.
            repo.update_job(cur, request_id, now, user_id,
                            request_status=C.RequestStatus.IN_PROGRESS)

    totals = _job_totals(lines, packed)
    banner = None
    if resumed and totals['packed']:
        banner = (f"Resuming — {totals['packed']:g} of {totals['required']:g} already "
                  f"packed. Fresh box for the rest.")

    # Hoisted out of the response literal: one query for every box's SKU rows,
    # not one per box.
    box_sku_rows = repo.sku_rows_in_boxes(
        request_id, [b['detail_id'] for b in _live_boxes(boxes)])
    sku_codes = {int(l['product_id']): l.get('sku_code') for l in lines
                 if l.get('product_id') is not None}

    return {
        "request_id": request_id,
        "potential_order_id": potential_order_id,
        "display_id": display_id(potential_order_id),
        # The packing screen heads itself with the merchant, and this response is
        # the only thing it has after claiming the job — it never re-reads the
        # picklist. Omitting it left that header blank.
        "merchant": order.get('merchant'),
        "request_status": C.RequestStatus.IN_PROGRESS,
        "resumed": resumed,
        "box_seq": metadata.get('box_seq', 0),
        "tolerance_g": metadata.get('tolerance_g', C.TOLERANCE_G),
        "totals": {"required": totals['required'], "packed": totals['packed'],
                   "remaining": totals['short']},
        "items": [_line_out(l, packed.get(int(l['product_id']), 0)) for l in lines],
        # The job's boxes, and NOT an empty list on resume.
        #
        # This response is everything the app has after claiming a job — it does
        # not then re-read the picklist. Omitting the boxes told it a resumed job
        # had none, so a job whose box is already open and already bound to a
        # label came back looking brand new: the app offered "place the empty box
        # on the scale" for a box that physically exists, and the only thing that
        # could happen next was a 409 saying one is already open. `GET /jobs/{id}`
        # has always returned these; the two shapes simply disagreed, and the one
        # every packer hits first was the wrong one.
        "boxes": [_box_out(b, with_items=True, sku_rows=box_sku_rows, codes=sku_codes)
                  for b in boxes],
        "banner": banner,
    }


def _guard_job_in_use(job: dict, user_id: int, now: datetime) -> None:
    """Refuse a job another packer is actively holding — but only for a while.

    A permanent claim would let one dead handset strand a picklist for everyone
    (§16.4 names this as a real leak), so the hold expires and the picklist returns
    to the floor on its own. A `saved` job is never held: pausing is how a packer
    hands work back.
    """
    if job['request_status'] != C.RequestStatus.IN_PROGRESS:
        return
    holder = int(job.get('updated_by_id') or job.get('created_by_id') or 0)
    if holder in (0, user_id):
        return
    touched = job.get('updated_on') or job.get('created_on')
    if isinstance(touched, datetime) and now - touched > timedelta(minutes=C.JOB_TAKEOVER_MINUTES):
        return
    raise ConflictError(
        f"{display_id(int(job['request_identifier']))} is already being packed by "
        f"{job.get('metadata', {}).get('last_packer') or 'another packer'}.",
        C.ErrorCode.JOB_IN_USE)


# ── SCREEN 16 — the reconciliation read ──────────────────────────────────────

def get_job_state(current_user: dict, request_id: int) -> dict:
    """The full server-side truth for a job, so a recovering app can diff its queue.

    **The server's box state wins.** If the app holds queued scans for a box this
    reports `sealed`, it drops them — that box's item list was settled
    authoritatively at close.
    """
    job = _load_job_or_404(request_id, current_user)
    order_id = int(job['request_identifier'])
    lines = repo.order_lines([order_id])
    boxes = repo.boxes_for_job(request_id)
    live = _live_boxes(boxes)
    sku_rows = repo.sku_rows_in_boxes(request_id, [b['detail_id'] for b in live])

    packed: Dict[int, float] = {}
    for row in sku_rows:
        pid = _product_id(row)
        if pid is None:
            continue
        packed[pid] = packed.get(pid, 0.0) + float(row['picked_quantity'] or 0)

    codes = {int(l['product_id']): l.get('sku_code') for l in lines
             if l.get('product_id') is not None}
    totals = _job_totals(lines, packed)
    return {
        "request_id": request_id,
        "potential_order_id": order_id,
        "display_id": display_id(order_id),
        "request_status": job['request_status'],
        "box_seq": job['metadata'].get('box_seq', len(boxes)),
        "tolerance_g": job['metadata'].get('tolerance_g', C.TOLERANCE_G),
        "totals": {"required": totals['required'], "packed": totals['packed'],
                   "remaining": totals['short']},
        "items": [{
            "sku_code": l.get('sku_code'),
            "quantity_required": int(l['quantity'] or 0),
            "quantity_packed": _units(packed.get(int(l['product_id']), 0)),
            "quantity_short": _units(max(int(l['quantity'] or 0)
                                         - packed.get(int(l['product_id']), 0), 0)),
        } for l in lines],
        "boxes": [_box_out(b, with_items=True, sku_rows=sku_rows, codes=codes) for b in boxes],
    }


# ── SCREEN 6.2 — open a box with its captured tare ───────────────────────────

def open_box(current_user: dict, request_id: int, tare_kg: float,
             captured_at: Optional[str] = None) -> dict:
    """Create the box row from the empty carton's weight. Setup step 1.

    The label arrives one call later, so `entity_id` is written as `''` — the
    column is NOT NULL and the row must exist before the sticker is scanned. The
    single-use check ignores `''` (design §4.7).
    """
    job = _load_job_or_404(request_id, current_user)
    _require_job_writable(job)

    tare = _kg(tare_kg)
    if tare < C.MIN_TARE_KG:
        # A reading this small is drift, not a carton. Accepting it would give every
        # box on that bench a baseline of noise.
        raise ValidationError(
            f"Empty box weight {tare:.3f} kg is below the scale's "
            f"{C.MIN_TARE_KG:.3f} kg minimum.",
            C.ErrorCode.BELOW_SCALE_MINIMUM)

    boxes = repo.boxes_for_job(request_id)
    still_open = _open_boxes(boxes)
    if still_open:
        info = still_open[0].get('box_info') or {}
        raise ConflictError(
            f"Box {info.get('box_no')} is still open. Close or abandon it first.",
            C.ErrorCode.BOX_ALREADY_OPEN)
    if len(_live_boxes(boxes)) >= C.MAX_BOXES_PER_PICKLIST:
        raise ValidationError(
            f"This picklist already has {C.MAX_BOXES_PER_PICKLIST} boxes.",
            C.ErrorCode.BOX_ALREADY_OPEN)

    user_id = _user_id(current_user)
    metadata = dict(job['metadata'])
    # Issued from metadata.box_seq inside the same transaction — that is what keeps
    # numbering continuous across a save-and-resume (requirements §7).
    box_no = int(metadata.get('box_seq') or 0) + 1
    metadata['box_seq'] = box_no

    info = _new_box_info(box_no, metadata.get('tolerance_g', C.TOLERANCE_G),
                         C.BoxKind.BUILT, user_id, C.BoxStatus.SETUP, captured_at)
    info['weight_events'].append({"t": captured_at, "e": C.WeightEvent.TARE, "w": tare})

    now = repo.db_now()
    with mysql_manager.get_cursor() as cur:
        box_id = repo.insert_detail(
            cur, request_id, job.get('company_id'), '', C.EntityType.BOX,
            C.NO_BOX, 0, user_id, now,
            source_stock_info=_dump_box_info(info), tare_weight_kg=tare)
        repo.update_job(cur, request_id, job['created_on'], user_id,
                        request_status=C.RequestStatus.IN_PROGRESS, metadata=metadata)

    return {
        "box_id": box_id,
        "box_no": box_no,
        "request_id": request_id,
        "status": C.BoxStatus.SETUP,
        "tare_kg": tare,
        "next_step": "bind_label",
    }


# ── SCREEN 7 — bind the pre-printed label ────────────────────────────────────

def bind_label(current_user: dict, box_id: int, label_code: str,
               scanned_at: Optional[str] = None) -> dict:
    """Write the scanned warehouse QR into the box row's `entity_id`.

    **The setup order is enforced here, not just by the UI.** Binding a box with no
    tare is refused: a client that got the order backwards would produce boxes whose
    expected weight has no baseline, and every one of them would seal against
    nothing.
    """
    code = (label_code or '').strip()
    if not code:
        raise ValidationError("label_code is required")

    box, job = _load_box_or_404(box_id, current_user)
    _require_job_writable(job)
    info = dict(box.get('box_info') or {})

    if box['tare_weight_kg'] is None:
        raise ConflictError("Capture the empty box weight first.", C.ErrorCode.TARE_MISSING)
    if info.get('status') != C.BoxStatus.SETUP:
        raise ConflictError(
            f"Box {info.get('box_no')} is {info.get('status')}, not awaiting a label.",
            C.ErrorCode.BOX_NOT_OPEN)

    owner = repo.label_owner(code)
    if owner:
        raise ConflictError(
            f"Label {code} is already on a box for "
            f"{display_id(int(owner['request_identifier'] or 0))}.",
            C.ErrorCode.LABEL_ALREADY_USED)

    info['status'] = C.BoxStatus.OPEN
    info['bound_at'] = scanned_at
    user_id = _user_id(current_user)

    with mysql_manager.get_cursor() as cur:
        bound = repo.bind_label(cur, box_id, box['created_on'], code,
                                _dump_box_info(info), user_id)
        if not bound:
            # The `entity_id = ''` guard did not match: a concurrent bind won.
            raise ConflictError(f"Box {info.get('box_no')} already carries a label.",
                                C.ErrorCode.LABEL_ALREADY_USED)
        repo.update_job(cur, int(job['request_id']), job['created_on'], user_id)

    return {
        "box_id": box_id,
        "box_no": info.get('box_no'),
        "label_code": code,
        "status": C.BoxStatus.OPEN,
        "tare_kg": _num(box['tare_weight_kg']),
        "bound_at": scanned_at,
        "next_step": "pack",
    }


# ── SCREEN 8 — the batched scan loop ─────────────────────────────────────────

def _resolve_scan_codes(parsed: Sequence[ParsedCode], by_code: Dict[str, dict]) -> Dict[str, dict]:
    """{product code: product row} for a batch — one seek per DISTINCT unknown code.

    Codes already on the picklist resolve from the line snapshot with no query at
    all, which is the steady state: the only codes needing a catalogue lookup are
    ones that are about to be rejected, and rejections are rare by definition
    (design §6.7.6).
    """
    unknown = {p.product_code for p in parsed
               if p.ok and p.product_code and p.product_code not in by_code}
    return repo.products_for_codes(unknown) if unknown else {}


def apply_scans(current_user: dict, box_id: int, scans: Sequence[dict],
                weight_events: Sequence[dict] = ()) -> dict:
    """Apply a flushed batch of trigger pulls to the open box.

    **Quantity is the server's own parse of `raw`.** A client-declared quantity is
    ignored if present: a modified client reporting "this scan = 2000 units" would
    otherwise seal a box against an expected weight it chose for itself (§6.7.1).

    **A carton code is refused here** with `result: 'intact_carton'` and never
    absorbed into a hand-built box — the other half of the mutual routing check
    that `/cartons` performs (§6.8.3).

    Two writes per batch, not per scan: every accepted scan for one SKU collapses
    into a single `picked_quantity` update, and the whole trail is one box-row JSON
    update regardless of batch size.
    """
    box, job = _load_box_or_404(box_id, current_user)
    _require_job_writable(job)
    info = dict(box.get('box_info') or {})
    if info.get('status') != C.BoxStatus.OPEN:
        raise ConflictError(
            f"Box {info.get('box_no')} is {info.get('status')} and cannot take scans.",
            C.ErrorCode.BOX_NOT_OPEN)

    request_id = int(job['request_id'])
    lines = repo.order_lines([int(job['request_identifier'])])
    by_id, by_code = _line_index(lines)

    boxes = repo.boxes_for_job(request_id)
    live = _live_boxes(boxes)
    all_sku_rows = repo.sku_rows_in_boxes(request_id, [b['detail_id'] for b in live])

    packed_job: Dict[int, float] = {}
    rows_in_box: Dict[int, dict] = {}
    for row in all_sku_rows:
        pid = _product_id(row)
        if pid is None:
            continue
        packed_job[pid] = packed_job.get(pid, 0.0) + float(row['picked_quantity'] or 0)
        if int(row['source_bin_id']) == box_id:
            rows_in_box[pid] = row

    fmt = BarcodeFormat.from_config()
    seen_uids = {s.get('uid') for s in (info.get('scans') or []) if s.get('uid')}
    seen_serials = {s.get('sn') for s in (info.get('scans') or []) if s.get('sn')}

    parsed_all = [parse(s.get('raw') or '', fmt) if s.get('raw') else None
                  for s in scans]
    catalogue = _resolve_scan_codes([p for p in parsed_all if p], by_code)

    results: List[dict] = []
    result_products: List[Optional[int]] = []
    deltas: Dict[int, float] = {}
    trail: List[dict] = []
    rejects = 0

    for scan, parsed in zip(scans, parsed_all):
        uid = scan.get('uid')
        entry = {"t": scan.get('t'), "uid": uid, "w": scan.get('w')}

        if uid and uid in seen_uids:
            # A retried batch returns `duplicate` for rows already applied and
            # writes nothing further, so the app can drain its outbox blindly
            # without reasoning about what did or did not land.
            results.append({"uid": uid, "result": C.Result.DUPLICATE, "sku_code": None,
                            "quantity": 0})
            result_products.append(None)
            continue
        if uid:
            seen_uids.add(uid)

        verdict = _classify_scan(scan, parsed, by_code, catalogue,
                                 packed_job, deltas, seen_serials)
        results.append(verdict['result_out'])
        result_products.append(verdict['product_id'])
        entry.update(verdict['trail'])
        trail.append(entry)
        if verdict['result_out']['result'] not in (C.Result.ACCEPTED, C.Result.UNDO):
            rejects += 1
        if verdict['product_id'] is not None and verdict['delta']:
            deltas[verdict['product_id']] = deltas.get(verdict['product_id'], 0.0) + verdict['delta']
            if verdict['serial']:
                seen_serials.add(verdict['serial'])

    user_id = _user_id(current_user)
    now = repo.db_now()

    # Rejected scans are STORED, not discarded. A packer repeatedly triggering a SKU
    # that is not on the picklist is exactly the pattern this module exists to make
    # visible.
    info.setdefault('scans', []).extend(trail)
    info.setdefault('weight_events', []).extend(
        [{"t": e.get('t'), "e": e.get('e'), "w": e.get('w'), "x": e.get('x'), "d": e.get('d')}
         for e in (weight_events or [])])
    flags = dict(info.get('flags') or {})
    flags['reject_scans'] = int(flags.get('reject_scans') or 0) + rejects
    info['flags'] = flags

    # The post-batch contents of this box, clamped at zero. Computed BEFORE the
    # writes so the row quantities, the box's `picked_quantity` and the response all
    # come from one number — an undo that would take a line negative must not leave
    # the box total disagreeing with the rows it is meant to sum.
    box_items: Dict[int, float] = {
        pid: float(row['picked_quantity'] or 0) for pid, row in rows_in_box.items()}
    for pid, delta in deltas.items():
        box_items[pid] = max(box_items.get(pid, 0.0) + delta, 0.0)
    box_units = sum(box_items.values())

    with mysql_manager.get_cursor() as cur:
        for product_id in deltas:
            existing = rows_in_box.get(product_id)
            quantity = box_items.get(product_id, 0.0)
            if existing:
                repo.update_detail(cur, int(existing['detail_id']), existing['created_on'],
                                   user_id, picked_quantity=quantity)
            else:
                # `weight_kg` on a SKU row is a SNAPSHOT of the unit weight, not a
                # join. The expected weight is the evidence a fraud accusation rests
                # on; a master-data correction next month must not silently re-derive
                # a different expected weight for a box sealed today (design §4.5).
                repo.insert_detail(cur, request_id, job.get('company_id'), str(product_id),
                                   C.EntityType.SKU, box_id, quantity, user_id, now,
                                   weight_kg=_unit_kg(by_id.get(product_id)))
        repo.update_detail(cur, box_id, box['created_on'], user_id,
                           picked_quantity=box_units,
                           source_stock_info=_dump_box_info(info))
        metadata = dict(job['metadata'])
        for product_id in deltas:
            was = float((rows_in_box.get(product_id) or {}).get('picked_quantity') or 0)
            packed_job[product_id] = packed_job.get(product_id, 0.0) + \
                (box_items.get(product_id, 0.0) - was)
        metadata['totals'] = _job_totals(lines, packed_job)
        repo.update_job(cur, request_id, job['created_on'], user_id, metadata=metadata)

    # `qty_in_box` is the running count the handheld shows against the line. It can
    # only be filled once the whole batch is applied — twenty scans of one SKU each
    # need the total after the batch, not after themselves.
    for result_out, pid in zip(results, result_products):
        if pid is not None and result_out['result'] in (C.Result.ACCEPTED, C.Result.UNDO):
            result_out['qty_in_box'] = _units(box_items.get(pid, 0))

    totals = metadata['totals']
    return {
        "box_id": box_id,
        "results": results,
        "box": {
            "expected_kg": _kg(float(box['tare_weight_kg'] or 0) + sum(
                qty * (_unit_kg(by_id.get(pid)) or 0)
                for pid, qty in box_items.items())),
            "units": _units(box_units),
            "items": [{"sku_code": (by_id.get(pid) or {}).get('sku_code'), "quantity": _units(qty)}
                      for pid, qty in box_items.items() if qty],
        },
        "job": {"packed_units": totals['packed'], "total_units": totals['required']},
    }


def _classify_scan(scan: dict, parsed: Optional[ParsedCode], by_code: Dict[str, dict],
                   catalogue: Dict[str, dict], packed_job: Dict[int, float],
                   pending: Dict[int, float], seen_serials: set) -> dict:
    """Decide one scan's verdict. Pure — the caller does all the writing.

    `pending` is the running total of this batch's accepted deltas, so twenty scans
    of the same SKU are checked against the picklist cumulatively rather than each
    passing an over-quantity test the batch as a whole fails.
    """
    uid = scan.get('uid')

    def out(result: str, product_id=None, sku_code=None, quantity=0, delta=0.0,
            serial=None, extra=None):
        result_out = {"uid": uid, "result": result, "sku_code": sku_code,
                      "quantity": quantity}
        if extra:
            result_out.update(extra)
        return {"result_out": result_out, "product_id": product_id, "delta": delta,
                "serial": serial,
                "trail": {"r": result, "sku": product_id, "sn": serial, "q": quantity}}

    # An explicit correction, not a re-scan. Without it a packer who physically
    # removes a scanned item leaves the count and the weight diverged, and the box
    # can never close. It reduces the count rather than inflating it, and it is
    # recorded as its own auditable event — so it does not violate the "every
    # addition is evidenced by a hardware decode" rule (design §6.2b).
    delta_in = scan.get('delta')
    if delta_in is not None and float(delta_in) < 0:
        line = by_code.get(str(scan.get('sku_code') or ''))
        if not line:
            return out(C.Result.UNKNOWN_SKU)
        pid = int(line['product_id'])
        return out(C.Result.UNDO, product_id=pid, sku_code=line.get('sku_code'),
                   quantity=int(delta_in), delta=float(delta_in))

    if parsed is None or not parsed.ok:
        return out(C.Result.UNPARSEABLE)

    # A full supplier carton is a shipping box in its own right; it must never be
    # scanned INTO the box being built. The app routes off its own parse, but this
    # rejection is the enforcement (§6.8.3).
    if parsed.is_intact_carton:
        return out(C.Result.INTACT_CARTON, quantity=parsed.quantity, serial=parsed.serial,
                   extra={"hint": "post this code to /packing/jobs/{request_id}/cartons"})

    if parsed.serial and parsed.serial in seen_serials:
        # The serial identifies a physical pack uniquely, so the same one arriving
        # twice is a duplicate with certainty rather than by inference from `uid`.
        return out(C.Result.DUPLICATE, quantity=0, serial=parsed.serial)

    line = by_code.get(parsed.product_code)
    if not line:
        product = catalogue.get(parsed.product_code)
        if not product:
            return out(C.Result.UNKNOWN_SKU)
        return out(C.Result.NOT_IN_PICKLIST, sku_code=product.get('product_string'),
                   serial=parsed.serial)

    pid = int(line['product_id'])
    required = float(line['quantity'] or 0)
    already = packed_job.get(pid, 0.0) + pending.get(pid, 0.0)
    if already + parsed.quantity > required:
        return out(C.Result.OVER_QUANTITY, product_id=pid, sku_code=line.get('sku_code'),
                   quantity=parsed.quantity, serial=parsed.serial)

    return out(C.Result.ACCEPTED, product_id=pid, sku_code=line.get('sku_code'),
               quantity=parsed.quantity, delta=float(parsed.quantity),
               serial=parsed.serial, extra={"serial": parsed.serial})


# ── SCREEN 8b — an intact supplier carton ────────────────────────────────────

def intake_carton(current_user: dict, request_id: int, raw: str, measured_kg: float,
                  scanned_at: Optional[str] = None) -> dict:
    """One scan creates, fills, weighs and seals a box.

    An unopened OEM carton is already a sealed, labelled, known-contents shipping
    unit, so it does not pass through setup -> open -> sealed: there is nothing to
    add to it. Its identity is its OWN code, so it consumes no warehouse label, and
    its tare is READ from `product_uom.pack_tare_kg` rather than weighed — a sealed
    carton cannot be emptied to find out (§6.8).

    **It is still weighed.** The scan says what should be inside; the scale confirms
    nothing was taken out before it reached the bench. A carton opened in transit and
    resealed is exactly what a weight check catches and a trusted OEM seal does not.
    """
    job = _load_job_or_404(request_id, current_user)
    _require_job_writable(job)

    parsed = parse(raw or '', BarcodeFormat.from_config())
    if not parsed.ok:
        raise ValidationError("That code does not match this company's format.",
                              C.ErrorCode.NOT_AN_INTACT_CARTON)
    if not parsed.is_intact_carton:
        # The mirror of `/scans` rejecting a carton code. Together they stop a
        # modified client choosing which arithmetic its scan is measured against.
        raise ValidationError("That is a retail pack, not an intact carton.",
                              C.ErrorCode.NOT_AN_INTACT_CARTON)

    carton_code = parsed.serial or parsed.upi
    if not carton_code:
        raise ValidationError("This carton code carries no serial to identify it by.",
                              C.ErrorCode.NOT_AN_INTACT_CARTON)

    lines = repo.order_lines([int(job['request_identifier'])])
    _, by_code = _line_index(lines)
    line = by_code.get(parsed.product_code)
    if not line:
        product = repo.products_for_codes([parsed.product_code]).get(parsed.product_code)
        detail = ("That SKU is not on this picklist." if product
                  else f"No product matches {parsed.product_code}.")
        raise ValidationError(detail, C.ErrorCode.NOT_AN_INTACT_CARTON)

    product_id = int(line['product_id'])
    boxes = repo.boxes_for_job(request_id)
    packed = _packed_by_product(request_id, boxes)
    remaining = float(line['quantity'] or 0) - packed.get(product_id, 0.0)

    # A 200-unit carton cannot ship intact against a line needing 150. There is
    # deliberately no "scan the carton, declare fewer" path — that would let a
    # packer assert a quantity the barcode contradicts, which is the one property an
    # anti-fraud flow cannot give up (§6.8.2).
    if parsed.quantity > remaining:
        raise ConflictError(
            f"Carton holds {parsed.quantity} but only {remaining:g} are still needed "
            f"for {line.get('sku_code')}. Open it and scan retail packs.",
            C.ErrorCode.CARTON_EXCEEDS_NEED,
            {"carton_quantity": parsed.quantity, "remaining": remaining})

    if repo.label_owner(carton_code):
        raise ConflictError(f"Carton {carton_code} is already packed on this order.",
                            C.ErrorCode.DUPLICATE_CARTON)

    rung = repo.uom_rung(product_id, parsed.quantity)
    if not rung or rung.get('pack_tare_kg') is None:
        raise ValidationError("No packing weight on record for this carton size.",
                              C.ErrorCode.PACK_TARE_MISSING)

    tare = _kg(rung['pack_tare_kg'])
    unit_weight = _unit_kg(line)
    sealed = _kg(measured_kg)
    tolerance_g = int(job['metadata'].get('tolerance_g', C.TOLERANCE_G))

    user_id = _user_id(current_user)
    metadata = dict(job['metadata'])
    box_no = int(metadata.get('box_seq') or 0) + 1
    metadata['box_seq'] = box_no

    info = _new_box_info(box_no, tolerance_g, C.BoxKind.INTACT, user_id,
                         C.BoxStatus.SEALED, scanned_at)
    info['scans'] = [{"t": scanned_at, "r": C.Result.ACCEPTED, "sku": product_id,
                      "sn": parsed.serial, "q": parsed.quantity, "batch": parsed.batch}]

    try:
        with mysql_manager.get_cursor() as cur:
            now = repo.db_now()
            box_id = repo.insert_detail(
                cur, request_id, job.get('company_id'), carton_code, C.EntityType.BOX,
                C.NO_BOX, parsed.quantity, user_id, now,
                source_stock_info=_dump_box_info(info), tare_weight_kg=tare)
            repo.insert_detail(
                cur, request_id, job.get('company_id'), str(product_id), C.EntityType.SKU,
                box_id, parsed.quantity, user_id, now, weight_kg=unit_weight)

            # Recomputed from the rows just written, by the SAME aggregate a built
            # box gets. Passing the cursor matters: these rows are uncommitted, and a
            # second pooled connection would weigh an empty box.
            expected = repo.expected_weight_kg(box_id, now, cursor=cur)
            if expected is None:
                # The aggregate could not find the box row it had just written. That
                # is a bug, not a state — and the old fallback to bare `tare` made it
                # invisible: a 200-unit carton was weighed as an empty one and the
                # 8 kg of stock inside it silently vanished from the expectation.
                # Fail loudly; a weight check that cannot compute its own number must
                # never answer with a smaller one.
                raise RuntimeError(
                    f"expected-weight aggregate returned no row for box {box_id}")
            expected = _kg(expected)
            variance = _grams(sealed - expected)
            if abs(variance) > tolerance_g:
                # Raising rolls the whole transaction back, so a refused carton
                # leaves no box row behind. There is nothing to append a
                # `seal_rejected` event to — unlike a built box, this box would not
                # have existed.
                raise _SealRejected(expected, sealed, variance)

            info['within_tolerance'] = True
            info['sealed_at'] = scanned_at
            info['unverifiable_kg'] = 0.0 if _weight_verifiable(unit_weight, parsed.quantity) \
                else _kg((unit_weight or 0) * parsed.quantity)
            info['flags']['max_variance_g'] = abs(variance)
            info['weight_events'].append(
                {"t": scanned_at, "e": C.WeightEvent.SEAL, "w": sealed, "x": expected,
                 "d": variance})

            repo.update_detail(cur, box_id, now, user_id,
                               source_stock_info=_dump_box_info(info),
                               weight_kg=sealed, expected_weight_kg_=expected,
                               variance_g=variance)

            packed[product_id] = packed.get(product_id, 0.0) + parsed.quantity
            metadata['totals'] = _job_totals(lines, packed)
            repo.update_job(cur, request_id, job['created_on'], user_id,
                            request_status=C.RequestStatus.IN_PROGRESS, metadata=metadata)
    except _SealRejected as rejected:
        raise ConflictError(
            f"Carton reads {rejected.sealed_kg:.3f} kg but should be "
            f"{rejected.expected_kg:.3f} kg ({rejected.variance_g:+d} g, tolerance "
            f"±{tolerance_g} g). Do not ship — check the seal.",
            C.ErrorCode.WEIGHT_MISMATCH,
            {"expected_kg": rejected.expected_kg, "sealed_kg": rejected.sealed_kg,
             "variance_g": rejected.variance_g, "tolerance_g": tolerance_g})

    totals = metadata['totals']
    packing_events.publish_carton_sealed(
        request_id=request_id, potential_order_id=int(job['request_identifier']),
        box_id=box_id, box_no=box_no, label_code=carton_code, kind=C.BoxKind.INTACT,
        units=float(parsed.quantity), sealed_kg=sealed, expected_kg=expected,
        variance_g=variance, within_tolerance=True, tolerance_g=tolerance_g,
        company_id=job.get('company_id'),
        warehouse_id=job.get('order', {}).get('warehouse_id'), packed_by=user_id)

    return {
        "box_id": box_id,
        "box_no": box_no,
        "kind": C.BoxKind.INTACT,
        "label_code": carton_code,
        "status": C.BoxStatus.SEALED,
        "contents": [{"sku_code": line.get('sku_code'), "name": line.get('name'),
                      "quantity": parsed.quantity, "batch": parsed.batch}],
        "tare_kg": tare,
        "expected_kg": expected,
        "sealed_kg": sealed,
        "variance_g": variance,
        "within_tolerance": True,
        "job": {"packed_units": totals['packed'], "total_units": totals['required'],
                "remaining_units": totals['short'],
                "next_action": "finish" if totals['short'] <= 0 else "new_box"},
    }


# ── SCREEN 9 — close the box (the authoritative write) ───────────────────────

def close_box(current_user: dict, box_id: int, sealed_kg: float,
              sealed_at: Optional[str] = None, items: Sequence[dict] = (),
              scans: Sequence[dict] = (), weight_events: Sequence[dict] = ()) -> dict:
    """Weight-verify and seal a built box. **The rule this module exists for.**

    The item list in the body WINS over accumulated scans, so a box whose `/scans`
    batches never uploaded still seals correctly — the whole content list is carried
    here. But the weight is not taken on trust: `expected` is recomputed as one SQL
    aggregate over the reconciled rows' SNAPSHOTTED unit weights, and any
    client-supplied expected value is ignored.

    On rejection nothing is written except a `seal_rejected` entry on the box's
    `weight_events[]` and a bumped `flags.seal_attempts`. A packer who attempts to
    seal an overweight box four times is a signal, and discarding it would hide
    exactly the behaviour this module exists to catch.
    """
    box, job = _load_box_or_404(box_id, current_user)
    _require_job_writable(job)
    info = dict(box.get('box_info') or {})
    if info.get('status') != C.BoxStatus.OPEN:
        raise ConflictError(
            f"Box {info.get('box_no')} is {info.get('status')} and cannot be closed.",
            C.ErrorCode.BOX_NOT_OPEN)

    request_id = int(job['request_id'])
    lines = repo.order_lines([int(job['request_identifier'])])
    by_id, by_code = _line_index(lines)

    declared: Dict[int, float] = {}
    for item in items or []:
        line = by_code.get(str(item.get('sku_code') or ''))
        if not line:
            raise ValidationError(
                f"{item.get('sku_code')} is not on this picklist.", C.ErrorCode.OVER_QUANTITY)
        quantity = float(item.get('quantity') or 0)
        if quantity < 0:
            raise ValidationError("quantity cannot be negative")
        declared[int(line['product_id'])] = declared.get(int(line['product_id']), 0.0) + quantity

    total_units = sum(declared.values())
    if total_units <= 0:
        raise ConflictError("Box is empty.", C.ErrorCode.BOX_EMPTY)

    boxes = repo.boxes_for_job(request_id)
    live = _live_boxes(boxes)
    all_rows = repo.sku_rows_in_boxes(request_id, [b['detail_id'] for b in live])
    rows_in_box: Dict[int, dict] = {}
    packed_elsewhere: Dict[int, float] = {}
    for row in all_rows:
        pid = _product_id(row)
        if pid is None:
            continue
        if int(row['source_bin_id']) == box_id:
            rows_in_box[pid] = row
        else:
            packed_elsewhere[pid] = packed_elsewhere.get(pid, 0.0) + float(row['picked_quantity'] or 0)

    for pid, quantity in declared.items():
        required = float((by_id.get(pid) or {}).get('quantity') or 0)
        if packed_elsewhere.get(pid, 0.0) + quantity > required:
            raise ConflictError(
                f"{(by_id.get(pid) or {}).get('sku_code')}: "
                f"{packed_elsewhere.get(pid, 0.0) + quantity:g} packed but only "
                f"{required:g} required.",
                C.ErrorCode.OVER_QUANTITY)

    sealed = _kg(sealed_kg)
    tolerance_g = int(info.get('tolerance_g') or job['metadata'].get('tolerance_g')
                      or C.TOLERANCE_G)
    user_id = _user_id(current_user)
    now = repo.db_now()

    trail = [{"t": s.get('t'), "uid": s.get('uid'), "w": s.get('w'), "r": "late"}
             for s in (scans or [])]
    events = [{"t": e.get('t'), "e": e.get('e'), "w": e.get('w'), "x": e.get('x'),
               "d": e.get('d')} for e in (weight_events or [])]

    try:
        with mysql_manager.get_cursor() as cur:
            # Reconcile the SKU rows to the declared list FIRST, so the aggregate
            # weighs what is actually being sealed. If the check then fails, raising
            # rolls this reconciliation back with everything else.
            for pid, quantity in declared.items():
                existing = rows_in_box.pop(pid, None)
                unit_weight = _unit_kg(by_id.get(pid))
                if existing:
                    repo.update_detail(cur, int(existing['detail_id']), existing['created_on'],
                                       user_id, picked_quantity=quantity)
                else:
                    repo.insert_detail(cur, request_id, job.get('company_id'), str(pid),
                                       C.EntityType.SKU, box_id, quantity, user_id, now,
                                       weight_kg=unit_weight)
            for leftover in rows_in_box.values():
                # Scanned into this box but absent from the final list — the packer
                # took it back out. Zeroed rather than deleted: nothing in this module
                # deletes, and the row is evidence the item was once in the carton.
                repo.update_detail(cur, int(leftover['detail_id']), leftover['created_on'],
                                   user_id, picked_quantity=0)

            expected = repo.expected_weight_kg(box_id, box['created_on'], cursor=cur)
            if expected is None:
                # See the note in intake_carton: falling back to the tare here would
                # under-state a full box by everything in it, and seal it.
                raise RuntimeError(
                    f"expected-weight aggregate returned no row for box {box_id}")
            expected = _kg(expected)
            variance = _grams(sealed - expected)
            if abs(variance) > tolerance_g:
                raise _SealRejected(expected, sealed, variance)

            unverifiable = _kg(sum(
                quantity * (_unit_kg(by_id.get(pid)) or 0)
                for pid, quantity in declared.items()
                if not _weight_verifiable(_unit_kg(by_id.get(pid)), quantity)))

            info['status'] = C.BoxStatus.SEALED
            info['sealed_at'] = sealed_at
            info['within_tolerance'] = True
            info['unverifiable_kg'] = unverifiable
            info.setdefault('scans', []).extend(trail)
            info.setdefault('weight_events', []).extend(events)
            info['weight_events'].append(
                {"t": sealed_at, "e": C.WeightEvent.SEAL, "w": sealed, "x": expected,
                 "d": variance})
            flags = dict(info.get('flags') or {})
            flags['max_variance_g'] = max(int(flags.get('max_variance_g') or 0), abs(variance))
            info['flags'] = flags

            repo.update_detail(cur, box_id, box['created_on'], user_id,
                               picked_quantity=total_units,
                               source_stock_info=_dump_box_info(info),
                               weight_kg=sealed, expected_weight_kg_=expected,
                               variance_g=variance)

            packed = dict(packed_elsewhere)
            for pid, quantity in declared.items():
                packed[pid] = packed.get(pid, 0.0) + quantity
            metadata = dict(job['metadata'])
            metadata['totals'] = _job_totals(lines, packed)
            repo.update_job(cur, request_id, job['created_on'], user_id, metadata=metadata)
    except _SealRejected as rejected:
        _record_seal_rejection(box, rejected, sealed_at, user_id)
        raise ConflictError(
            f"Box cannot close: scale reads {rejected.sealed_kg:.3f} kg but scanned items "
            f"total {rejected.expected_kg:.3f} kg ({rejected.variance_g:+d} g, tolerance "
            f"±{tolerance_g} g). Remove the unscanned item.",
            C.ErrorCode.WEIGHT_MISMATCH,
            {"expected_kg": rejected.expected_kg, "sealed_kg": rejected.sealed_kg,
             "variance_g": rejected.variance_g, "tolerance_g": tolerance_g})

    totals = metadata['totals']
    label = box['entity_id'] or None
    packing_events.publish_carton_sealed(
        request_id=request_id, potential_order_id=int(job['request_identifier']),
        box_id=box_id, box_no=info.get('box_no'), label_code=label,
        kind=info.get('kind', C.BoxKind.BUILT), units=total_units, sealed_kg=sealed,
        expected_kg=expected, variance_g=variance, within_tolerance=True,
        tolerance_g=tolerance_g, company_id=job.get('company_id'),
        warehouse_id=job.get('order', {}).get('warehouse_id'), packed_by=user_id)

    return {
        "box_id": box_id,
        "box_no": info.get('box_no'),
        "label_code": label,
        "status": C.BoxStatus.SEALED,
        "expected_kg": expected,
        "sealed_kg": sealed,
        "variance_g": variance,
        "within_tolerance": True,
        "tolerance_g": tolerance_g,
        "unverifiable_kg": info.get('unverifiable_kg', 0.0),
        "packed": {"units": _units(total_units), "skus": len([q for q in declared.values() if q])},
        "packer": current_user.get('username'),
        "sealed_at": sealed_at,
        "job": {"packed_units": totals['packed'], "total_units": totals['required'],
                "remaining_units": totals['short'],
                "next_action": "finish" if totals['short'] <= 0 else "new_box"},
    }


def _record_seal_rejection(box: dict, rejected: _SealRejected, sealed_at: Optional[str],
                           user_id: int) -> None:
    """Append the refused seal to the box's trail, in its own transaction.

    It has to be separate: the close transaction was rolled back precisely so that
    nothing it reconciled survives, and this one entry is the deliberate exception.
    Never raises — losing the audit note is bad, but turning a clear
    `weight_mismatch` into a 500 is worse.
    """
    try:
        info = dict(box.get('box_info') or {})
        info.setdefault('weight_events', []).append({
            "t": sealed_at, "e": C.WeightEvent.SEAL_REJECTED,
            "w": rejected.sealed_kg, "x": rejected.expected_kg, "d": rejected.variance_g,
        })
        flags = dict(info.get('flags') or {})
        flags['seal_attempts'] = int(flags.get('seal_attempts') or 0) + 1
        flags['max_variance_g'] = max(int(flags.get('max_variance_g') or 0),
                                      abs(rejected.variance_g))
        info['flags'] = flags
        with mysql_manager.get_cursor() as cur:
            repo.update_detail(cur, int(box['detail_id']), box['created_on'], user_id,
                               source_stock_info=_dump_box_info(info))
    except Exception:
        logger.exception("packing: failed to record a seal rejection",
                         extra={'box_id': box.get('detail_id')})


# ── SCREEN 14 — abandon a box ────────────────────────────────────────────────

def abandon_box(current_user: dict, box_id: int,
                reason: str = C.AbandonReason.PACKER_EXIT) -> dict:
    """Take a box out of the job without deleting anything.

    **Nothing is deleted, ever.** The box row, its SKU rows and its whole JSON trail
    are kept in full — a box abandoned immediately after a weight mismatch is a
    pattern worth being able to see, and deleting the evidence would erase exactly
    the case this module exists for.

    **The label is NOT released.** Labels are single-use forever (D6), so the
    sticker stays in `entity_id` and is spent. Clearing it would either orphan the
    code or let a second box claim it — two box rows, one label — which is the
    ambiguity the single-use rule exists to prevent.
    """
    box, job = _load_box_or_404(box_id, current_user)
    info = dict(box.get('box_info') or {})
    if info.get('status') in (C.BoxStatus.SEALED, C.BoxStatus.ABANDONED):
        raise ConflictError(f"Box {info.get('box_no')} is already {info.get('status')}.",
                            C.ErrorCode.BOX_NOT_OPEN)

    if reason not in C.AbandonReason.ALL:
        raise ValidationError(f"reason must be one of {', '.join(C.AbandonReason.ALL)}")

    info['status'] = C.BoxStatus.ABANDONED
    info['abandoned_reason'] = reason
    info['abandoned_at'] = datetime.utcnow().isoformat()
    user_id = _user_id(current_user)

    with mysql_manager.get_cursor() as cur:
        repo.update_detail(cur, box_id, box['created_on'], user_id,
                           source_stock_info=_dump_box_info(info))
        repo.update_job(cur, int(job['request_id']), job['created_on'], user_id)

    return {"box_id": box_id, "status": C.BoxStatus.ABANDONED, "label_released": False}


# ── SCREEN 11 — save and exit ────────────────────────────────────────────────

def save_job(current_user: dict, request_id: int) -> dict:
    """Pause the job. **Nothing is written to the order.**

    `potential_order` stays `Picking` and `quantity_packed` is untouched, because a
    half-written packed quantity would be read by invoicing as final. Resuming
    always starts a fresh box, which is enforced by the open-box refusal below
    rather than left to the UI (requirements §9.2).
    """
    job = _load_job_or_404(request_id, current_user)
    _require_job_writable(job)

    boxes = repo.boxes_for_job(request_id)
    still_open = _open_boxes(boxes)
    if still_open:
        info = still_open[0].get('box_info') or {}
        raise ConflictError(
            f"Box {info.get('box_no')} is still open. Close or abandon it before saving.",
            C.ErrorCode.BOX_STILL_OPEN)

    lines = repo.order_lines([int(job['request_identifier'])])
    packed = _packed_by_product(request_id, boxes)
    totals = _job_totals(lines, packed)
    metadata = dict(job['metadata'])
    metadata['totals'] = totals
    metadata['saved_at'] = datetime.utcnow().isoformat()

    with mysql_manager.get_cursor() as cur:
        repo.update_job(cur, request_id, job['created_on'], _user_id(current_user),
                        request_status=C.RequestStatus.SAVED, metadata=metadata)

    sealed = len(_sealed_boxes(boxes))
    return {
        "request_id": request_id,
        "request_status": C.RequestStatus.SAVED,
        "packed_units": totals['packed'],
        "total_units": totals['required'],
        "boxes_sealed": sealed,
        "detail": (f"Saved. {totals['packed']:g} of {totals['required']:g} packed — "
                   f"resume on a fresh box."),
    }


# ── SCREEN 12 — submit ───────────────────────────────────────────────────────

def submit_job(current_user: dict, request_id: int, acknowledge_short: bool = False,
               reason_id: Optional[int] = None, note: Optional[str] = None,
               reasons: Optional[Dict[str, int]] = None) -> dict:
    """Finalise the job and write back to the order. The largest write in the module.

    **Two-phase by design.** An un-acknowledged submit against an incomplete order
    fails WITH the shortfall in the body — that rejection *is* the confirmation
    dialog, so the numbers the packer acknowledges are produced by the same code
    that will write them, and there is no window between a preview and a commit in
    which the quantities could change. An accidental submit therefore cannot close
    an order short.

    **The shortfall is derived, never declared** (`quantity - packed`, per line,
    from the job's own rows). Asking the packer to re-enumerate it would be
    redundant typing and a chance for the declaration to disagree with the record.
    """
    job = _load_job_or_404(request_id, current_user)
    _require_job_writable(job)

    boxes = repo.boxes_for_job(request_id)
    still_open = _open_boxes(boxes)
    if still_open:
        info = still_open[0].get('box_info') or {}
        raise ConflictError(
            f"Box {info.get('box_no')} is still open. Close or abandon it before submitting.",
            C.ErrorCode.BOX_STILL_OPEN)

    order_id = int(job['request_identifier'])
    lines = repo.order_lines([order_id])
    packed = _packed_by_product(request_id, boxes)
    totals = _job_totals(lines, packed)

    if totals['packed'] <= 0:
        # Picking delivered nothing. Closing the order 100% not found is a picking
        # failure recorded as a packing outcome, and it would flow to invoicing as
        # an empty shipment (§6.10.4).
        raise ConflictError(
            "Nothing has been packed. Return the picklist to the pool instead.",
            C.ErrorCode.NOTHING_PACKED)

    shortfall = []
    for line in lines:
        pid = int(line['product_id'])
        required = float(line['quantity'] or 0)
        got = packed.get(pid, 0.0)
        if got < required:
            shortfall.append({
                "product_id": pid,
                "sku_code": line.get('sku_code'),
                "name": line.get('name'),
                "required": _units(required),
                "packed": _units(got),
                "short": _units(required - got),
            })

    if shortfall and not acknowledge_short:
        raise ConflictError(
            f"{len(shortfall)} SKUs short. {totals['short']:g} units will be marked "
            f"NOT FOUND and the order closed.",
            C.ErrorCode.SHORTFALL_REQUIRES_ACK,
            {"shortfall": [{k: v for k, v in s.items() if k != 'product_id'}
                           for s in shortfall],
             "totals": {"required": totals['required'], "packed": totals['packed'],
                        "short": totals['short']}})

    if reason_id is not None and not repo.reason_exists(int(reason_id)):
        raise ValidationError(f"reason_id {reason_id} is not an active short reason")

    reason_by_code = {str(k): int(v) for k, v in (reasons or {}).items()}
    # Only loaded when there is a shortfall to name — a complete order's submit
    # should not pay for a lookup whose result it will not use.
    reason_names = ({int(r['reason_id']): r['reason'] for r in repo.short_reasons()}
                    if shortfall else {})

    user_id = _user_id(current_user)
    now = repo.db_now()
    status = C.RequestStatus.SUBMITTED_SHORT if shortfall else C.RequestStatus.COMPLETED
    sealed = _sealed_boxes(boxes)
    # `box_count` is read when the invoice and the `order` row are created, so a
    # count that never reaches the order ships the default of 1 onto every invoice
    # regardless of how many boxes physically exist.
    box_count = len(sealed)

    short_pack_reason = None
    if shortfall:
        parts = [reason_names.get(int(reason_id))] if reason_id is not None else []
        if note:
            parts.append(note)
        short_pack_reason = ' — '.join([p for p in parts if p]) or 'short packed'

    metadata = dict(job['metadata'])
    metadata['totals'] = totals
    metadata['submitted_at'] = now.isoformat()

    with mysql_manager.get_cursor() as cur:
        for short in shortfall:
            # `source_bin_id = 0` means "in no box", which is exactly what a
            # not-found shortfall is — the column's existing "no bin" convention
            # rather than a new flag.
            repo.insert_detail(
                cur, request_id, job.get('company_id'), str(short['product_id']),
                C.EntityType.SKU, C.NO_BOX, 0, user_id, now,
                underpick_reason_id=int(reason_by_code.get(str(short['sku_code']),
                                                           reason_id or 0)))
        repo.update_job(cur, request_id, job['created_on'], user_id,
                        request_status=status, metadata=metadata)

        # Through order.service, never direct SQL on potential_order* — the
        # cross-module boundary rule. Sharing the cursor is what makes the movement
        # rows and the order write commit or roll back together.
        order_service = _order_service()
        try:
            order_service.record_pack_completion(
                potential_order_id=order_id,
                packed_quantities={int(pid): int(qty) for pid, qty in packed.items()},
                box_count=box_count, user_id=user_id,
                short_pack_reason=short_pack_reason, cursor=cur)
        except order_service.PackCompletionError as exc:
            raise ConflictError(str(exc), C.ErrorCode.ORDER_NOT_PACKABLE)

    packing_events.publish_session_completed(
        request_id=request_id, potential_order_id=order_id, request_status=status,
        box_count=box_count, packed_units=totals['packed'],
        required_units=totals['required'], short_units=totals['short'],
        company_id=job.get('company_id'),
        warehouse_id=job.get('order', {}).get('warehouse_id'), packed_by=user_id,
        short_sku_codes=[s['sku_code'] for s in shortfall if s.get('sku_code')])

    return {
        "request_id": request_id,
        "request_status": status,
        "potential_order_id": order_id,
        "order_status": OrderStatus.PACKED.value,
        "boxes": [{"box_id": int(b['detail_id']),
                   "box_no": (b.get('box_info') or {}).get('box_no'),
                   "label_code": b['entity_id'] or None,
                   "units": _units(b['picked_quantity']),
                   "sealed_kg": _num(b['weight_kg']),
                   "variance_g": b['variance_g']} for b in sealed],
        "totals": {"packed": totals['packed'], "required": totals['required'],
                   "short": totals['short']},
        "shorts": [{"sku_code": s['sku_code'], "name": s['name'], "quantity": s['short'],
                    "reason": reason_names.get(
                        reason_by_code.get(str(s['sku_code']), reason_id or 0))}
                   for s in shortfall],
        "box_count": box_count,
    }
