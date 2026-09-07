# -*- encoding: utf-8 -*-
"""Admin API — stock movement analytics (/api/admin/inventory/analytics/*).

  GET  /movement                   per product: run rate, cover, expiry and risk band

Read-only and derived on every call. Nothing here is cached or stored, so the report
cannot drift from the stock and ledger rows it describes.
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.inventory import movement as mv

logger = get_logger(__name__)

BASE = '/api/admin/inventory/analytics'


@rest_api.route(f'{BASE}/movement')
class MovementReport(Resource):
    @token_required
    @active_required
    def get(self, current_user):
        from api.permissions import resolve_company_scope

        # An unscoped admin gets None (every company); a scoped one gets their list. A
        # requested company outside that list resolves to nothing rather than to itself.
        company_ids = resolve_company_scope(current_user, request.args.get('company_id'))

        try:
            window = int(request.args.get('window_days') or 90)
        except (TypeError, ValueError):
            window = 90
        if window not in mv.WINDOW_CHOICES:
            window = 90

        try:
            report = mv.movement_report(company_ids=company_ids, window_days=window)
        except Exception:
            logger.exception("movement report failed")
            return {'success': False, 'msg': 'Could not build the stock movement report'}, 500

        return {'success': True, 'bands': list(mv.BANDS), **report}, 200
