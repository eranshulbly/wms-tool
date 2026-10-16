# -*- encoding: utf-8 -*-
"""Order tracking routes (handheld):

  GET /api/v1/tracking/search?q=        — scan, order number, last digits, or dealer
  GET /api/v1/tracking/orders/<id>      — one order's full story

Read-only. Gated on order:read, which every warehouse account already holds —
looking up where an order got to is not a privilege, and making it one would
just push people back to asking the office.
"""

from flask import request
from flask_restx import Resource

from api.core.logging import get_logger
from api.extensions import rest_api
from api.modules.fulfillment.tracking import service as svc
from api.modules.platform.user_auth.rbac import P
from api.shared.auth_v1 import company_scope, v1_require_permission

logger = get_logger(__name__)

MAX_QUERY = 128


@rest_api.route('/api/v1/tracking/search')
class V1TrackingSearch(Resource):
    """Resolve a scan, an order number, its last digits, or a dealer name."""

    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user):
        q = (request.args.get('q') or '').strip()[:MAX_QUERY]
        if not q:
            return {'mode': 'list', 'items': [], 'total': 0, 'query': ''}, 200
        try:
            return svc.search(q, company_scope(current_user)), 200
        except Exception as e:
            logger.exception("Order tracking search failed", extra={'q': q})
            return {'detail': 'Could not search: %s' % e}, 400


@rest_api.route('/api/v1/tracking/orders/<int:potential_order_id>')
class V1TrackingOrder(Resource):
    """One order, picked from a search result list."""

    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user, potential_order_id):
        try:
            order = svc.detail(potential_order_id, company_scope(current_user))
        except Exception as e:
            logger.exception("Order tracking detail failed",
                             extra={'potential_order_id': potential_order_id})
            return {'detail': 'Could not load this order: %s' % e}, 400
        if not order:
            return {'detail': 'That order was not found.'}, 404
        return {'mode': 'order', 'order': order}, 200
