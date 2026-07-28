# -*- encoding: utf-8 -*-
"""
Compatibility shim. Domain logic now lives in its owning module:
  order  -> api.modules.order.business / .state_machine
  invoice-> api.modules.invoice.business
  catalog-> api.modules.catalog.{dealer,product,product_upload}_business
Re-exported here so `from ..business import order_business` keeps working.
"""
from api.modules.order import business as order_business                 # noqa: F401
from api.modules.order import state_machine as order_state_machine       # noqa: F401
from api.modules.invoice import business as invoice_business             # noqa: F401
from api.modules.catalog import dealer_business                          # noqa: F401
from api.modules.catalog import product_business                        # noqa: F401
from api.modules.catalog import product_upload_business                 # noqa: F401

__all__ = [
    'order_business', 'order_state_machine', 'invoice_business',
    'dealer_business', 'product_business', 'product_upload_business',
]
