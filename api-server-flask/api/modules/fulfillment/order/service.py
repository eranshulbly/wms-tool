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
        company_id = context.get('company_id')
        result = process_order_dataframe(
            df,
            context['warehouse_id'],
            company_id,
            context['user_id'],
            context['upload_batch_id'],
        )
        error_rows = list(result['error_rows'])

        # A spreadsheet of orders carries no line items — one row IS one order — so this
        # step does nothing for it. An Order Challan carries both: the order header and
        # the items ordered. Rather than making the operator upload the same PDF twice
        # (once here, once on the products screen), the items are attached now.
        #
        # Order of operations matters. Products are synced BEFORE the lines are attached,
        # so a part the catalogue has never seen exists — with its HSN, GST, unit and
        # rate — by the time a line has to point at it. Attaching first would create the
        # same product as a bare code-and-name stub and throw the rest away.
        if 'Part #' in df.columns and 'Reserved Qty' in df.columns:
            from api.modules.fulfillment.order import product_sync
            from api.modules.platform.catalog.product_upload_business import (
                process_product_upload_dataframe)

            # Lines are attached ONLY for orders this upload actually created.
            #
            # An order number reaches error_rows only by failing — most often because it
            # already exists — and the operator is told it was "skipped, nothing changed".
            # That has to be true. process_product_upload_dataframe works in REPLACE mode:
            # it deletes an order's existing line items and re-inserts them with
            # quantity_packed reset to 0. Letting a refused order through would mean
            # re-uploading a challan silently rewrote a live order's lines and discarded
            # whatever the warehouse had already packed against them.
            refused = {str(r.get('order_id') or '').strip()
                       for r in result['error_rows'] if str(r.get('order_id') or '').strip()}
            attachable = df[~df['Sales Order #'].astype(str).str.strip().isin(refused)] \
                if refused else df

            if attachable.empty:
                logger.info("No line items attached — every order in the file was refused",
                            extra={'refused_orders': len(refused)})
            else:
                products = product_sync.sync_products(attachable, company_id)
                lines = process_product_upload_dataframe(
                    attachable, company_id, context['user_id'], context['upload_batch_id'])
                error_rows.extend(lines.get('error_rows') or [])
                logger.info("Order upload also attached line items", extra={
                    'products_created': products['created'],
                    'products_enriched': products['enriched'],
                    'lines_attached': lines.get('products_processed', 0),
                    'orders_touched': lines.get('orders_updated', 0),
                    'refused_orders': len(refused)})

        return {
            'processed_count': result['orders_processed'],
            'error_rows': error_rows,
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
