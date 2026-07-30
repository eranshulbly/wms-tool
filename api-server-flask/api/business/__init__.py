# -*- encoding: utf-8 -*-
"""
Compatibility shim. Domain logic now lives in its owning module:
  order  -> api.modules.fulfillment.order.business / .state_machine
  invoice-> api.modules.fulfillment.invoice.business
  catalog-> api.modules.platform.catalog.{dealer,product,product_upload}_business
Re-exported here so `from ..business import order_business` keeps working.
"""
from api.modules.fulfillment.order import business as order_business                 # noqa: F401
from api.modules.fulfillment.order import state_machine as order_state_machine       # noqa: F401
from api.modules.fulfillment.invoice import business as invoice_business             # noqa: F401
from api.modules.platform.catalog import dealer_business                          # noqa: F401
from api.modules.platform.catalog import product_business                        # noqa: F401
from api.modules.platform.catalog import product_upload_business                 # noqa: F401

__all__ = [
    'order_business', 'order_state_machine', 'invoice_business',
    'dealer_business', 'product_business', 'product_upload_business',
]
