# -*- encoding: utf-8 -*-
"""
Mobile API — sales analytics (/api/v1/analytics/*), JWT-authenticated.

Thin wrappers over field_sales.service, scoped to the signed-in salesperson:

  GET /api/v1/analytics/my-summary          this exec's month sales / target / %
  GET /api/v1/analytics/dealer/<dealer_id>  that dealer's month sales / target / %
                                            split by parts category (Parts / Pro Parts)
                                            with per-category suggestions, plus a
                                            non-parts category sales breakdown
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_auth_required
from api.modules.sales.field_sales import service


@rest_api.route('/api/v1/analytics/my-summary')
class V1MySalesSummary(Resource):
    @v1_auth_required
    def get(self, current_user):
        """This month's target achievement for the signed-in sales executive."""
        return service.exec_summary(current_user['user_id']), 200


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
        sales, no targets. `data_through` says how current the Busy figures are.
        """
        data = service.dealer_category_analytics(dealer_id)
        if data is None:
            return {"detail": f"dealer {dealer_id} not found"}, 404
        return data, 200
