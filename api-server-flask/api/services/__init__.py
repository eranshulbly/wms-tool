# -*- encoding: utf-8 -*-
"""
Compatibility shim. Upload services now live in their owning module
(api/modules/<m>/service.py); shared upload infra lives in api/shared. Exposed
here so `from ..services import order_service` keeps working.
"""
from api.modules.fulfillment.order import service as order_service          # noqa: F401
from api.modules.fulfillment.invoice import service as invoice_service      # noqa: F401
from api.modules.platform.catalog import product_service                 # noqa: F401

__all__ = ['order_service', 'invoice_service', 'product_service']
