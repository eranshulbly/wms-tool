# -*- encoding: utf-8 -*-
"""
Sales-executive activity analytics (admin web).

  GET /executives   one row per executive: visits, time on site, orders, sales
  GET /visits       the visit log behind those numbers, newest first

Both take an optional company_id and a from/to date range. The range is applied to
check_in_at for visits, created_at for orders and invoice_date for invoices — each
trail dated by when the thing happened, not when it was recorded.
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.sales.analytics import service as svc

logger = get_logger(__name__)

BASE = '/api/admin/sales/analytics'


def _scope(current_user):
    """Company ids this caller may read, or None for unrestricted (admin)."""
    from api.permissions import resolve_company_scope
    return resolve_company_scope(current_user, request.args.get('company_id'))


def _dates():
    """`from`/`to` as YYYY-MM-DD, or None. Absent means every record on file."""
    def clean(name):
        v = (request.args.get(name) or '').strip()
        return v or None
    return clean('from'), clean('to')


@rest_api.route(f'{BASE}/executives')
class SalesExecutiveSummary(Resource):
    """Per-executive activity summary for the selected window."""

    @token_required
    @active_required
    def get(self, current_user):
        from api.permissions import CompanyAccessDenied
        try:
            scope = _scope(current_user)
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        date_from, date_to = _dates()
        try:
            rows = svc.executive_summary(scope, date_from, date_to)
        except Exception:
            logger.exception("Sales executive summary failed",
                             extra={'company_id': request.args.get('company_id')})
            return {'success': False, 'msg': 'Could not build the sales executive report.'}, 500

        return {
            'success': True,
            'executives': rows,
            'from': date_from,
            'to': date_to,
            # The UI captions the time column with this, so the rule that produced the
            # number travels with it rather than living only in the backend.
            'long_visit_minutes': svc.LONG_VISIT_MINUTES,
        }, 200


@rest_api.route(f'{BASE}/visits')
class SalesExecutiveVisits(Resource):
    """The visit log — where each executive was, when, and for how long."""

    @token_required
    @active_required
    def get(self, current_user):
        from api.permissions import CompanyAccessDenied
        try:
            scope = _scope(current_user)
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        date_from, date_to = _dates()
        try:
            rows = svc.visit_log(scope, date_from, date_to,
                                 user_id=request.args.get('user_id'))
        except Exception:
            logger.exception("Sales executive visit log failed",
                             extra={'company_id': request.args.get('company_id')})
            return {'success': False, 'msg': 'Could not load the visit log.'}, 500

        return {'success': True, 'visits': rows,
                'from': date_from, 'to': date_to,
                'long_visit_minutes': svc.LONG_VISIT_MINUTES}, 200
