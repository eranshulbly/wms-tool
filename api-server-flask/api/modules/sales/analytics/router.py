# -*- encoding: utf-8 -*-
"""
Analytics endpoints (/api/analytics/*) — web-authenticated dashboards & reports.

Sales-executive analytics are computed from the Busy sales data (busy_sales_data),
attributed to an executive through the dealer -> sales_executive assignment
(dealer.sales_executive_id, loaded from the dealer↔executive mapping file).
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger
from api.modules.sales.analytics import service

logger = get_logger(__name__)

# Attribution goes through the company's dealers. The Busy feed is loaded per company, so
# every query here is scoped to one company; _company() resolves the caller's own rather
# than trusting a request parameter.
from api.permissions import resolve_company_scope, CompanyAccessDenied   # noqa: E402
from api.modules.sales.analytics.service import DEFAULT_COMPANY          # noqa: E402


def _company(current_user):
    """The single company this caller's analytics are computed for.

    Analytics is inherently one dealer-network at a time (targets, part-group mappings and
    the Busy feed are all per company), so this collapses the caller's scope to one id.
    An unrestricted (all-companies) caller falls back to DEFAULT_COMPANY.
    """
    scope = resolve_company_scope(current_user)
    if not scope:                 # None => unrestricted; [] => no grants
        return DEFAULT_COMPANY
    return scope[0]

# "This month" = the current calendar month. All Busy rows carry a real date, so the
# same filter drives every query; the label is returned so the UI can show the period.
_MONTH = "YEAR(b.sale_date) = YEAR(CURDATE()) AND MONTH(b.sale_date) = MONTH(CURDATE())"

# The part-group mapping / targets for the current period (first day of the month) — a
# real DATE so periods never collide across years. (%% survives execute_query's `% params`.)
_PERIOD = "DATE_FORMAT(CURDATE(), '%%Y-%%m-01')"


def _month_label():
    # %% because execute_query runs `query % params`, so a literal % must be doubled.
    rows = mysql_manager.execute_query("SELECT DATE_FORMAT(CURDATE(), '%%M %%Y') AS m")
    return rows[0]['m'] if rows else ''


def _num(v):
    """MySQL SUM returns Decimal; hand the UI plain floats/ints."""
    if v is None:
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _pct(sales, target):
    """% of target achieved, or None when there is no target to measure against."""
    if not target:
        return None
    return round(float(sales) / float(target) * 100, 1)


@rest_api.route('/api/analytics/sales-executives')
class SalesExecSummary(Resource):
    """This-month sales per sales executive (total value + quantity + active dealers)."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            rows = mysql_manager.execute_query(
                f"""SELECT u.id AS user_id, u.username,
                           COUNT(DISTINCT d.dealer_id) AS assigned_dealers,
                           COUNT(DISTINCT CASE WHEN b.id IS NOT NULL THEN d.dealer_id END)
                               AS active_dealers,
                           COALESCE(SUM(b.amount), 0)   AS total_sales,
                           COALESCE(SUM(b.quantity), 0) AS total_qty
                    FROM users u
                    JOIN dealer d
                      ON d.sales_executive_id = u.id AND d.company_id = %s
                    LEFT JOIN busy_sales_data b
                      ON b.particulars = d.name AND {_MONTH}
                    WHERE u.role = 'sales_executive'
                    GROUP BY u.id, u.username
                    ORDER BY total_sales DESC""",
                (_company(current_user),),
            ) or []
            execs = [{
                'user_id':          r['user_id'],
                'username':         r['username'],
                'assigned_dealers': r['assigned_dealers'],
                'active_dealers':   r['active_dealers'],
                'total_sales':      _num(r['total_sales']),
                'total_qty':        _num(r['total_qty']),
            } for r in rows]
            return {'success': True, 'month': _month_label(), 'executives': execs}, 200
        except Exception as e:
            logger.exception("Error in /api/analytics/sales-executives")
            return {'success': False, 'msg': f'Error computing analytics: {str(e)}'}, 400


@rest_api.route('/api/analytics/sales-executives/<int:user_id>')
class SalesExecDetail(Resource):
    """One executive's this-month breakdown: sales by dealer, and quantity by part."""

    @token_required
    @active_required
    def get(self, current_user, user_id):
        try:
            who = mysql_manager.execute_query(
                "SELECT id, username FROM users WHERE id = %s AND role = 'sales_executive'",
                (user_id,),
            )
            if not who:
                return {'success': False, 'msg': 'sales executive not found'}, 404

            # Sales by dealer — every assigned dealer (0 for those with no sales this month).
            by_dealer = mysql_manager.execute_query(
                f"""SELECT d.dealer_id, d.name AS dealer,
                           COALESCE(SUM(b.amount), 0)   AS sales,
                           COALESCE(SUM(b.quantity), 0) AS qty
                    FROM dealer d
                    LEFT JOIN busy_sales_data b
                      ON b.particulars = d.name AND {_MONTH}
                    WHERE d.sales_executive_id = %s AND d.company_id = %s
                    GROUP BY d.dealer_id, d.name
                    ORDER BY sales DESC""",
                (user_id, _company(current_user)),
            ) or []

            # Quantity by part group — parts not in the July mapping bucket as "(Unmapped)".
            by_part_group = mysql_manager.execute_query(
                f"""SELECT COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                           SUM(b.quantity)          AS qty,
                           SUM(b.amount)            AS sales,
                           COUNT(DISTINCT b.item_code) AS parts
                    FROM busy_sales_data b
                    JOIN dealer d ON d.name = b.particulars AND d.company_id = %s
                    LEFT JOIN part_groups pg
                      ON pg.part_number = b.item_code AND pg.period = DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
                    WHERE d.sales_executive_id = %s AND {_MONTH}
                    GROUP BY COALESCE(pg.part_group, '(Unmapped)')
                    ORDER BY qty DESC""",
                (_company(current_user), user_id),
            ) or []

            # Quantity by part — enriched with the July part-group mapping where available.
            by_part = mysql_manager.execute_query(
                f"""SELECT b.item_code,
                           MAX(pg.description) AS description,
                           MAX(pg.part_group)  AS part_group,
                           SUM(b.quantity)     AS qty,
                           SUM(b.amount)       AS sales
                    FROM busy_sales_data b
                    JOIN dealer d ON d.name = b.particulars AND d.company_id = %s
                    LEFT JOIN part_groups pg
                      ON pg.part_number = b.item_code AND pg.period = DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
                    WHERE d.sales_executive_id = %s AND {_MONTH}
                    GROUP BY b.item_code
                    ORDER BY qty DESC""",
                (_company(current_user), user_id),
            ) or []

            total_sales = sum(float(r['sales']) for r in by_dealer)
            total_qty = sum(float(r['qty']) for r in by_dealer)

            return {
                'success': True,
                'month': _month_label(),
                'user_id': who[0]['id'],
                'username': who[0]['username'],
                'total_sales': _num(total_sales),
                'total_qty': _num(total_qty),
                'by_dealer': [{
                    'dealer_id': r['dealer_id'], 'dealer': r['dealer'],
                    'sales': _num(r['sales']), 'qty': _num(r['qty']),
                } for r in by_dealer],
                'by_part_group': [{
                    'part_group': r['part_group'],
                    'qty': _num(r['qty']), 'sales': _num(r['sales']),
                    'parts': r['parts'],
                } for r in by_part_group],
                'by_part': [{
                    'item_code': r['item_code'],
                    'description': r['description'],
                    'part_group': r['part_group'],
                    'qty': _num(r['qty']), 'sales': _num(r['sales']),
                } for r in by_part],
            }, 200
        except Exception as e:
            logger.exception("Error in /api/analytics/sales-executives/<id>")
            return {'success': False, 'msg': f'Error computing analytics: {str(e)}'}, 400


# Shared FROM for the filtered explorer, scoped to one company (an int, safe to inline).
def _base(company_id):
    return (f"FROM busy_sales_data b "
            f"JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)} "
            f"LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = DATE_FORMAT(CURDATE(), '%%Y-%%m-01') ")


def _filtered_where(args):
    """Build the WHERE (this-month + any of the 4 optional filters) and its params."""
    where, params = [_MONTH], []
    ex = args.get('executive_id', type=int)
    de = args.get('dealer_id', type=int)
    pg = (args.get('part_group') or '').strip()
    pt = (args.get('part') or '').strip()
    if ex:
        where.append("d.sales_executive_id = %s"); params.append(ex)
    if de:
        where.append("d.dealer_id = %s"); params.append(de)
    if pt:
        where.append("b.item_code = %s"); params.append(pt)
    if pg:
        where.append("COALESCE(pg.part_group, '(Unmapped)') = %s"); params.append(pg)
    return " AND ".join(where), tuple(params)


@rest_api.route('/api/analytics/filters')
class AnalyticsFilters(Resource):
    """Options for the sales-analytics filter bar (executive / dealer / part group / part)."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            execs = mysql_manager.execute_query(
                f"""SELECT DISTINCT u.id AS user_id, u.username
                    FROM users u
                    JOIN dealer d ON d.sales_executive_id = u.id AND d.company_id = {int(_company(current_user))}
                    WHERE u.role = 'sales_executive'
                    ORDER BY u.username""") or []
            dealers = mysql_manager.execute_query(
                f"""SELECT dealer_id, name AS dealer, sales_executive_id
                    FROM dealer
                    WHERE company_id = {int(_company(current_user))} AND sales_executive_id IS NOT NULL
                    ORDER BY name""") or []
            groups = mysql_manager.execute_query(
                """SELECT DISTINCT part_group FROM part_groups
                   WHERE period = DATE_FORMAT(CURDATE(), '%%Y-%%m-01') AND part_group IS NOT NULL AND part_group <> ''
                   ORDER BY part_group""") or []
            parts = mysql_manager.execute_query(
                """SELECT b.item_code, MAX(pg.description) AS description
                   FROM busy_sales_data b
                   LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
                   GROUP BY b.item_code ORDER BY b.item_code""") or []
            return {
                'success': True,
                'executives': [{'user_id': r['user_id'], 'username': r['username']} for r in execs],
                'dealers': [{'dealer_id': r['dealer_id'], 'dealer': r['dealer'],
                             'executive_id': r['sales_executive_id']} for r in dealers],
                'part_groups': [r['part_group'] for r in groups] + ['(Unmapped)'],
                'parts': [{'item_code': r['item_code'], 'description': r['description']} for r in parts],
            }, 200
        except Exception as e:
            logger.exception("Error in /api/analytics/filters")
            return {'success': False, 'msg': f'Error loading filters: {str(e)}'}, 400


@rest_api.route('/api/analytics/sales')
class SalesExplorer(Resource):
    """Filtered sales analytics: a summary plus breakdowns by executive, dealer,
    part group and part. Delegates to analytics.service (shared with the mobile API)."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            a = request.args
            return service.sales_explorer(
                executive_id=a.get('executive_id', type=int),
                dealer_id=a.get('dealer_id', type=int),
                part_group=(a.get('part_group') or '').strip() or None,
                part=(a.get('part') or '').strip() or None,
                period=(a.get('period') or '').strip() or 'this_month',
                company_id=_company(current_user),
            ), 200
        except Exception as e:
            logger.exception("Error in /api/analytics/sales")
            return {'success': False, 'msg': f'Error computing analytics: {str(e)}'}, 400


@rest_api.route('/api/analytics/dealer-suggestions')
class DealerSuggestions(Resource):
    """Part suggestions for a sales exec visiting a dealer. Delegates to
    analytics.service (shared with the mobile API)."""

    @token_required
    @active_required
    def get(self, current_user):
        try:
            dealer_id = request.args.get('dealer_id', type=int)
            if not dealer_id:
                return {'success': False, 'msg': 'dealer_id is required'}, 422
            result = service.dealer_suggestions(dealer_id, company_id=_company(current_user))
            if result is None:
                return {'success': False, 'msg': 'dealer not found'}, 404
            return result, 200
        except Exception as e:
            logger.exception("Error in /api/analytics/dealer-suggestions")
            return {'success': False, 'msg': f'Error computing suggestions: {str(e)}'}, 400


@rest_api.route('/api/analytics/dealer-suggestions/<int:dealer_id>')
class DealerSuggestionsByDealer(Resource):
    """Part suggestions for a dealer (path-param variant). Thin wrapper over the
    shared analytics.service.dealer_suggestions — identical data to the mobile
    API (/api/v1/analytics/*); the grouping into cards happens in the UI layer."""

    @token_required
    @active_required
    def get(self, current_user, dealer_id):
        try:
            data = service.dealer_suggestions(dealer_id, company_id=_company(current_user))
            if data is None:
                return {'success': False, 'msg': 'dealer not found'}, 404
            return data, 200
        except Exception as e:
            logger.exception("Error in /api/analytics/dealer-suggestions/<id>")
            return {'success': False, 'msg': f'Error computing suggestions: {str(e)}'}, 400
