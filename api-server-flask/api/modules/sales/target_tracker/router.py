# -*- encoding: utf-8 -*-
"""Target Tracker API (/api/target-tracker/*) — web-authenticated.

One endpoint per step of the screen, so the UI never over-fetches: the picker lists are
their own call, the popup is its own call, and the dashboard is a single round trip.

  GET /companies                      the step-1 options
  GET /months?company_id              the step-2 options, with elapsed fractions
  GET /dashboard?company_id&months&…  KPIs + month strip + the level's tables
  GET /detail?key=&mode=&…            the product popup for one category/scheme
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger
from api.modules.sales.target_tracker import service as tt

logger = get_logger(__name__)


def _list(name):
    """Repeated or comma-separated query params — ?months=2026-07&months=2026-08 and
    ?months=2026-07,2026-08 both work."""
    vals = request.args.getlist(name)
    out = []
    for v in vals:
        out.extend([x.strip() for x in str(v).split(',') if x.strip()])
    return out


def _scope():
    """Build the shared Scope from the request, or raise ValueError for a bad ask."""
    company_id = request.args.get('company_id', type=int)
    if not company_id:
        raise ValueError('company_id is required')
    months = _list('months')
    if not months:
        raise ValueError('at least one month is required')
    return tt.Scope(company_id, months,
                    execs=[int(x) for x in _list('exec')],
                    dealers=[int(x) for x in _list('dealer')],
                    groups=_list('group'), parts=_list('part'))


@rest_api.route('/api/target-tracker/companies')
class TTCompanies(Resource):
    """Step 1. `line` is derived from the company's own data — the active categories it
    sells — rather than stored copy."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            rows = mysql_manager.execute_query(
                """SELECT co.company_id, co.name,
                          (SELECT COUNT(*) FROM dealer d WHERE d.company_id = co.company_id) AS dealers,
                          (SELECT GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR ', ')
                             FROM product p JOIN categories c ON c.category_id = p.category_id
                            WHERE p.company_id = co.company_id AND p.is_active = 1) AS line
                     FROM company co ORDER BY co.name""") or []
            return {'success': True, 'companies': [{
                'id': r['company_id'], 'name': r['name'], 'dealers': r['dealers'],
                'line': r['line'] or 'No products loaded yet',
            } for r in rows]}, 200
        except Exception as e:
            logger.exception('Error in /api/target-tracker/companies')
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/target-tracker/months')
class TTMonths(Resource):
    """Step 2. Only months the company actually has sales or targets for."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            company_id = request.args.get('company_id', type=int)
            if not company_id:
                return {'success': False, 'msg': 'company_id is required'}, 422
            return {'success': True, 'months': tt.available_months(company_id)}, 200
        except Exception as e:
            logger.exception('Error in /api/target-tracker/months')
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/target-tracker/dashboard')
class TTDashboard(Resource):
    """Everything below the filter trail, in one call.

    `level` tells the UI which screen it is on, derived from the filters rather than
    passed in: exactly one executive -> screen 2, exactly one dealer -> screen 3.
    Drill-down is single-month only (§10.1), so a multi-month ask returns level 'all'
    and the month-wise grid however the filters are set.
    """

    @token_required
    @active_required
    def get(self, current_user):
        try:
            s = _scope()
            multi = len(s.months) > 1
            level = 'all'
            if not multi:
                if len(s.dealers) == 1:
                    level = 'dealer'
                elif len(s.execs) == 1:
                    level = 'exec'

            out = {
                'success': True, 'level': level, 'multi_month': multi,
                'months': tt.by_month(s) if multi else [],
                'kpis': tt.kpis(s),
            }
            # The column groups every row table renders: Parts and Other, nothing more.
            # The per-category split lives in the KPI row (and the Other tile's popup) at
            # whatever level the user has drilled to, so the tables stay narrow.
            out['axis'] = tt.table_axis(s, out['kpis']['categories'])
            if level == 'all':
                out['executives'] = tt.by_executive(s)
                if multi:
                    # One achievement cell per month per executive (§5.3 case B), carrying
                    # the full per-category breakdown rather than a combined month total.
                    grid = {}
                    for m in sorted(s.months):
                        sub = tt.Scope(s.company_id, [m], s.execs, s.dealers, s.groups, s.parts)
                        for e in tt.by_executive(sub):
                            grid.setdefault(e['id'], {})[m] = e['cats']
                    out['exec_grid'] = grid
                    out['month_ids'] = sorted(s.months)
            elif level == 'exec':
                out['dealers'] = tt.by_dealer(s)
                out['categories'] = tt.by_category(s, 'category')
                out['schemes'] = tt.by_category(s, 'scheme')
                out['exec'] = next((e for e in tt.by_executive(s) if e['id'] == s.execs[0]), None)
            else:
                out['categories'] = tt.by_category(s, 'category')
                out['schemes'] = tt.by_category(s, 'scheme')
                out['opportunity'] = tt.opportunity(s, s.dealers[0])
                d = mysql_manager.execute_query(
                    """SELECT d.dealer_id, d.name, d.dealer_code, d.town, u.username AS exec_name
                       FROM dealer d LEFT JOIN users u ON u.id = d.sales_executive_id
                       WHERE d.dealer_id = %s""", (s.dealers[0],))
                out['dealer'] = d[0] if d else None
            return out, 200
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 422
        except Exception as e:
            logger.exception('Error in /api/target-tracker/dashboard')
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/target-tracker/detail')
class TTDetail(Resource):
    """The product popup for one category or scheme, at whatever level is filtered."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            key = (request.args.get('key') or '').strip()
            mode = (request.args.get('mode') or 'category').strip()
            if not key:
                return {'success': False, 'msg': 'key is required'}, 422
            if mode not in ('category', 'scheme'):
                return {'success': False, 'msg': 'mode must be category|scheme'}, 422
            return {'success': True, 'detail': tt.detail(_scope(), key, mode)}, 200
        except ValueError as e:
            return {'success': False, 'msg': str(e)}, 422
        except Exception as e:
            logger.exception('Error in /api/target-tracker/detail')
            return {'success': False, 'msg': str(e)}, 400
