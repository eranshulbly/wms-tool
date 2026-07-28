# -*- encoding: utf-8 -*-
"""
Compatibility aggregator.

Model classes now live in their owning module: api/modules/<module>/models.py.
They are re-exported here so existing `from ..models import X` / `from .models
import X` call sites keep working during the restructure. New code should import
from the owning module (preferably via that module's service.py).
"""

# Infra names some legacy call sites import from here (e.g. `from ..models import
# mysql_manager`) — kept re-exported for backward compatibility.
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter

from api.modules.user_auth.models import (
    Users, JWTTokenBlocklist, UserWarehouseCompany,
)
from api.modules.inventory.models import Warehouse
from api.modules.catalog.models import Company, Dealer, Product
from api.modules.supply_sheet.models import SupplySheetCounter
from api.modules.order.models import (
    OrderState, PotentialOrder, PotentialOrderProduct, Order,
    OrderStateHistory, OrderProduct,
)
from api.modules.invoice.models import Invoice, InvoiceProcessingConfig
from api.modules.eway_bill.models import (
    TransportRoute, CustomerRouteMapping, DailyRouteManifest, CompanySchemaMapping,
)

__all__ = [
    "mysql_manager", "MySQLModel", "partition_filter",
    "Users", "JWTTokenBlocklist", "UserWarehouseCompany",
    "Warehouse", "Company", "Dealer", "Product", "SupplySheetCounter",
    "OrderState", "PotentialOrder", "PotentialOrderProduct", "Order",
    "OrderStateHistory", "OrderProduct",
    "Invoice", "InvoiceProcessingConfig",
    "TransportRoute", "CustomerRouteMapping", "DailyRouteManifest", "CompanySchemaMapping",
]
