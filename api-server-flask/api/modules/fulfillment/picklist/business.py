# -*- encoding: utf-8 -*-
"""picklist module — what an upload does, and what a scan does.

Upload does NOT move an order. It attaches a document to an order that is already
in potential_order (typically Open), fills in that order's line items, and mints a
QR token. The order's status is untouched.

Scan is what moves it, one step along OrderStateMachine's chain.
"""

import re
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

def _normalise_party(name):
    """A party name reduced to what identifies it, for comparison only.

    Case, punctuation and spacing differ between the header block and the Name field on
    the same sheet ("OM MARKETING" against "Om Marketing,"), so comparing them raw misses
    the match the whole check depends on.
    """
    return ''.join(ch for ch in str(name or '').lower() if ch.isalnum())


# Order-number segments that mark an internal distribution sheet rather than a customer
# order. Measured against every pick list on file: of 353 MPDSTN orders, 353 carried the
# distributor as their dealer; of 3,816 PSAO orders, none did.
_INTERNAL_ORDER_SEGMENTS = ('-MPDSTN-',)


def _names_the_distributor(meta) -> bool:
    """True when this sheet names its own issuer rather than a customer.

    Two independent tests, because either source alone has a blind spot.

    The order number is the stronger one. An internal sheet carries a distribution
    segment (…-MPDSTN-…), it is always present — extraction refuses a sheet without an
    order number at all — and on 4,169 real pick lists it has never once been wrong in
    either direction.

    The header comparison catches the rest: `header.distributor_name` is the centred
    block above 'Pick List' and `order.dealer_name` is the Name field, both off the same
    page, so a sheet whose Name is its own issuer is internal whatever its number says.
    That test alone is NOT enough — the header fails to parse on 17% of these sheets, and
    one such sheet is exactly how 30305-02-MPDSTN-1026-3369 got filed under OM MARKETING
    after this check was already live.

    Neither test guesses: when the order number is ordinary and the header is unreadable,
    this returns False and the sheet imports as before.
    """
    order_no = ((meta.get('order') or {}).get('order_no') or '').upper()
    if any(seg in order_no for seg in _INTERNAL_ORDER_SEGMENTS):
        return True

    distributor = _normalise_party((meta.get('header') or {}).get('distributor_name'))
    named = _normalise_party((meta.get('order') or {}).get('dealer_name'))
    if not distributor or not named:
        return False
    # One is often the other with a suffix ("OM MARKETING" / "OM MARKETING PVT LTD"),
    # so containment either way counts as the same party.
    return distributor == named or named.startswith(distributor) or distributor.startswith(named)


def ingest_picklist(file_stream, filename, warehouse_id, company_id,
                    user_id, upload_batch_id=None, dealer_name_override=None) -> dict:
    """Import one pick-list PDF. One file, one transaction.

    Returns a summary dict for the uploader. Raises PicklistIngestError with a
    message worth showing to a human when the file cannot be imported.
    """
    meta = extractor.extract(file_stream, source_filename=filename)

    # A typed dealer name replaces the one printed on the sheet.
    #
    # Internal (MPDSTN) sheets name the distributor itself in the Name field,
    # so all 21 of them landed under OM MARKETING and the actual retail customer
    # was recorded nowhere. The uploader knows who it was; the sheet does not.
    #
    # The sheet's own value is KEPT alongside rather than overwritten. Six months
    # on, 'the sheet said OM MARKETING and Anurag typed Ramesh Traders' is a
    # different fact from 'the sheet said Ramesh Traders', and only one of them
    # can be checked against the paper. Whether the caller is allowed to do this
    # is settled in the router, on the role — never here.
    override = (dealer_name_override or '').strip()
    if override:
        meta['order']['dealer_name_on_sheet'] = meta['order'].get('dealer_name') or ''
        meta['order']['dealer_name'] = override
        meta['order']['dealer_name_entered_by'] = user_id
    elif _names_the_distributor(meta):
        # The sheet names US, so there is no customer on it to import.
        #
        # Accepting it anyway is what put 352 orders under a dealer called OM MARKETING,
        # with the actual customer recorded nowhere and unrecoverable from anything but
        # the paper. Refusing costs one upload; accepting costs an order filed against a
        # dealer that is not a dealer, and nobody notices until someone asks who bought it.
        #
        # Decided by comparing the Name field with the distributor block the sheet itself
        # prints at the top, rather than by matching 'OM MARKETING': the rule is "this
        # sheet names its own issuer", which stays true for any distributor and any
        # rename, and needs no configuration to keep in step.
        raise PicklistIngestError("Enter a valid dealer name.")

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

    # ONE PICK LIST PER ORDER. A second upload is refused, not merged.
    #
    # It used to replace the row in place, and that quietly destroyed the thing
    # the sheet is for. The order's line items are wiped and re-inserted from
    # the new PDF, so a sheet already printed and walking round the warehouse
    # would no longer describe what the system thinks is on it — and nothing
    # recorded that it had changed. The QR on the paper kept working, pointing
    # at different contents.
    #
    # Refusing also closes the gap the old (order, code) key left open: a second
    # sheet for the same order under a DIFFERENT code was not a replace at all,
    # it was a second row — two live QR codes for one order, both scannable, and
    # two people able to move it.
    #
    # The database's uq_picklist_order_code is still the backstop for the exact
    # same code arriving twice at once; this is the check that covers the rest.
    if potential_order is not None:
        clash = picklist_repo.find_any_for_order(potential_order.potential_order_id)
        if clash:
            raise PicklistIngestError(_duplicate_message(order_no, clash))

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

            # Always an insert now. The duplicate check above is what decides
            # whether we get here at all, and there is no in-place update path
            # left: a pick list is written once and then only ever read.
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
        # Echoed so the upload log can say the name was typed, not read.
        'dealer_name_overridden': bool(override),
        'line_count': len(lines),
        'products_created': products_created,
        'unresolved_parts': unresolved,
        'replaced': replaced,
    }


def _duplicate_message(order_no: str, clash: dict) -> str:
    """Why this upload was refused, in terms the uploader can act on.

    Names the sheet that is already on file and whether it has been printed,
    because those are different situations: an unprinted one is a mistake to
    undo, a printed one is paper somebody may already be holding.
    """
    when = clash.get('created_at')
    who = clash.get('uploaded_by_name') or 'someone'
    code = clash.get('picklist_code') or 'no code'

    detail = 'uploaded %s by %s' % (
        when.strftime('%d %b %Y at %H:%M') if when else 'earlier', who)

    if clash.get('printed_at'):
        state = ('It has already been PRINTED%s, so a paper copy may be on the '
                 'floor.' % (' %d times' % clash['print_count']
                             if (clash.get('print_count') or 0) > 1 else ''))
    else:
        state = 'It has not been printed yet.'

    return (
        'Duplicate pick list — order %s already has one (code %s, %s). %s '
        'Re-uploading would rewrite that order\'s lines underneath a sheet '
        'that may already be printed, so it is refused. Remove the existing '
        'pick list first if this one is meant to replace it.'
        % (order_no, code, detail, state))


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
    # Its own grant, so holding move_pickpack does not confer the ability to
    # end an order.
    OrderStatus.CANCELLED:      PermissionCode.ORDER_CANCEL,
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


# What a human types when the QR will not read: the last digits of the order
# number off the printed sheet ("3002" for 30305-02-MPDSTN-0926-3002).
#
# Three at minimum. Fewer is not a shortcut, it is a guess — two digits would
# match a dozen sheets and the operator would spend longer reading the
# disambiguation list than the whole number.
_RE_ORDER_SUFFIX = re.compile(r'^[0-9]{3,10}$')

# A whole order number, typed out.
_RE_ORDER_NO_FULL = re.compile(r'^[0-9A-Z]+(?:-[0-9A-Z]+){2,}$')


def resolve_typed(entry: str):
    """Resolve what an operator TYPED, when the QR could not be scanned.

    Four forms, strongest identifier first:

      1. the whole payload, pasted or re-scanned            -> handled by caller
      2. the 16-character token printed under the symbol    -> exact, safe
      3. the whole order number                             -> exact
      4. the last digits of the order number                -> may be ambiguous

    **This is deliberately weaker than a scan, and that is the trade-off.** A
    scan proves possession of the printed sheet, because the token is the only
    way in; a typed suffix proves only that somebody knows five digits. It is
    still behind a login and the same permission gate, and it only reaches
    sheets whose orders are live — but it does mean the sheet is no longer
    required. That is the price of a fallback for a creased or smudged symbol,
    and the alternative is an operator who cannot move a real order at all.

    Ambiguity is REFUSED, never resolved by picking the newest. The suffix is a
    per-series counter and there are already two series in play (PSAO around
    45000, MPDSTN around 3000), so two sheets sharing a suffix is a matter of
    time. Moving the wrong dealer's order is not recoverable by the person who
    did it — they would not know it happened.
    """
    text = (entry or '').strip().upper()
    if not text:
        raise ScanRejected('bad_payload', 'Nothing was entered.')

    # The token: exact, and as strong as a scan because it IS what the scan
    # carries. Checked before the suffix so an all-digit token cannot be
    # mistaken for one (the alphabet is base32, so that cannot happen today,
    # but the ordering costs nothing and does not depend on that staying true).
    if (len(text) == qrcode_payload.TOKEN_LENGTH
            and all(c in qrcode_payload._ALPHABET for c in text)):
        picklist = picklist_repo.find_by_token(text)
        if not picklist:
            raise ScanRejected('unknown_token', 'That code is not recognised.')
        return picklist

    if _RE_ORDER_SUFFIX.match(text):
        matches = picklist_repo.find_live_by_order_suffix(text)
    elif _RE_ORDER_NO_FULL.match(text):
        matches = picklist_repo.find_live_by_order_no(text)
    else:
        raise ScanRejected(
            'bad_payload',
            'Enter the last digits of the order number, or the whole number.')

    if not matches:
        raise ScanRejected(
            'unknown_code',
            'No live pick list ends in %s. Check the number on the sheet.' % text)

    if len(matches) > 1:
        listed = ', '.join(m['original_order_id'] for m in matches[:4])
        raise ScanRejected(
            'ambiguous_code',
            '%s matches %d pick lists (%s). Enter more digits.'
            % (text, len(matches), listed))

    return matches[0]


def resolve_scan(payload: str):
    """Turn a scanned payload into (picklist_row, potential_order).

    The pick list is fetched by TOKEN and the payload's order number is then
    compared against the row that came back. Looking it up by order number instead
    would make the token decorative: order numbers are printed in plain text on
    every sheet, so anyone could move any order by typing one in.

    A payload that is not in the scanned format is treated as something a human
    typed — see resolve_typed, which is explicit about being the weaker path.
    """
    try:
        parsed = qrcode_payload.parse(payload)
    except qrcode_payload.PayloadError:
        # Not a scan. The cross-checks below have nothing to compare against, so
        # resolve_typed returns the row directly and we skip them; it does its
        # own exact matching instead.
        picklist = resolve_typed(payload)
        order = order_repo.find_by_id(picklist['potential_order_id'])
        if not order:
            raise ScanRejected(
                'unknown_token',
                'The order this pick list points at no longer exists.',
                picklist_id=picklist['picklist_id'])
        return picklist, order

    picklist = picklist_repo.find_by_token(parsed['token'])
    superseded = False
    if not picklist:
        # The token is not on file, and the usual reason is not a forgery: the sheet was
        # REISSUED. Deleting a pick list and uploading the sheet again mints a new token,
        # while the sheet already on the trolley still carries the old one. Refusing it
        # strands a picker holding a real sheet for a live order, and the only way out is
        # to find and reprint it — so the scan falls back to the order number the sheet
        # itself names.
        #
        # This grants nothing new. resolve_typed already accepts a whole order number as
        # an exact identifier, so moving an order without a valid token is a capability
        # the system has always had; a scan that reaches this point has in fact proved
        # more, because the payload came off a printed sheet.
        matches = picklist_repo.find_live_by_order_no(parsed['order_no'])
        if len(matches) > 1:
            # Never resolved by taking the newest: moving the wrong dealer's order is not
            # something the person who did it would notice.
            raise ScanRejected(
                'ambiguous_code',
                'Order %s has %d live pick lists. Use the current sheet.'
                % (parsed['order_no'], len(matches)))
        if not matches:
            raise ScanRejected('unknown_token', 'This QR code is not recognised.')
        picklist = matches[0]
        superseded = True

    if picklist['original_order_id'].upper() != parsed['order_no']:
        raise ScanRejected(
            'mismatch',
            'This QR code does not match the order it names.',
            picklist_id=picklist['picklist_id'])
    # The pick-list code is checked only when the token resolved. On a reissued sheet the
    # code legitimately differs from the one now on file — that difference IS the reissue,
    # and refusing on it would undo the fallback above.
    if not superseded and (picklist['picklist_code'] or '').upper() != parsed['picklist_code']:
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
