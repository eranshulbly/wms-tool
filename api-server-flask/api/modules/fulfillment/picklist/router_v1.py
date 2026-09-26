# -*- encoding: utf-8 -*-
"""Mobile API for moving an order by scanning its pick-list QR code.

  POST /api/v1/picklists/scan   — resolve a scanned code, change nothing
  POST /api/v1/picklists/move   — apply one move

Two calls rather than one on purpose. A pick list riding a trolley cannot tell the
operator it is the wrong sheet; the order number and dealer on screen can. Scan
shows them what they scanned and which moves they may make, and only the second
call touches an order.

Which moves a user may make comes from their permission codes — order:move_pickpack
for Picking and Packed, order:move_dispatch for Dispatch Ready — which rbac derives
from the order states their role already holds. The endpoints themselves require
only that the caller holds one of the two; which specific target is allowed is
decided per order, because it depends on where that order currently is.
"""

from flask import request
from flask_restx import Resource

from api.core.logging import get_logger
from api.extensions import rest_api
from api.modules.fulfillment.picklist import service as picklist_service
from api.modules.platform.user_auth.rbac import P
from api.shared.auth_v1 import v1_auth_required
from api.shared.idempotency import idempotent, InProgress

logger = get_logger(__name__)

_MOVE_CODES = (P.ORDER_MOVE_PICKPACK, P.ORDER_MOVE_DISPATCH)


def _missing_move_permission(current_user):
    """Refuse a caller who holds neither move grant.

    v1_require_permission takes a single code; this screen is open to either, so the
    check is here. Whether the specific target is allowed is decided later, per
    order, by business.allowed_targets.
    """
    codes = set(current_user.get('permissions') or [])
    if codes.intersection(_MOVE_CODES):
        return None
    return {'detail': 'Missing permission: %s or %s' % _MOVE_CODES}, 403


@rest_api.route('/api/v1/picklists/scan')
class V1PicklistScan(Resource):
    """Resolve a scanned QR payload. Read-only — nothing moves."""

    @v1_auth_required
    def post(self, current_user):
        denied = _missing_move_permission(current_user)
        if denied:
            return denied

        body = request.get_json(silent=True) or {}
        payload = (body.get('payload') or '').strip()
        if not payload:
            return {'success': False, 'result': 'bad_payload',
                    'msg': 'No QR payload was sent.'}, 400

        return picklist_service.preview_scan(payload, current_user)


@rest_api.route('/api/v1/picklists/move')
class V1PicklistMove(Resource):
    """Apply one move to the order behind a scanned pick list."""

    @v1_auth_required
    def post(self, current_user):
        denied = _missing_move_permission(current_user)
        if denied:
            return denied

        try:
            # A handheld on warehouse wifi retries writes it never saw acknowledged.
            # Without this, a retried move is applied twice and walks the order an
            # extra state along — the exact failure the QR is meant to prevent.
            with idempotent(current_user['user_id'], 'picklists.move') as guard:
                if guard.replayed:
                    return guard.response
                body, status = self._move(current_user)
                return guard.store(body, status)
        except InProgress as e:
            # Same key still in flight. The app's queue simply tries again.
            return {'detail': str(e)}, 409

    def _move(self, current_user):
        body = request.get_json(silent=True) or {}
        payload = (body.get('payload') or '').strip()
        if not payload:
            return {'success': False, 'result': 'bad_payload',
                    'msg': 'No QR payload was sent.'}, 400

        return picklist_service.apply_scan(
            payload,
            current_user,
            target_status=body.get('target_status'),
            box_count=body.get('box_count'),
            device_id=body.get('device_id'),
        )
