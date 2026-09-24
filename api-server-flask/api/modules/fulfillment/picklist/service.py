# -*- encoding: utf-8 -*-
"""picklist module — orchestration.

Upload does not reuse BaseUploadService: that pipeline parses one spreadsheet into
a DataFrame and iterates rows, whereas a pick list is one PDF describing one order.
What it does borrow is the upload_batches bookkeeping, so pick-list uploads appear
in the same admin upload history as everything else.
"""

from datetime import datetime

from api.core.logging import get_logger
from api.db_manager import mysql_manager
from api.models import Order, PotentialOrder
from api.modules.fulfillment.picklist import business, repository as picklist_repo
from api.modules.fulfillment.picklist.extract import PicklistExtractError
from api.repositories import order_repo
from api.shared.upload_utils import create_upload_batch

logger = get_logger(__name__)

UPLOAD_TYPE = 'picklists'


def upload_one(uploaded_file, warehouse_id, company_id, user_id) -> tuple:
    """Import a single pick-list PDF.

    One file per request on purpose. nginx caps request bodies at 12M and gunicorn
    runs a single process on this box, so a browser sending forty PDFs in one POST
    would either 413 or hold the only worker for the whole batch. The frontend
    uploads them one at a time and shows per-file progress instead.

    Returns (response_dict, http_status).
    """
    filename = getattr(uploaded_file, 'filename', '') or ''
    if not filename.lower().endswith('.pdf'):
        return {'success': False, 'filename': filename,
                'msg': 'Pick lists must be PDF files.'}, 400

    upload_batch_id = create_upload_batch(
        mysql_manager, UPLOAD_TYPE, filename, warehouse_id, company_id, user_id)

    try:
        result = business.ingest_picklist(
            uploaded_file.stream, filename, warehouse_id, company_id,
            user_id, upload_batch_id)
    except (PicklistExtractError, business.PicklistIngestError) as e:
        _delete_batch(upload_batch_id)
        return {'success': False, 'filename': filename, 'msg': str(e)}, 400
    except Exception as e:
        logger.exception("Pick-list upload failed", extra={'filename': filename})
        _delete_batch(upload_batch_id)
        return {'success': False, 'filename': filename,
                'msg': 'Could not import this pick list: %s' % e}, 400

    if upload_batch_id:
        mysql_manager.execute_query(
            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
            (result['line_count'], upload_batch_id), fetch=False)

    result['success'] = True
    result['filename'] = filename
    result['upload_batch_id'] = upload_batch_id
    return result, 200


def _delete_batch(upload_batch_id) -> None:
    if not upload_batch_id:
        return
    try:
        mysql_manager.execute_query(
            "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False)
    except Exception:
        pass


# ── Scan ─────────────────────────────────────────────────────────────────────

def apply_scan(payload, user, target_status=None, box_count=None,
               device_id=None) -> tuple:
    """Resolve a scanned QR payload and move its order one step.

    Every outcome, including every rejection, is written to order_picklist_scan —
    a rejected scan leaves no order_state_history row, so without the audit there
    would be nothing at all to look at when someone reports a QR that "does nothing".
    """
    user_id = user.id
    picklist = None
    try:
        picklist, order = business.resolve_scan(payload)
        target = business.plan_transition(order, target_status)

        # Same gate the per-order status endpoints apply: a role that is not trusted
        # to manage orders in a state must not reach that state by scanning either.
        # Checked here rather than in the router so the refusal is audited with the
        # order and target it was refused for.
        from api.permissions import can_see_order_state
        if not can_see_order_state(user.role, target.value):
            raise business.ScanRejected(
                'no_access',
                'You do not have permission to move orders to %s.' % target.value,
                picklist_id=picklist['picklist_id'],
                from_status=order.status, to_status=target.value)
    except business.ScanRejected as e:
        picklist_repo.record_scan(
            e.picklist_id or (picklist or {}).get('picklist_id'), payload, user_id,
            device_id, e.from_status, e.to_status, e.result, e.message)
        status_code = 403 if e.result == 'no_access' else 400
        return {'success': False, 'result': e.result, 'msg': e.message}, status_code

    from_status = order.status

    try:
        new_status = _transition(order, target, user_id, box_count)
    except Exception as e:
        logger.exception("Pick-list scan transition failed",
                         extra={'picklist_id': picklist['picklist_id']})
        picklist_repo.record_scan(
            picklist['picklist_id'], payload, user_id, device_id,
            from_status, target.value, 'error', str(e))
        return {'success': False, 'result': 'error',
                'msg': 'Could not move this order: %s' % e}, 400

    picklist_repo.record_scan(
        picklist['picklist_id'], payload, user_id, device_id,
        from_status, new_status, 'ok')

    return {
        'success': True,
        'result': 'ok',
        'picklist_id': picklist['picklist_id'],
        'original_order_id': picklist['original_order_id'],
        'from_status': from_status,
        'to_status': new_status,
        # A pick list is open while its order is; there is no separate lifecycle.
        'picklist_state': 'open' if new_status in picklist_repo.OPEN_STATUSES else 'closed',
    }, 200


def _transition(order, target, user_id, box_count):
    """Write the status change, its history row, and any knock-on records.

    Returns the status the order actually ended in, which is not always `target` —
    see the invoice_submitted branch.
    """
    now = datetime.utcnow()
    target_value = target.value

    potential_order = PotentialOrder.get_by_id(order.potential_order_id)
    if not potential_order:
        raise RuntimeError('order %s disappeared mid-scan' % order.potential_order_id)

    potential_order.status = target_value
    potential_order.updated_at = now
    if target_value == 'Packed':
        # A scan carries no box count of its own. The handheld prompts for one at the
        # packing bench; when it does not, 1 is assumed and corrected later — the same
        # default the rest of the app uses.
        potential_order.box_count = int(box_count) if box_count else 1
    potential_order.save()

    state = order_repo.get_or_create_state(target_value, '%s state' % target_value)
    order_repo.create_state_history(
        potential_order.potential_order_id, state.state_id, user_id, now)

    # Mirrors the bulk-upload path: an invoice uploaded while the order was still
    # Open or Picking has been waiting for Packed. Without this the order would sit
    # at Packed forever, since the invoice that would have moved it is already spent.
    if target_value == 'Packed' and potential_order.invoice_submitted:
        final_order = Order(
            potential_order_id=potential_order.potential_order_id,
            order_number='ORD-%s-%s' % (potential_order.potential_order_id,
                                        now.strftime('%Y%m%d%H%M')),
            status='Invoiced',
            box_count=potential_order.box_count,
            created_at=now,
            updated_at=now,
        )
        final_order.save()

        potential_order.status = 'Invoiced'
        potential_order.invoice_submitted = False
        potential_order.updated_at = now
        potential_order.save()

        invoiced_state = order_repo.get_or_create_state(
            'Invoiced', 'Invoice uploaded for order')
        order_repo.create_state_history(
            potential_order.potential_order_id, invoiced_state.state_id, user_id, now)
        return 'Invoiced'

    if target_value == 'Completed':
        final_order = order_repo.find_order_by_potential_id(
            potential_order.potential_order_id)
        if final_order:
            final_order.status = 'Completed'
            final_order.dispatched_date = now
            final_order.updated_at = now
            final_order.save()

    return target_value
