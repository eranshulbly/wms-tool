# -*- encoding: utf-8 -*-
"""
InvoiceRepository — all bulk SQL for the invoice upload pipeline.

The 3-phase bulk-write pattern lives here so invoice_business.py contains
only classification logic (pure Python, zero DB calls) while this class
owns every database round-trip.
"""

from ..core.logging import get_logger
from .base_repository import BaseRepository

logger = get_logger(__name__)

# Fixed column order for the bulk invoice INSERT.
# Must match the fields set by invoice_business.create_invoice_from_row().
_INVOICE_COLUMNS = (
    'potential_order_id', 'warehouse_id', 'company_id', 'dealer_id',
    'invoice_number', 'original_order_id', 'invoice_date', 'invoice_type',
    'cancellation_date', 'total_invoice_amount', 'invoice_header_type',
    'order_date', 'b2b_purchase_order_number', 'b2b_order_type',
    'account_tin', 'cash_customer_name', 'contact_first_name',
    'contact_last_name', 'customer_category',
    'round_off_amount', 'invoice_round_off_amount', 'short_amount', 'realized_amount',
    'hmcgl_card_no', 'campaign',
    'packaging_forwarding_charges', 'tax_on_pf', 'type_of_tax_pf',
    'irn_number', 'irn_status', 'ack_number', 'ack_date',
    'credit_note_number', 'irn_cancel', 'irn_status_cancel',
    'ack_number_cancel', 'ack_date_cancel',
    'uploaded_by', 'upload_batch_id', 'created_at', 'updated_at',
)


class InvoiceRepository(BaseRepository):
    """Bulk DB writes for the invoice upload pipeline."""

    def get_bypass_order_types(self) -> set:
        """Return the set of order_type values that skip the Packed prerequisite."""
        from ..models import InvoiceProcessingConfig
        return InvoiceProcessingConfig.get_bypass_order_types()

    def bulk_insert_invoices(self, invoices: list) -> int:
        """
        INSERT all Invoice objects in a single executemany call.

        Uses INSERT IGNORE so duplicate invoice_numbers are silently skipped
        rather than aborting the whole batch.

        Returns:
            Number of rows actually inserted.
        """
        if not invoices:
            return 0

        col_str = ', '.join(_INVOICE_COLUMNS)
        ph_str  = ', '.join(['%s'] * len(_INVOICE_COLUMNS))
        sql = f"INSERT IGNORE INTO invoice ({col_str}) VALUES ({ph_str})"
        rows = [tuple(getattr(inv, col) for col in _INVOICE_COLUMNS) for inv in invoices]

        with self._db.get_cursor() as cursor:
            cursor.executemany(sql, rows)
            return cursor.rowcount

    def bulk_transition_to_invoiced(self, orders_to_invoice: dict, dealer_backfills: dict,
                                    state_id: int, user_id: int, current_time) -> None:
        """
        Transition a batch of PotentialOrders to Invoiced in three executemany calls:
          1. UPDATE potential_order  — status + optional dealer backfill
          2. INSERT `order`          — one row per unique potential order
          3. INSERT order_state_history
        """
        if not orders_to_invoice:
            return

        ts_str = current_time.strftime('%Y%m%d%H%M')

        # 1. Bulk UPDATE potential_orders
        po_params = [
            (dealer_backfills.get(pot_id), current_time, pot_id)
            for pot_id in orders_to_invoice
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """UPDATE potential_order
                   SET status = 'Invoiced',
                       invoice_submitted = 0,
                       dealer_id = COALESCE(dealer_id, %s),
                       updated_at = %s
                   WHERE potential_order_id = %s""",
                po_params
            )

        # 2. Bulk INSERT Order records
        order_params = [
            (pot_id, f"ORD-{pot_id}-{ts_str}", 'Invoiced', po.box_count or 1, current_time, current_time)
            for pot_id, po in orders_to_invoice.items()
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO `order`
                   (potential_order_id, order_number, status, box_count, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                order_params
            )

        # 3. Bulk INSERT state history
        hist_params = [
            (pot_id, state_id, user_id, current_time)
            for pot_id in orders_to_invoice
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT INTO order_state_history
                   (potential_order_id, state_id, changed_by, changed_at)
                   VALUES (%s, %s, %s, %s)""",
                hist_params
            )

    def bulk_migrate_products_to_order(self, orders_to_invoice: dict, current_time) -> None:
        """
        Copy potential_order_product rows into order_product for all just-invoiced orders.

        Runs after bulk_transition_to_invoiced has committed the `order` records.
        Uses two SELECTs + one executemany INSERT.
        """
        if not orders_to_invoice:
            return

        pot_ids = list(orders_to_invoice.keys())
        placeholders = ','.join(['%s'] * len(pot_ids))

        # Fetch order_id for each potential_order_id
        pf_sql_o, pf_params_o = self._pf('order')
        order_rows = self._db.execute_query(
            f"SELECT order_id, potential_order_id FROM `order` "
            f"WHERE {pf_sql_o} AND potential_order_id IN ({placeholders})",
            pf_params_o + tuple(pot_ids)
        )
        if not order_rows:
            return

        pot_to_order = {r['potential_order_id']: r['order_id'] for r in order_rows}

        # Bulk fetch product rows for those potential orders
        pf_sql_p, pf_params_p = self._pf('potential_order_product')
        pop_rows = self._db.execute_query(
            f"SELECT potential_order_id, product_id, quantity, mrp, total_price "
            f"FROM potential_order_product "
            f"WHERE {pf_sql_p} AND potential_order_id IN ({placeholders})",
            pf_params_p + tuple(pot_ids)
        )
        if not pop_rows:
            return

        op_rows = [
            (pot_to_order[r['potential_order_id']], r['product_id'],
             r['quantity'], r['mrp'], r['total_price'], current_time, current_time)
            for r in pop_rows
            if r['potential_order_id'] in pot_to_order
        ]

        if op_rows:
            with self._db.get_cursor() as cursor:
                cursor.executemany(
                    """INSERT IGNORE INTO order_product
                       (order_id, product_id, quantity, mrp, total_price, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    op_rows
                )
            logger.debug("Migrated product rows", extra={'product_rows': len(op_rows), 'orders': len(pot_to_order)})

    def migrate_products_to_order_single(self, potential_order_id: int,
                                          order_id: int, current_time) -> None:
        """
        Copy potential_order_product rows into order_product for a single order.
        Used by the single-order invoicing path (update_order_to_invoiced).
        """
        pf_sql, pf_params = self._pf('potential_order_product')
        pop_rows = self._db.execute_query(
            f"SELECT product_id, quantity, mrp, total_price FROM potential_order_product "
            f"WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        if not pop_rows:
            return

        op_rows = [
            (order_id, r['product_id'], r['quantity'], r['mrp'],
             r['total_price'], current_time, current_time)
            for r in pop_rows
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO order_product
                   (order_id, product_id, quantity, mrp, total_price, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                op_rows
            )
        logger.debug("Migrated product rows for single order",
                     extra={'product_rows': len(op_rows), 'order_id': order_id})

    def bulk_flag_orders(self, orders_to_flag: dict, current_time) -> None:
        """Set invoice_submitted=1 on a batch of PotentialOrders in one executemany call."""
        if not orders_to_flag:
            return
        params = [(current_time, pot_id) for pot_id in orders_to_flag]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """UPDATE potential_order
                   SET invoice_submitted = 1, updated_at = %s
                   WHERE potential_order_id = %s""",
                params
            )
