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

    def find_any_by_original_id(self, original_order_id: str):
        """Find an order by its order number across EVERY partition, not just the
        active window.

        find_bulk_by_original_ids() is window-scoped, so it cannot tell "this order
        does not exist" apart from "this order is older than the window". That
        distinction did not matter while a miss only produced an error message. It
        matters now that a miss creates an order: `potential_order` carries no unique
        index on original_order_id (migration_partitions.sql had to drop it — MySQL
        requires the partition key in every unique index), so creating on a windowed
        miss would silently produce a second row for an order that already exists.

        Unindexed by partition, but original_order_id is indexed, so this is an index
        lookup per partition rather than a scan.

        Returns the most recent match, or None.
        """
        if not original_order_id:
            return None
        from api.models import PotentialOrder
        rows = self._db.execute_query(
            "SELECT * FROM potential_order WHERE original_order_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (original_order_id,)
        )
        return PotentialOrder(**rows[0]) if rows else None

    def insert_potential_order_on(self, cursor, fields: dict) -> int:
        """Insert one potential_order on the CALLER'S cursor and return its id.

        PotentialOrder.save() opens its own cursor and commits, which would land the
        order on disk even if the rest of the import then failed. Importing a pick
        list is one transaction, so it needs the insert on the transaction it already
        holds.
        """
        cursor.execute(
            """INSERT INTO potential_order
                 (original_order_id, b2b_po_number, order_type, vin_number,
                  shipping_address, source_created_by, purchaser_sap_code,
                  purchaser_name, warehouse_id, company_id, dealer_id, order_date,
                  requested_by, status, box_count, upload_batch_id,
                  created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s)""",
            (fields['original_order_id'], fields.get('b2b_po_number'),
             fields.get('order_type'), fields.get('vin_number'),
             fields.get('shipping_address'), fields.get('source_created_by'),
             fields.get('purchaser_sap_code'), fields.get('purchaser_name'),
             fields.get('warehouse_id'), fields.get('company_id'),
             fields.get('dealer_id'), fields.get('order_date'),
             fields.get('requested_by'), fields.get('status', 'Open'),
             fields.get('box_count', 1), fields.get('upload_batch_id'),
             fields['created_at'], fields['created_at']),
        )
        return cursor.lastrowid

    def build_potential_order(self, fields: dict):
        """Wrap a dict of freshly-inserted values as a PotentialOrder.

        Used straight after insert_potential_order_on(): the row is not committed yet,
        so re-reading it would either miss it (another connection) or cost a round
        trip for values the caller already has.
        """
        from api.models import PotentialOrder
        return PotentialOrder(**fields)

    def create_state_history_on(self, cursor, potential_order_id: int, state_id: int,
                                user_id: int, changed_at) -> None:
        """create_state_history, on the caller's cursor. Same reasoning as above —
        an order and the state history that explains it must commit together."""
        cursor.execute(
            """INSERT INTO order_state_history
                 (potential_order_id, state_id, changed_by, changed_at)
               VALUES (%s, %s, %s, %s)""",
            (potential_order_id, state_id, user_id, changed_at),
        )

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
