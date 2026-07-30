# -*- encoding: utf-8 -*-
"""
Compatibility shim. Repository classes now live in their owning module
(api/modules/<m>/repository.py) and BaseRepository in api/shared. The
module-level singletons are still exposed here so `from ..repositories import
order_repo` keeps working during the restructure.
"""
from api.shared.base_repository import BaseRepository  # noqa: F401
from api.modules.fulfillment.order.repository import OrderRepository
from api.modules.fulfillment.invoice.repository import InvoiceRepository
from api.modules.platform.catalog.product_repository import ProductRepository
from api.modules.platform.catalog.reference_repository import ReferenceRepository
from api.modules.platform.user_auth.repository import UserRepository

order_repo = OrderRepository()
invoice_repo = InvoiceRepository()
product_repo = ProductRepository()
user_repo = UserRepository()
reference_repo = ReferenceRepository()

__all__ = [
    'BaseRepository', 'OrderRepository', 'InvoiceRepository', 'ProductRepository',
    'UserRepository', 'ReferenceRepository',
    'order_repo', 'invoice_repo', 'product_repo', 'user_repo', 'reference_repo',
]
