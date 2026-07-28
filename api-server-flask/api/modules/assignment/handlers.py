# -*- encoding: utf-8 -*-
"""
assignment module — event subscriptions.

register_handlers() is called once at app startup. Today the handlers only log
(the assignment engine is not built yet), mirroring wms-v2-backend's scaffold.
When implemented, on_picklist_generated would create a 'picking' job, etc.
"""

from api.shared.events import event_bus
from api.shared.logging import get_logger
from api.modules.assignment.events import PicklistGenerated, PickingCompleted

logger = get_logger(__name__)


def on_picklist_generated(event: PicklistGenerated) -> None:
    logger.info("assignment: would create a picking job for picklist %s (order %s, wh %s)",
                event.picklist_id, event.order_id, event.warehouse_id)


def on_picking_completed(event: PickingCompleted) -> None:
    logger.info("assignment: would create a packing job for picklist %s (order %s, wh %s)",
                event.picklist_id, event.order_id, event.warehouse_id)


def register_handlers() -> None:
    """Wire this module's subscriptions to the event bus. Idempotent enough for one startup call."""
    event_bus.subscribe(PicklistGenerated, on_picklist_generated)
    event_bus.subscribe(PickingCompleted, on_picking_completed)
