# -*- encoding: utf-8 -*-
"""
Mobile API — sales analytics (/api/v1/analytics/*), JWT-authenticated.

  GET /api/v1/analytics/my-summary          this exec's month invoiced total
  GET /api/v1/analytics/dealer/<dealer_id>  that dealer's month invoiced total

Answered from this deployment's company (one instance ⇄ one company). Sales come
from uploaded invoices; there are no targets to measure against, so each payload
is a plain month total.
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_auth_required
from api.modules.sales.field_sales import service


@rest_api.route('/api/v1/analytics/my-summary')
class V1MySalesSummary(Resource):
    @v1_auth_required
    def get(self, current_user):
        """This month's invoiced total for the signed-in sales executive."""
        return service.exec_invoice_summary(
            current_user['user_id'], service.deployment_company_id()), 200


@rest_api.route('/api/v1/analytics/dealer/<int:dealer_id>')
class V1DealerAnalytics(Resource):
    @v1_auth_required
    def get(self, current_user, dealer_id):
        """This dealer's month invoiced total, for the dealer the exec checked into."""
        data = service.dealer_invoice_summary(
            dealer_id, service.deployment_company_id())
        if data is None:
            return {"detail": f"dealer {dealer_id} not found"}, 404
        return data, 200
