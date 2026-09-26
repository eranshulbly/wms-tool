# -*- encoding: utf-8 -*-
"""
Order Upload Service — extends BaseUploadService for the Template Method pipeline.

Backward-compatible module-level function kept so existing route calls
(order_service.process_order_upload(...)) require no changes.
"""

import os

from api.models import mysql_manager
from api.modules.fulfillment.order.business import process_order_dataframe
from api.modules.platform.catalog.dealer_business import clear_dealer_cache
from api.core.logging import get_logger
from api.shared.upload_base import BaseUploadService

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


class OrderUploadService(BaseUploadService):
    """Upload service for order files."""

    upload_type = 'orders'
    required_columns = ['Sales Order #']

    def process_dataframe(self, df, context: dict) -> dict:
        clear_dealer_cache()
        result = process_order_dataframe(
            df,
            context['warehouse_id'],
            context.get('company_id'),
            context['user_id'],
            context['upload_batch_id'],
        )
        return {
            'processed_count': result['orders_processed'],
            'error_rows': result['error_rows'],
        }


# ── Backward-compatible shim ──────────────────────────────────────────────────

_service = OrderUploadService()


def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    """Process an uploaded order file. Returns (result_dict, http_status_code)."""
    return _service.execute(
        uploaded_file,
        {'warehouse_id': warehouse_id, 'company_id': company_id, 'user_id': user_id},
    )


# ── Ancillary helpers (not part of the upload pipeline) ──────────────────────

def validate_order_data(df):
    """
    Validate order data before processing.

    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []

    if df.empty:
        errors.append("File contains no data")
        return False, errors

    required_cols = ['Sales Order #']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {', '.join(missing_cols)}")

    if 'Sales Order #' in df.columns:
        empty_orders = df[df['Sales Order #'].isnull() | (df['Sales Order #'] == '')].shape[0]
        if empty_orders > 0:
            errors.append(f"{empty_orders} rows have empty Sales Order # field")

    return len(errors) == 0, errors


def get_upload_statistics(warehouse_id=None, company_ids=None):
    """Return aggregate statistics about orders in the DB.

    `company_ids` is the caller's resolved tenant scope (permissions.resolve_company_scope),
    not a raw request parameter. Currently unused by any route — kept tenant-safe so wiring
    it up later cannot reintroduce an unfiltered read.
    """
    try:
        from api.permissions import company_filter_sql
        cf_sql, cf_params = company_filter_sql(company_ids)
        base_query = f"SELECT COUNT(*) as count FROM potential_order WHERE {cf_sql}"
        params = list(cf_params)

        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        total_result = mysql_manager.execute_query(base_query, params)
        total_orders = total_result[0]['count'] if total_result else 0

        status_query = base_query.replace("COUNT(*)", "status, COUNT(*) as count") + " GROUP BY status"
        status_results = mysql_manager.execute_query(status_query, params)
        status_breakdown = {r['status']: r['count'] for r in status_results}

        recent_query = base_query + " AND DATE(created_at) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
        recent_result = mysql_manager.execute_query(recent_query, params)
        recent_orders = recent_result[0]['count'] if recent_result else 0

        product_query = (
            "SELECT COUNT(*) as count FROM potential_order_product pop "
            "JOIN potential_order po ON pop.potential_order_id = po.potential_order_id WHERE 1=1"
        )
        pcf_sql, pcf_params = company_filter_sql(company_ids, alias='po')
        product_query += f" AND {pcf_sql}"
        product_params = list(pcf_params)
        if warehouse_id:
            product_query += " AND po.warehouse_id = %s"
            product_params.append(warehouse_id)

        product_result = mysql_manager.execute_query(product_query, product_params)
        total_products = product_result[0]['count'] if product_result else 0

        return {
            'total_orders': total_orders,
            'total_products': total_products,
            'recent_orders': recent_orders,
            'status_breakdown': status_breakdown,
        }

    except Exception:
        logger.exception("Error getting upload statistics")
        return {'total_orders': 0, 'total_products': 0, 'recent_orders': 0, 'status_breakdown': {}}


class PackCompletionError(Exception):
    """The order cannot be marked packed. Raised for a bad transition or a
    missing order — callers map it to a 409/404 of their own."""


def record_pack_completion(potential_order_id: int, packed_quantities: dict,
                           box_count: int, user_id: int,
                           short_pack_reason: str = None, cursor=None) -> dict:
    """Close a packing job onto the order. The ONLY writer of packed quantities.

    The packing module owns no order tables, so it calls this rather than issuing
    its own UPDATE against `potential_order*` — the cross-module boundary rule the
    rest of this codebase follows. Everything a completed pack changes is here, in
    one place, so a second consumer (a future picking-to-pack handoff, a correction
    tool) cannot write a different subset and leave the order half-updated.

    Writes, in order:
      1. `potential_order_product.quantity_packed` / `quantity_remaining` per line
      2. `potential_order.status = 'Packed'`, `box_count`, `short_pack_reason`
      3. one `order_state_history` row

    `box_count` is not decoration. It is read when the invoice and the `order` row
    are created (`invoice/repository.py`), so a count that never reaches the order
    ships the default of `1` onto every invoice regardless of how many boxes
    physically exist.

    Args:
        potential_order_id: the order being closed.
        packed_quantities: {product_id: packed base units}. Lines absent from the
            map are set to 0 packed — an order is closed as a whole, and leaving a
            line at its previous value would record a quantity no box supports.
        box_count: sealed box rows on the job.
        user_id: the packer, recorded as `changed_by` on the history row.
        short_pack_reason: free text; None leaves the column untouched.
        cursor: an open cursor to join the caller's transaction. Passing one is
            what makes the movement rows and the order write commit or roll back
            together; omitting it opens a transaction here.

    Returns:
        {'potential_order_id', 'status', 'box_count', 'lines_updated'}

    Raises:
        PackCompletionError: order missing, or not in a state that may go to Packed.
    """
    from api.modules.fulfillment.order.constants import OrderStatus
    from api.modules.fulfillment.order.state_machine import OrderStateMachine
    from api.shared.db_manager import partition_filter
    from datetime import datetime

    def _run(cur):
        pf_sql, pf_params = partition_filter('potential_order')
        cur.execute(
            f"""SELECT potential_order_id, status FROM potential_order
                WHERE {pf_sql} AND potential_order_id = %s""",
            (*pf_params, potential_order_id))
        rows = cur.fetchall()
        if not rows:
            raise PackCompletionError(f"order {potential_order_id} not found")

        current = rows[0]['status']
        # Packed -> Packed is not in the state machine but is the normal shape of a
        # retried submit, and refusing it would turn a lost response into a stuck
        # order. Every other illegal source is still refused.
        if current != OrderStatus.PACKED.value and not OrderStateMachine.can_single_transition(
                OrderStatus(current), OrderStatus.PACKED):
            raise PackCompletionError(
                f"order {potential_order_id} is {current}; it cannot be marked Packed")

        pop_pf_sql, pop_pf_params = partition_filter('potential_order_product')
        cur.execute(
            f"""SELECT potential_order_product_id, product_id, quantity
                FROM potential_order_product
                WHERE {pop_pf_sql} AND potential_order_id = %s""",
            (*pop_pf_params, potential_order_id))
        lines = cur.fetchall() or []

        updates = []
        for line in lines:
            packed = int(packed_quantities.get(line['product_id'], 0) or 0)
            required = int(line['quantity'] or 0)
            # The partition column rides in the WHERE of every row's params: without
            # it a single-row UPDATE probes every monthly partition, and this runs
            # once per line.
            updates.append((packed, max(required - packed, 0),
                            *pop_pf_params, line['potential_order_product_id']))
        if updates:
            # executemany, not a loop of execute: an order with 200 lines would
            # otherwise be 200 round trips inside a transaction holding row locks.
            cur.executemany(
                f"""UPDATE potential_order_product
                       SET quantity_packed = %s, quantity_remaining = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE {pop_pf_sql} AND potential_order_product_id = %s""",
                updates)

        order_sets = ["status = %s", "box_count = %s", "updated_at = CURRENT_TIMESTAMP"]
        order_params = [OrderStatus.PACKED.value, int(box_count)]
        if short_pack_reason is not None:
            order_sets.append("short_pack_reason = %s")
            order_params.append(short_pack_reason[:255])
        cur.execute(
            f"""UPDATE potential_order SET {', '.join(order_sets)}
                WHERE {pf_sql} AND potential_order_id = %s""",
            (*order_params, *pf_params, potential_order_id))

        cur.execute("SELECT state_id FROM order_state WHERE state_name = %s",
                    (OrderStatus.PACKED.value,))
        state_rows = cur.fetchall()
        if state_rows:
            cur.execute(
                """INSERT INTO order_state_history
                     (potential_order_id, state_id, changed_by, changed_at)
                   VALUES (%s, %s, %s, %s)""",
                (potential_order_id, state_rows[0]['state_id'], user_id, datetime.utcnow()))
        else:
            # The states are seeded at startup, so an absent row means a
            # misconfigured database. The pack itself is still correct and must not
            # be lost over a missing audit lookup.
            logger.error("order_state 'Packed' is missing — no history row written",
                         extra={'potential_order_id': potential_order_id})

        return {
            'potential_order_id': potential_order_id,
            'status': OrderStatus.PACKED.value,
            'box_count': int(box_count),
            'lines_updated': len(updates),
        }

    if cursor is not None:
        return _run(cursor)
    with mysql_manager.get_cursor() as cur:
        return _run(cur)


def cleanup_temporary_files():
    """Remove temp files older than 1 hour from the service tmp directory."""
    import time

    try:
        tmp_dir = os.path.join(BASE_DIR, 'tmp')
        if not os.path.exists(tmp_dir):
            return
        current_time = time.time()
        for filename in os.listdir(tmp_dir):
            file_path = os.path.join(tmp_dir, filename)
            if os.path.isfile(file_path) and current_time - os.path.getmtime(file_path) > 3600:
                try:
                    os.remove(file_path)
                    logger.debug("Removed old temp file", extra={'filename': filename})
                except Exception:
                    logger.warning("Error removing temp file", extra={'filename': filename})
    except Exception:
        logger.exception("Error during temp file cleanup")
