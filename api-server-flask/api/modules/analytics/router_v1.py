# -*- encoding: utf-8 -*-
"""
Mobile API — sales analytics (/api/v1/analytics/*), JWT-authenticated.

Thin wrappers over analytics.service (the same computation the web dashboards use),
scoped to the signed-in salesperson:

  GET /api/v1/analytics/my-summary          this exec's month sales / target / %
  GET /api/v1/analytics/dealer/<dealer_id>  that dealer's month sales / target / %
                                            plus part suggestions (grow / new)
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_auth_required
from api.modules.analytics import service


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
        """A dealer's month target achievement plus part suggestions, for the
        dealer the exec has checked into."""
        suggestions = service.dealer_suggestions(dealer_id)
        if suggestions is None:
            return {"detail": f"dealer {dealer_id} not found"}, 404
        summary = service.dealer_summary(dealer_id)
        return {
            "month": suggestions['month'],
            "dealer_id": dealer_id,
            "dealer": suggestions['dealer'],
            "sales": summary['sales'],
            "target": summary['target'],
            "pct": summary['pct'],
            "grow": suggestions['grow'],
            "new_opportunity": suggestions['new_opportunity'],
        }, 200
