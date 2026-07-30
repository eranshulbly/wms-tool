# -*- encoding: utf-8 -*-
"""
Events the assignment module reacts to.

These are OWNED by their publishers (inventory / order) — re-exported here only
as a convenience for this module's handlers. A subscriber must never define the
publisher's event types.
"""

from api.modules.inventory.events import PicklistGenerated, PickingCompleted  # noqa: F401
from api.modules.fulfillment.order.events import OrderSubmitted  # noqa: F401

__all__ = [
    'PicklistGenerated', 'PickingCompleted', 'OrderSubmitted',
]
