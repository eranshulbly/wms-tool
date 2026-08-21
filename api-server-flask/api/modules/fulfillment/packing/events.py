# -*- encoding: utf-8 -*-
"""
Domain events packing publishes.

Nothing subscribes today, and that is the point: dispatch re-weigh, fraud
reporting and the invoice fix (design §6.10.3 Gap 4) all want to react to a sealed
carton, and each belongs to a different module. Publishing on the shared bus means
packing never learns their names — the fourth boundary rule of the modular
monolith. Handlers are wired at startup by the subscribing module, exactly as
`fulfillment/assignment/handlers.py` does.

Publishing is fire-and-forget: `EventBus.publish` swallows and logs a failing
handler, so a subscriber can never fail a packer's seal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from api.shared.events import Event, event_bus


@dataclass
class CartonSealed(Event):
    """A box was weight-verified and closed. The carton physically exists now.

    Carries the variance rather than just a pass/fail because a subscriber
    interested in fraud wants the magnitude, and re-reading the row to get it would
    make every subscriber pay for a query the publisher already had the answer to.
    """

    request_id: int
    potential_order_id: int
    box_id: int
    box_no: int
    label_code: str
    kind: str                      # constants.BoxKind — built | intact
    units: float
    sealed_kg: float
    expected_kg: float
    variance_g: int
    within_tolerance: bool
    tolerance_g: int
    company_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    packed_by: Optional[int] = None


@dataclass
class PackingSessionCompleted(Event):
    """A packing job was submitted — the order is now `Packed`.

    `short` is non-zero when the order closed with a declared shortfall; a
    subscriber that must not act on an incomplete shipment can branch on it
    without re-deriving the arithmetic.
    """

    request_id: int
    potential_order_id: int
    request_status: str            # completed | submitted_short
    box_count: int
    packed_units: float
    required_units: float
    short_units: float
    company_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    packed_by: Optional[int] = None
    short_sku_codes: List[str] = field(default_factory=list)


def publish_carton_sealed(**kwargs) -> None:
    """Announce `carton.sealed`."""
    event_bus.publish(CartonSealed(**kwargs))


def publish_session_completed(**kwargs) -> None:
    """Announce `packing.session_completed`."""
    event_bus.publish(PackingSessionCompleted(**kwargs))
