# -*- encoding: utf-8 -*-
"""
inventory module — HTTP routes.

Only a module-status endpoint for now (the stock/picklist features are
scaffolded). Warehouse reads are still served by the order dashboard routes
(`/api/warehouses`); they will migrate to call inventory.service over time.
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.modules.inventory import service as inventory_service


@rest_api.route('/api/inventory')
class InventoryStatus(Resource):
    """Module status + warehouse count (scaffold)."""

    @token_required
    @active_required
    def get(self, _current_user):
        warehouses = inventory_service.list_warehouses()
        return {
            "module": "inventory",
            "status": "scaffolded",
            "features": {"warehouses": "live", "stock": "live", "ledger": "live",
                         "movement_requests": "live", "grn": "planned",
                         "stacking": "planned", "picking": "planned"},
            "warehouse_count": len(warehouses),
        }, 200
