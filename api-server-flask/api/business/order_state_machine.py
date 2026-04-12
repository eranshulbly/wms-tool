# -*- encoding: utf-8 -*-
"""
OrderStateMachine — single authoritative source for all order state transition rules.

Previously the transition rules were split across three files:
  • order_business.py   — _VALID_TRANSITIONS, _SOURCE_FOR_TARGET, _FRONTEND_TO_DB_STATUS
  • invoice_business.py — _TERMINAL_STATES, _PRE_PACKED_STATES
  • routes.py           — inline valid_transitions dict (different from order_business.py!)

All of that now lives here.  No database access — pure class-level constants and class
methods.  Import OrderStatus from constants.order_states instead of using string literals.
"""

from ..constants.order_states import OrderStatus


class OrderStateMachine:
    """
    Defines and enforces the WMS order state machine.

    State diagram:
        Open ──► Picking ──► Packed ──► Invoiced ──► Dispatch Ready ──► Completed
                    ▲                                                        │
                    │                                                Partially Completed
                  (back-transition allowed for single-order endpoint)

    Notes
    ─────
    • BULK_TRANSITIONS  : forward-only chain used by the Excel bulk-upload endpoint.
      Only these transitions are valid when updating orders from a CSV file.

    • SINGLE_ORDER_TRANSITIONS : valid targets for the per-order status update endpoint.
      Includes the Picking → Open back-transition that was in the original route-layer dict.

    • TERMINAL_STATES   : orders in these states cannot accept a new invoice upload.

    • PRE_PACKED_STATES : orders in these states CAN accept an invoice_submitted flag
      (the invoice upload happened before the order was packed).
    """

    # ── Forward-only bulk transitions ────────────────────────────────────────
    # key = expected current status  →  value = allowed target
    BULK_TRANSITIONS: dict = {
        OrderStatus.OPEN:           OrderStatus.PICKING,
        OrderStatus.PICKING:        OrderStatus.PACKED,
        OrderStatus.DISPATCH_READY: OrderStatus.COMPLETED,
    }

    # Reverse lookup: target → required source (used by bulk-status-update business logic)
    _SOURCE_FOR_TARGET: dict = {v: k for k, v in BULK_TRANSITIONS.items()}

    # ── Per-order transitions (used by individual order status update endpoint) ─
    # This DIFFERS from BULK_TRANSITIONS — it allows the Picking → Open back-transition.
    SINGLE_ORDER_TRANSITIONS: dict = {
        OrderStatus.OPEN:                [OrderStatus.PICKING],
        OrderStatus.PICKING:             [OrderStatus.PACKED, OrderStatus.OPEN],
        OrderStatus.PACKED:              [OrderStatus.PICKING],
        OrderStatus.INVOICED:            [],
        OrderStatus.DISPATCH_READY:      [],
        OrderStatus.COMPLETED:           [],
        OrderStatus.PARTIALLY_COMPLETED: [],
    }

    # ── Terminal / pre-packed sets (used by invoice upload business logic) ────
    TERMINAL_STATES: frozenset = frozenset({
        OrderStatus.INVOICED,
        OrderStatus.DISPATCH_READY,
        OrderStatus.COMPLETED,
        OrderStatus.PARTIALLY_COMPLETED,
    })

    PRE_PACKED_STATES: frozenset = frozenset({
        OrderStatus.OPEN,
        OrderStatus.PICKING,
    })

    # ── Query helpers ─────────────────────────────────────────────────────────

    @classmethod
    def required_source_for_bulk(cls, target: OrderStatus) -> 'OrderStatus | None':
        """Return the required current status for a bulk transition to `target`."""
        return cls._SOURCE_FOR_TARGET.get(target)

    @classmethod
    def can_bulk_transition(cls, current: OrderStatus, target: OrderStatus) -> bool:
        """True when a bulk-upload can move an order from `current` to `target`."""
        return cls.BULK_TRANSITIONS.get(current) == target

    @classmethod
    def can_single_transition(cls, current: OrderStatus, target: OrderStatus) -> bool:
        """True when a single-order endpoint can move an order from `current` to `target`."""
        return target in cls.SINGLE_ORDER_TRANSITIONS.get(current, [])

    @classmethod
    def is_terminal(cls, status: OrderStatus) -> bool:
        """True when no further invoice upload is allowed."""
        return status in cls.TERMINAL_STATES

    @classmethod
    def is_pre_packed(cls, status: OrderStatus) -> bool:
        """True when the order has not yet reached Packed state."""
        return status in cls.PRE_PACKED_STATES
