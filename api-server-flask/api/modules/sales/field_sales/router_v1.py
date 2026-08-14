# -*- encoding: utf-8 -*-
"""
Mobile API — sales analytics (/api/v1/analytics/*), JWT-authenticated.

Thin wrappers over field_sales.service, scoped to the signed-in salesperson:

  GET /api/v1/analytics/my-summary          this exec's month sales / target / %
  GET /api/v1/analytics/dealer/<dealer_id>  that dealer's month sales / target / %
                                            split by parts category (Parts / Pro Parts)
                                            with per-category suggestions, plus a
                                            non-parts category sales breakdown

Both are answered from the caller's OWN company, and what that company can
actually report depends on its analytics_mode:

  'targets'  — a Busy sales feed and dealer_target rows, so the full payload above.
  'invoices' — no feed and no targets, so the month's invoiced total alone. The
               payload keeps its shape with the category blocks empty and
               `has_targets` False; the app reads that and drops the target and
               category surfaces instead of drawing empty ones.
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_auth_required
from api.modules.sales.field_sales import service


def _caller_company(current_user):
    """The company whose figures this caller sees.

    A field-sales user is granted exactly one company — the one their dealers,
    targets and invoices all live in — so that grant is the answer. A caller with
    several grants (or company:all) has no single answer, and picking one of them
    silently would report another company's numbers as theirs; those keep the
    historic default instead.
    """
    ids = current_user.get('company_ids') or []
    if current_user.get('has_all_companies') or len(ids) != 1:
        return service.DEFAULT_COMPANY
    return int(ids[0])


@rest_api.route('/api/v1/analytics/my-summary')
class V1MySalesSummary(Resource):
    @v1_auth_required
    def get(self, current_user):
        """This month's achievement for the signed-in sales executive — measured
        against target where the company sets targets, else the invoiced total."""
        company_id = _caller_company(current_user)
        if service.company_analytics_mode(company_id) == 'invoices':
            return service.exec_invoice_summary(
                current_user['user_id'], company_id), 200
        return service.exec_summary(
            current_user['user_id'], company_id=company_id), 200


@rest_api.route('/api/v1/analytics/dealer/<int:dealer_id>')
class V1DealerAnalytics(Resource):
    @v1_auth_required
    def get(self, current_user, dealer_id):
        """A dealer's month achievement split by parts category, with per-category
        suggestions and a non-parts category sales breakdown, for the dealer the
        exec has checked into.

        `categories[]` — Parts / Pro Parts, each with sales, % of the dealer's
        (whole) money target, and grow / new_opportunity suggestions from that
        category. `other_stats[]` — every other category's month + last-6-months
        sales, no targets. `data_through` says how current the figures are.

        On an invoices-mode company `categories[]` is empty and `sales` carries the
        dealer's invoiced total for the month.
        """
        company_id = _caller_company(current_user)
        if service.company_analytics_mode(company_id) == 'invoices':
            data = service.dealer_invoice_summary(dealer_id, company_id)
        else:
            data = service.dealer_category_analytics(dealer_id, company_id=company_id)
        if data is None:
            return {"detail": f"dealer {dealer_id} not found"}, 404
        return data, 200
