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
from api.modules.platform.catalog import dealer_business  # cross-module: catalog owns dealers
from api.modules.platform.user_auth.rbac import P as PermissionCode
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
    if (potential_order is not None and potential_order.company_id and company_id
            and potential_order.company_id != company_id):
        raise PicklistIngestError(
            "order %s belongs to a different company than the one selected for this "
            "upload" % order_no)

    lines = meta.get('lines') or []
    current_time = datetime.utcnow()
    existing = (picklist_repo.find_existing(potential_order.potential_order_id, picklist_code)
                if potential_order is not None else None)

    with mysql_manager.get_cursor(commit=False) as cursor:
        try:
            order_created = potential_order is None
            if order_created:
                potential_order = _create_order_from_picklist(
                    cursor, meta, order_no, warehouse_id, company_id,
                    user_id, upload_batch_id, current_time)

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
                # But forget that it was printed. Any paper already on the trolley
                # describes the PREVIOUS version of this sheet, so it is not a
                # printed copy of the one that just replaced it — and leaving the
                # mark would hide the reprint from the very filter that exists to
                # catch it. The token survives; the print state does not.
                picklist_repo.clear_printed_on(cursor, existing['picklist_id'])
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
        'order_created': order_created,
    })

    return {
        'picklist_id': picklist_id,
        'qr_token': qr_token,
        'original_order_id': order_no,
        'picklist_code': picklist_code,
        'potential_order_id': potential_order.potential_order_id,
        'order_status': potential_order.status,
        # True when this upload created the order rather than attaching to one that
        # was already there. Surfaced so the operator can tell the two apart.
        'order_created': order_created,
        'dealer_name': (meta.get('order') or {}).get('dealer_name') or '',
        'line_count': len(lines),
        'products_created': products_created,
        'unresolved_parts': unresolved,
        'replaced': replaced,
    }


def _match_order(order_no: str):
    """Find the order this pick list names. Returns None when it genuinely does not
    exist anywhere, in which case the caller creates it.

    The lookup is deliberately UNWINDOWED. find_bulk_by_original_ids() only searches
    the active partition window, so it cannot distinguish "never uploaded" from
    "older than the window" — and since potential_order has no unique index on
    original_order_id, creating on a windowed miss would quietly produce a second row
    for an order that already exists.
    """
    if not order_no:
        raise PicklistIngestError("the pick list carries no order number")
    return order_repo.find_any_by_original_id(order_no)


def _create_order_from_picklist(cursor, meta, order_no, warehouse_id, company_id,
                                user_id, upload_batch_id, current_time):
    """Create the order this pick list describes, because nothing else has.

    An order born this way is thinner than one from the order-file upload: the pick
    list prints the order number, date, dealer and city, and nothing else the order
    table wants. B2B PO#, order type, VIN, shipping address and SAP code are simply
    not on the document, so they stay NULL rather than being guessed at.

    It lands in exactly the state the order upload would leave it in — status Open
    with an Open row in order_state_history — so everything downstream (the dashboard,
    bulk transitions, scanning) treats it identically.
    """
    order = meta.get('order') or {}
    dealer_name = (order.get('dealer_name') or '').strip()
    city = (order.get('city') or '').strip()

    dealer_id = None
    if dealer_name:
        try:
            dealer_id = dealer_business.get_or_create_dealer(dealer_name)
            if dealer_id and city:
                # Only fills a blank. The pick list is a weaker source than whatever
                # a human or the dealer master already put there.
                dealer_business.set_town_if_absent(dealer_id, city)
        except Exception as e:
            # A dealer we cannot resolve must not lose us the order; the name is kept
            # on the order itself either way.
            logger.warning("Could not resolve dealer for pick list",
                           extra={'dealer_name': dealer_name, 'error': str(e)})

    order_date = order.get('order_date_iso') or current_time

    potential_order_id = order_repo.insert_potential_order_on(cursor, {
        'original_order_id': order_no,
        'purchaser_name': dealer_name or None,
        'dealer_id': dealer_id,
        'order_date': order_date,
        'warehouse_id': warehouse_id,
        'company_id': company_id,
        'requested_by': user_id,
        'status': OrderStatus.OPEN.value,
        'box_count': 1,
        'upload_batch_id': upload_batch_id,
        'created_at': current_time,
        # Not on a pick list — left NULL rather than invented:
        'b2b_po_number': None,
        'order_type': None,
        'vin_number': None,
        'shipping_address': None,
        'source_created_by': None,
        'purchaser_sap_code': None,
    })

    state = order_repo.get_or_create_state(
        OrderStatus.OPEN.value, 'Order is open and ready for processing')
    order_repo.create_state_history_on(
        cursor, potential_order_id, state.state_id, user_id, current_time)

    logger.info("Order created from pick list",
                extra={'potential_order_id': potential_order_id,
                       'original_order_id': order_no, 'dealer_id': dealer_id})

    return order_repo.build_potential_order({
        'potential_order_id': potential_order_id,
        'original_order_id': order_no,
        'purchaser_name': dealer_name or None,
        'dealer_id': dealer_id,
        'warehouse_id': warehouse_id,
        'company_id': company_id,
        'status': OrderStatus.OPEN.value,
        'created_at': current_time,
    })


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

# Which permission code lets a scan reach which state.
#
# The floor is split in two and so is this: pick-and-pack staff move orders through
# Picking and Packed; releasing for dispatch is a separate grant because, on the
# scan path, it happens without an invoice.
#
# Both codes are derived from the role's existing order-state grants in
# rbac._legacy_codes_for_user, so the Roles screen stays the one place this is
# configured.
TARGET_PERMISSION = {
    OrderStatus.PICKING:        PermissionCode.ORDER_MOVE_PICKPACK,
    OrderStatus.PACKED:         PermissionCode.ORDER_MOVE_PICKPACK,
    OrderStatus.DISPATCH_READY: PermissionCode.ORDER_MOVE_DISPATCH,
    OrderStatus.COMPLETED:      PermissionCode.ORDER_MOVE_DISPATCH,
}


def allowed_targets(order, permission_codes) -> list:
    """The states THIS user may scan THIS order into, in the order to offer them.

    Two filters, and both matter. The state machine says what is reachable from the
    order's current status; the user's permissions say which of those they may do.
    An empty list means the scan is legible but this person cannot act on it — which
    is a different message from "that code is not recognised", and the handheld says
    so.
    """
    codes = set(permission_codes or [])
    return [
        target for target in OrderStateMachine.scan_targets(order.status)
        if TARGET_PERMISSION.get(target) in codes
    ]


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


def plan_transition(order, permission_codes, target_status=None):
    """Decide what a scan moves this order to. Raises ScanRejected if nothing legal.

    `target_status` is what the operator chose on the handheld after seeing the
    order. Pass it whenever it is known: an explicit target makes a second scan of
    the same sheet report "already Packed" rather than pushing the order another
    step along, which is the difference between a deliberate rescan and a
    double-trigger.

    Omitting it is allowed only where it is unambiguous — exactly one move open to
    this user — and refused with 'ambiguous' otherwise.
    """
    current = order.status

    permitted = allowed_targets(order, permission_codes)

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

        if not OrderStateMachine.can_scan_transition(current, target):
            raise ScanRejected(
                'illegal_transition',
                'An order in %s cannot move to %s by scanning.' % (current, target.value),
                from_status=current, to_status=target.value)

        if target not in permitted:
            raise ScanRejected(
                'no_access',
                'You do not have permission to move orders to %s.' % target.value,
                from_status=current, to_status=target.value)
        return target

    # No target named — only safe when exactly one move is open to this user.
    # Picking one for them when several are legal is how an order ends up two
    # states further along than anybody intended.
    if not permitted:
        reachable = OrderStateMachine.scan_targets(current)
        if not reachable:
            raise ScanRejected(
                'illegal_transition',
                'An order in %s cannot be advanced by scanning.' % current,
                from_status=current)
        raise ScanRejected(
            'no_access',
            'You do not have permission to move an order out of %s.' % current,
            from_status=current)

    if len(permitted) > 1:
        raise ScanRejected(
            'ambiguous',
            'Choose where to move this order: %s.'
            % ', '.join(t.value for t in permitted),
            from_status=current)

    return permitted[0]
