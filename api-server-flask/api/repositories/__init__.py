# -*- encoding: utf-8 -*-
"""
Compatibility shim. Repository classes now live in their owning module
(api/modules/<m>/repository.py) and BaseRepository in api/shared. The
module-level singletons are still exposed here so `from ..repositories import
order_repo` keeps working during the restructure.
"""
from api.shared.base_repository import BaseRepository  # noqa: F401
from api.modules.order.repository import OrderRepository
from api.modules.invoice.repository import InvoiceRepository
from api.modules.catalog.product_repository import ProductRepository
from api.modules.catalog.reference_repository import ReferenceRepository
from api.modules.user_auth.repository import UserRepository

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
