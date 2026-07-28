# -*- encoding: utf-8 -*-
"""Events published by the inventory module (see api/shared/events.py).

Owned here because inventory publishes them; assignment subscribes without the
publisher ever importing the subscriber.
"""

from dataclasses import dataclass

from api.shared.events import Event


@dataclass
class PicklistGenerated(Event):
    picklist_id: int
    order_id: int
    warehouse_id: int


@dataclass
class PickingCompleted(Event):
    picklist_id: int
    order_id: int
    warehouse_id: int
