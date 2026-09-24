# -*- encoding: utf-8 -*-
"""picklist module — what an upload does, and what a scan does.

Upload does NOT move an order. It attaches a document to an order that is already
in potential_order (typically Open), fills in that order's line items, and mints a
QR token. The order's status is untouched.

Scan is what moves it, one step along OrderStateMachine's chain.
"""

from datetime import datetime

from api.core.logging import get_logger
from api.db_manager import mysql_manager
from api.modules.fulfillment.order.constants import OrderStatus
from api.modules.fulfillment.order.state_machine import OrderStateMachine
from api.modules.fulfillment.picklist import extract as extractor
from api.modules.fulfillment.picklist import qrcode_payload, repository as picklist_repo
from api.repositories import order_repo, product_repo

logger = get_logger(__name__)


class PicklistIngestError(Exception):
    """This PDF cannot become a pick list. Carries a message meant for the uploader."""


# ── Upload ───────────────────────────────────────────────────────────────────

def ingest_picklist(file_stream, filename, warehouse_id, company_id,
                    user_id, upload_batch_id=None) -> dict:
    """Import one pick-list PDF. One file, one transaction.

    Returns a summary dict for the uploader. Raises PicklistIngestError with a
    message worth showing to a human when the file cannot be imported.
    """
    meta = extractor.extract(file_stream, source_filename=filename)

    order_no = (meta['order'].get('order_no') or '').strip()
    picklist_code = (meta['order'].get('code') or '').strip()

    # A payload that cannot be built would produce a QR nobody can parse, so fail
    # here rather than after writing the row.
    if qrcode_payload.SEP in order_no or qrcode_payload.SEP in picklist_code:
        raise PicklistIngestError(
            "the order number or pick-list code contains %r, which the QR payload "
            "uses as its separator" % qrcode_payload.SEP)

    potential_order = _match_order(order_no)

    # The uploader picks a company; the order carries its own. A mismatch means the
    # operator has the wrong tenant selected, and importing anyway would file the
    # document under a company that cannot see the order it points at.
    if potential_order.company_id and company_id and potential_order.company_id != company_id:
        raise PicklistIngestError(
            "order %s belongs to a different company than the one selected for this "
            "upload" % order_no)

    lines = meta.get('lines') or []
    current_time = datetime.utcnow()
    existing = picklist_repo.find_existing(potential_order.potential_order_id, picklist_code)

    with mysql_manager.get_cursor(commit=False) as cursor:
        try:
            products_created = _sync_products(cursor, lines, company_id, current_time)
            # Re-read on the SAME cursor: the products just created are uncommitted,
            # and a pooled connection would not see them.
            products_map = product_repo.find_bulk_by_part_numbers_on(
                cursor, [ln['part'] for ln in lines if ln.get('part')])

            line_rows, unresolved = _order_product_rows(
                potential_order.potential_order_id, lines, products_map, current_time)
            product_repo.replace_order_products_on(
                cursor, potential_order.potential_order_id, line_rows)

            row = {
                'potential_order_id': potential_order.potential_order_id,
                'original_order_id': order_no,
                'picklist_code': picklist_code,
                'picklist_date': meta['order'].get('order_date_iso'),
                'line_count': len(lines),
                'meta': meta,
                'warehouse_id': warehouse_id,
                'company_id': company_id or potential_order.company_id,
                'upload_batch_id': upload_batch_id,
                'created_by': user_id,
            }

            if existing:
                # Keep the token so sheets already printed keep resolving.
                picklist_repo.update_in_place(cursor, existing['picklist_id'], row)
                picklist_id = existing['picklist_id']
                qr_token = existing['qr_token']
                replaced = True
            else:
                row['qr_token'] = qrcode_payload.new_token()
                picklist_id = picklist_repo.insert(cursor, row)
                qr_token = row['qr_token']
                replaced = False

            cursor.connection.commit()
        except Exception:
            cursor.connection.rollback()
            raise

    logger.info("Pick list ingested", extra={
        'picklist_id': picklist_id,
        'order_no': order_no,
        'lines': len(lines),
        'products_created': products_created,
        'unresolved': len(unresolved),
        'replaced': replaced,
    })

    return {
        'picklist_id': picklist_id,
        'qr_token': qr_token,
        'original_order_id': order_no,
        'picklist_code': picklist_code,
        'order_status': potential_order.status,
        'line_count': len(lines),
        'products_created': products_created,
        'unresolved_parts': unresolved,
        'replaced': replaced,
    }


def _match_order(order_no: str):
    """Find the order this pick list names. Never creates one."""
    if not order_no:
        raise PicklistIngestError("the pick list carries no order number")

    matches = order_repo.find_bulk_by_original_ids([order_no])
    order = matches.get(order_no)
    if not order:
        # find_bulk_by_original_ids only searches the active partition window, so an
        # order older than that window is indistinguishable here from one that was
        # never uploaded. Say so, rather than claiming it does not exist.
        raise PicklistIngestError(
            "no order %s found in the current data window — upload the order file "
            "first, or check the order number" % order_no)
    return order


def _sync_products(cursor, lines, company_id, current_time) -> int:
    """Create catalogue entries for parts this pick list names and the master lacks."""
    part_numbers = [ln['part'] for ln in lines if ln.get('part')]
    if not part_numbers:
        return 0

    known = product_repo.find_bulk_by_part_numbers_on(cursor, part_numbers)

    new_products = {}
    for line in lines:
        part = line.get('part')
        if not part or part in known or part in new_products:
            continue
        new_products[part] = {
            'part': part,
            'name': line.get('desc') or part,
            'hsn': line.get('hsn'),
            'price': line.get('mrp'),
        }

    if new_products:
        product_repo.bulk_upsert_products_on(
            cursor, list(new_products.values()), current_time, company_id)
    return len(new_products)


def _order_product_rows(potential_order_id, lines, products_map, current_time):
    """Build potential_order_product tuples; report parts that still did not resolve.

    Quantity is the pick list's Order Qty, not its Allocated Qty. They are equal on a
    fully-allocated sheet, but potential_order_product.quantity means "what the order
    asked for" everywhere else in the app, and a short allocation must not silently
    shrink the order. The allocated figure survives in meta.
    """
    rows = []
    unresolved = []

    for line in lines:
        part = line.get('part')
        product = products_map.get(part) if part else None
        if not product:
            unresolved.append(part or '(blank)')
            continue

        qty = line.get('order_qty') or 0
        mrp = line.get('mrp')
        total = None
        if mrp is not None:
            try:
                total = round(float(mrp) * qty, 2)
            except (TypeError, ValueError):
                total = None

        rows.append((
            potential_order_id,
            product['product_id'],
            qty,
            0,            # quantity_packed
            qty,          # quantity_remaining
            mrp,
            total,
            current_time,
            current_time,
        ))

    return rows, unresolved


# ── Scan ─────────────────────────────────────────────────────────────────────

# Implicit next state, for a scan that does not name a target. Mirrors
# OrderStateMachine.BULK_TRANSITIONS; kept as its own map so a change to bulk
# uploads cannot silently change what a warehouse scanner does.
NEXT_STATE = {
    OrderStatus.OPEN: OrderStatus.PICKING,
    OrderStatus.PICKING: OrderStatus.PACKED,
    OrderStatus.DISPATCH_READY: OrderStatus.COMPLETED,
}


class ScanRejected(Exception):
    """A scan that changed nothing. `result` is the audit code."""

    def __init__(self, result, message, picklist_id=None,
                 from_status=None, to_status=None):
        super().__init__(message)
        self.result = result
        self.message = message
        self.picklist_id = picklist_id
        self.from_status = from_status
        self.to_status = to_status


def resolve_scan(payload: str):
    """Turn a scanned payload into (picklist_row, potential_order).

    The pick list is fetched by TOKEN and the payload's order number is then
    compared against the row that came back. Looking it up by order number instead
    would make the token decorative: order numbers are printed in plain text on
    every sheet, so anyone could move any order by typing one in.
    """
    try:
        parsed = qrcode_payload.parse(payload)
    except qrcode_payload.PayloadError as e:
        raise ScanRejected('bad_payload', str(e))

    picklist = picklist_repo.find_by_token(parsed['token'])
    if not picklist:
        raise ScanRejected('unknown_token', 'This QR code is not recognised.')

    if picklist['original_order_id'].upper() != parsed['order_no']:
        raise ScanRejected(
            'mismatch',
            'This QR code does not match the order it names.',
            picklist_id=picklist['picklist_id'])
    if (picklist['picklist_code'] or '').upper() != parsed['picklist_code']:
        raise ScanRejected(
            'mismatch',
            'This QR code does not match the pick list it names.',
            picklist_id=picklist['picklist_id'])

    order = order_repo.find_by_id(picklist['potential_order_id'])
    if not order:
        raise ScanRejected(
            'unknown_token',
            'The order this pick list points at no longer exists.',
            picklist_id=picklist['picklist_id'])

    return picklist, order


def plan_transition(order, target_status=None):
    """Decide what a scan moves this order to. Raises ScanRejected if nothing legal.

    `target_status` comes from the scanning station when the handheld is configured
    for one. Prefer it: a station knows it is the packing bench, so a second scan
    there reports "already Packed" instead of pushing the order a step further.
    Without one the order advances implicitly, which cannot tell a deliberate rescan
    from a double-trigger.
    """
    current = order.status

    if target_status:
        try:
            target = OrderStatus.from_frontend_slug(
                str(target_status).lower().replace(' ', '-'))
        except ValueError:
            raise ScanRejected('illegal_transition',
                               'Unknown target status %r.' % target_status,
                               from_status=current)

        if current == target:
            raise ScanRejected(
                'duplicate',
                'This order is already %s.' % target.value,
                from_status=current, to_status=target.value)

        if not OrderStateMachine.can_bulk_transition(current, target):
            raise ScanRejected(
                'illegal_transition',
                'An order in %s cannot move to %s by scanning.' % (current, target.value),
                from_status=current, to_status=target.value)
        return target

    target = NEXT_STATE.get(current)
    if not target:
        raise ScanRejected(
            'illegal_transition',
            'An order in %s cannot be advanced by scanning.' % current,
            from_status=current)
    return target
