# -*- encoding: utf-8 -*-
"""
In-process event bus.

Ported from wms-v2-backend (app/shared/events.py). Lets a module *react* to
something that happened in another module without the publisher importing the
subscriber — the fourth boundary rule of the modular monolith.

Today this is a synchronous in-process dispatcher. It is deliberately shaped
like a message broker (publish/subscribe by event type) so it can later be
swapped for SNS/SQS/Kafka without touching publishers or subscribers.

Usage:
    # define an event (any module)
    @dataclass
    class OrderInvoiced(Event):
        potential_order_id: int
        warehouse_id: int

    # subscribe (in a module's handlers.py, wired at startup)
    event_bus.subscribe(OrderInvoiced, on_order_invoiced)

    # publish (in the owning module's service.py)
    event_bus.publish(OrderInvoiced(potential_order_id=1, warehouse_id=2))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Type

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base class for all domain events. Subclass with @dataclass."""
    pass


class EventBus:
    """Synchronous in-process pub/sub keyed by event type."""

    def __init__(self) -> None:
        self._subscribers: Dict[Type[Event], List[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: Type[Event], handler: Callable[[Event], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        """Dispatch to every subscriber. One failing handler never breaks the others."""
        for handler in self._subscribers[type(event)]:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — a bad subscriber must not break the publisher
                logger.exception("Event handler %r failed for %s", handler, type(event).__name__)


# Process-wide singleton — import this everywhere.
event_bus = EventBus()
