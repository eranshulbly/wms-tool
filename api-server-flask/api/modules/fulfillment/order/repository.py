# -*- encoding: utf-8 -*-
"""
OrderRepository — all SQL for PotentialOrder, Order, OrderState, OrderStateHistory,
and the Dealer name lookup used during bulk status updates.
"""

from api.core.logging import get_logger
from api.shared.base_repository import BaseRepository

logger = get_logger(__name__)


class OrderRepository(BaseRepository):
    """Data access layer for order-domain entities."""

    # ── PotentialOrder ────────────────────────────────────────────────────────

    def existing_orders_with_status(self, company_id, order_ids: list) -> dict:
        """Existing orders for these numbers, keyed by number, with id/status/purchaser.

        Scoped to the company because the number comes from the customer's own series —
        two tenants can legitimately use the same one, and treating that as a duplicate
        would reject a valid order.

        Deliberately NOT partition-filtered: an order uploaded outside the active window
        is still an order, and missing it would let a duplicate through — which is the
        whole point of this check.

        Used where a duplicate needs more than a yes/no answer: whether it can be
        replaced depends on its current status (see OrderStateMachine.TERMINAL_STATES).
        """
        ids = [str(o).strip() for o in (order_ids or []) if str(o).strip()]
        if not ids:
            return {}
        unique = list(dict.fromkeys(ids))
        placeholders = ','.join(['%s'] * len(unique))
        rows = self._db.execute_query(
            f"""SELECT original_order_id, potential_order_id, status, purchaser_name
                  FROM potential_order
                 WHERE company_id = %s AND original_order_id IN ({placeholders})""",
            (company_id, *unique))
        return {r['original_order_id']: r for r in (rows or [])}

    def delete_order(self, potential_order_id: int) -> None:
        """Hard-delete one order's own data — state history, line items, the order row.

        Only ever called on an order still short of Invoiced (the caller checks
        OrderStateMachine.is_terminal first — see business.py's duplicate-replace flow):
        no stock has moved for it yet at that point, so unlike admin's whole-batch revert
        (_delete_order_batch in router_admin.py), which also has to give stock back, there
        is nothing here to reverse.
        """
        pf_osh_sql, pf_osh_params = self._pf('order_state_history', alias='osh')
        pf_pop_sql, pf_pop_params = self._pf('potential_order_product', alias='pop')
        pf_po_sql, pf_po_params = self._pf('potential_order')
        with self._db.get_cursor() as cursor:
            cursor.execute(
                f"DELETE osh FROM order_state_history osh"
                f" WHERE osh.potential_order_id = %s AND {pf_osh_sql}",
                (potential_order_id, *pf_osh_params))
            cursor.execute(
                f"DELETE pop FROM potential_order_product pop"
                f" WHERE pop.potential_order_id = %s AND {pf_pop_sql}",
                (potential_order_id, *pf_pop_params))
            cursor.execute(
                f"DELETE FROM potential_order WHERE potential_order_id = %s AND {pf_po_sql}",
                (potential_order_id, *pf_po_params))

    def find_bulk_by_original_ids(self, order_ids: list) -> dict:
        """
        Fetch multiple PotentialOrders in one IN query (active partition window).

        Returns:
            dict mapping original_order_id → PotentialOrder instance
        """
        if not order_ids:
            return {}
        from api.models import PotentialOrder
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
        from api.models import PotentialOrder
        pf_sql, pf_params = self._pf('potential_order')
        rows = self._db.execute_query(
            f"SELECT * FROM potential_order WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        return PotentialOrder(**rows[0]) if rows else None

    # ── Order ────────────────────────────────────────────────────────────────

    def find_order_by_potential_id(self, potential_order_id: int):
        """Return the Order record linked to a PotentialOrder, or None."""
        from api.models import Order
        pf_sql, pf_params = self._pf('order')
        rows = self._db.execute_query(
            f"SELECT * FROM `order` WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        return Order(**rows[0]) if rows else None

    # ── OrderState ───────────────────────────────────────────────────────────

    def find_state_by_name(self, state_name: str):
        """Return an OrderState by its state_name, or None."""
        from api.models import OrderState
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
        from api.models import OrderState
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
        from api.models import OrderStateHistory
        OrderStateHistory(
            potential_order_id=potential_order_id,
            state_id=state_id,
            changed_by=user_id,
            changed_at=changed_at,
        ).save()

    # ── Dealer (name lookup only) ────────────────────────────────────────────

    def get_dealer_name(self, dealer_id: int) -> str:
        """Return the dealer's name for a given dealer_id, or empty string."""
        from api.models import Dealer
        dealer = Dealer.get_by_id(dealer_id)
        return dealer.name if dealer else ''
