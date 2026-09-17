# -*- encoding: utf-8 -*-
"""
Sales report route (admin web):

  GET /api/admin/sales-report   product + dealer breakdowns of invoiced sales
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.permissions import resolve_company_scope, CompanyAccessDenied
from api.modules.sales.report import service as svc

logger = get_logger(__name__)

BASE = '/api/admin/sales-report'


@rest_api.route(BASE)
class SalesReport(Resource):
    """Product and dealer sales breakdowns — admin only, same rule as Order Margin:
    the figures carry landed cost wherever a line's batch is on file."""

    @token_required
    @active_required
    def get(self, current_user):
        if getattr(current_user, 'role', None) != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403

        try:
            scope = resolve_company_scope(current_user, request.args.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        date_from = (request.args.get('from') or '').strip() or None
        date_to = (request.args.get('to') or '').strip() or None

        try:
            report = svc.sales_report(scope, date_from, date_to)
        except Exception:
            logger.exception('sales report failed',
                             extra={'company_id': request.args.get('company_id')})
            return {'success': False, 'msg': 'Could not build the sales report.'}, 500

        return {'success': True, **report, 'from': date_from, 'to': date_to}, 200
