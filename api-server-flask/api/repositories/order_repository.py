# -*- encoding: utf-8 -*-
"""
OrderRepository — all SQL for PotentialOrder, Order, OrderState, OrderStateHistory,
and the Dealer name lookup used during bulk status updates.
"""

from ..core.logging import get_logger
from .base_repository import BaseRepository

logger = get_logger(__name__)


class OrderRepository(BaseRepository):
    """Data access layer for order-domain entities."""

    # ── PotentialOrder ────────────────────────────────────────────────────────

    def find_bulk_by_original_ids(self, order_ids: list) -> dict:
        """
        Fetch multiple PotentialOrders in one IN query (active partition window).

        Returns:
            dict mapping original_order_id → PotentialOrder instance
        """
        if not order_ids:
            return {}
        from ..models import PotentialOrder
        pf_sql, pf_params = self._pf('potential_order')
        placeholders = ','.join(['%s'] * len(order_ids))
        rows = self._db.execute_query(
            f"SELECT * FROM potential_order "
            f"WHERE {pf_sql} AND original_order_id IN ({placeholders})",
            pf_params + tuple(order_ids)
        )
        return {r['original_order_id']: PotentialOrder(**r) for r in rows} if rows else {}

    def find_by_id(self, potential_order_id: int):
        """Return a single PotentialOrder by primary key, or None."""
        from ..models import PotentialOrder
        pf_sql, pf_params = self._pf('potential_order')
        rows = self._db.execute_query(
            f"SELECT * FROM potential_order WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        return PotentialOrder(**rows[0]) if rows else None

    # ── Order ────────────────────────────────────────────────────────────────

    def find_order_by_potential_id(self, potential_order_id: int):
        """Return the Order record linked to a PotentialOrder, or None."""
        from ..models import Order
        pf_sql, pf_params = self._pf('order')
        rows = self._db.execute_query(
            f"SELECT * FROM `order` WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        return Order(**rows[0]) if rows else None

    # ── OrderState ───────────────────────────────────────────────────────────

    def find_state_by_name(self, state_name: str):
        """Return an OrderState by its state_name, or None."""
        from ..models import OrderState
        rows = self._db.execute_query(
            "SELECT * FROM order_state WHERE state_name = %s", (state_name,)
        )
        return OrderState(**rows[0]) if rows else None

    def get_or_create_state(self, name: str, description: str):
        """
        Return the OrderState for *name*, creating it if it doesn't yet exist.

        Safe to call repeatedly — uses find-then-create without a unique
        constraint race because order_state rows are created at app startup
        in practice.
        """
        from ..models import OrderState
        state = self.find_state_by_name(name)
        if not state:
            state = OrderState(state_name=name, description=description)
            state.save()
            logger.debug("Created OrderState", extra={'state_name': name})
        return state

    # ── OrderStateHistory ────────────────────────────────────────────────────

    def create_state_history(self, potential_order_id: int, state_id: int,
                             user_id: int, changed_at) -> None:
        """Insert one row into order_state_history."""
        from ..models import OrderStateHistory
        OrderStateHistory(
            potential_order_id=potential_order_id,
            state_id=state_id,
            changed_by=user_id,
            changed_at=changed_at,
        ).save()

    # ── Dealer (name lookup only) ────────────────────────────────────────────

    def get_dealer_name(self, dealer_id: int) -> str:
        """Return the dealer's name for a given dealer_id, or empty string."""
        from ..models import Dealer
        dealer = Dealer.get_by_id(dealer_id)
        return dealer.name if dealer else ''
