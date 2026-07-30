# -*- encoding: utf-8 -*-
"""Events published by the order module (see api/shared/events.py)."""

from dataclasses import dataclass

from api.shared.events import Event


@dataclass
class OrderSubmitted(Event):
    order_id: int
    dealer_id: int
