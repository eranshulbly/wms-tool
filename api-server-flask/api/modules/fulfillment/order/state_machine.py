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

from api.modules.fulfillment.order.constants import OrderStatus


class OrderStateMachine:
    """
    Defines and enforces the WMS order state machine.

    State diagram (one shared lifecycle for web and mobile):

        (app)      submitted ──┐   (enters at Open via the DMS-output upload;
                               ▼    matching is being re-architected)
        (web upload) ────────► Open ──► Picking ──► Packed ──► Invoiced
                                          ▲                       │
                                          │            Dispatch Ready ──► Completed
                                          │                       │
                        (back-transition) │              Partially Completed

    Web-uploaded orders start at Open; app-created orders land at `submitted` and
    later join the same chain at Open. There is no separate approve/reject step.

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

    # ── Transitions a pick-list QR scan may make ─────────────────────────────
    # Deliberately a separate map from BULK_TRANSITIONS, not an edit to it.
    #
    # It differs in two ways. An Open order can go straight to Packed, because a
    # small order is picked and packed in one motion at one bench and forcing two
    # scans would only teach people to double-trigger. And Packed can go to
    # Dispatch Ready, which the Excel bulk path deliberately cannot.
    #
    # THAT SECOND ONE BYPASSES INVOICING. Everywhere else, Dispatch Ready is reached
    # through /move-to-invoiced after an invoice exists; a scan reaching it means an
    # order can be released for dispatch with no invoice uploaded. That is the
    # requested behaviour for the handheld — the dispatch grant is separate
    # (order:move_dispatch) precisely because it is the loose one.
    #
    # Keeping the maps separate means a future change to how spreadsheets move
    # orders cannot silently change what a scanner on the floor does, or vice versa.
    SCAN_TRANSITIONS: dict = {
        OrderStatus.OPEN:           [OrderStatus.PICKING, OrderStatus.PACKED],
        OrderStatus.PICKING:        [OrderStatus.PACKED],
        OrderStatus.PACKED:         [OrderStatus.DISPATCH_READY],
        OrderStatus.DISPATCH_READY: [OrderStatus.COMPLETED],
    }

    @classmethod
    def scan_targets(cls, current) -> list:
        """Every state a scan could move an order in `current` to, before the
        scanning user's own permissions narrow it."""
        return list(cls.SCAN_TRANSITIONS.get(current, []))

    @classmethod
    def can_scan_transition(cls, current, target) -> bool:
        """True when a scan may move an order from `current` to `target`."""
        return target in cls.SCAN_TRANSITIONS.get(current, [])

    # ── Per-order transitions (used by individual order status update endpoint) ─
    # This DIFFERS from BULK_TRANSITIONS — it allows the Picking → Open back-transition.
    SINGLE_ORDER_TRANSITIONS: dict = {
        # An app order lands at `submitted`. It enters the warehouse chain at Open via
        # the DMS-output upload (that matching flow is being re-architected), so there is
        # no per-order forward transition out of `submitted` here yet.
        OrderStatus.SUBMITTED:           [],
        OrderStatus.OPEN:                [OrderStatus.PICKING],
        OrderStatus.PICKING:             [OrderStatus.PACKED, OrderStatus.OPEN],
        OrderStatus.PACKED:              [OrderStatus.PICKING],
        OrderStatus.INVOICED:            [],
        OrderStatus.DISPATCH_READY:      [],
        OrderStatus.COMPLETED:           [],
        OrderStatus.PARTIALLY_COMPLETED: [],
    }

    # States an order can occupy before entering the warehouse chain (app-only).
    PRE_WAREHOUSE_STATES: frozenset = frozenset({
        OrderStatus.SUBMITTED,
    })

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
