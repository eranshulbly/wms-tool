# -*- encoding: utf-8 -*-
"""
repositories/ — Data access layer.

Each repository class wraps all SQL for one domain entity.
Business-layer code imports the module-level singletons:

    from ..repositories import order_repo, invoice_repo, product_repo

Route handlers continue to call model classmethods directly (unchanged in
Phase 4; cleaned up in Phase 5-6).
"""

from .order_repository import OrderRepository
from .invoice_repository import InvoiceRepository
from .product_repository import ProductRepository
from .user_repository import UserRepository
from .reference_repository import ReferenceRepository

# Module-level singletons — import these in business-layer modules.
order_repo = OrderRepository()
invoice_repo = InvoiceRepository()
product_repo = ProductRepository()
user_repo = UserRepository()
reference_repo = ReferenceRepository()

__all__ = [
    'OrderRepository', 'InvoiceRepository', 'ProductRepository',
    'UserRepository', 'ReferenceRepository',
    'order_repo', 'invoice_repo', 'product_repo', 'user_repo', 'reference_repo',
]
