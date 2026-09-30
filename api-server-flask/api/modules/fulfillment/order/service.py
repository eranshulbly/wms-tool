# -*- encoding: utf-8 -*-
"""
Order Upload Service — extends BaseUploadService for the Template Method pipeline.

Backward-compatible module-level function kept so existing route calls
(order_service.process_order_upload(...)) require no changes.
"""

import os

from api.models import mysql_manager
from api.modules.fulfillment.order.business import process_order_dataframe
from api.modules.platform.catalog.product_upload_business import (
    process_product_upload_dataframe,
)
from api.modules.platform.catalog.dealer_business import clear_dealer_cache
from api.core.logging import get_logger
from api.shared.upload_base import BaseUploadService

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


class OrderUploadService(BaseUploadService):
    """Upload service for order files."""

    upload_type = 'orders'
    required_columns = ['Sales Order #']

    # The line-item columns. A file carrying these describes its own contents, so the
    # order upload reads them itself instead of waiting for a second file — which is what
    # left a PDF-sourced order with a header and no items.
    LINE_COLUMNS = ('Part #', 'Reserved Qty')

    def before_processing(self, df, context: dict):
        """Ask about replaceable duplicates, then refuse a file selling unreceived stock.

        Two independent gates, in order, both running before anything is written:

        1. Duplicate orders. A number already on file for this company either can be
           replaced (not yet Invoiced or later — see business.classify_order_duplicates)
           or can't. A replaceable one needs a decision only the operator can make, so —
           unless context already carries one, from the confirm re-submit — this stops
           and asks instead of silently skipping it, the same way ProductUploadService
           asks about missing part numbers below. A blocked one (already Invoiced or
           later) was never a decision to make; it stays a plain skip, as before this
           feature existed.

        2. Batches not received. Only for files that name batches (the supplier's PDF
           invoices). The invoice upload closes an order by taking stock out of the exact
           batches on it, so an order that names a batch never received could be opened
           but never closed. Rows of orders that will end up skipped either way (blocked,
           or replaceable-but-declined) are left out: the upload skips those anyway, and
           blaming a batch would hide the real reason the row did nothing. A replaceable
           duplicate the operator chose to replace IS checked — it is about to be
           recreated from this file, same as any new order.
        """
        duplicate_action = context.get('duplicate_action')
        if 'Sales Order #' in df.columns and not duplicate_action:
            from api.modules.fulfillment.order.business import classify_order_duplicates

            replaceable, _blocked = classify_order_duplicates(df, context.get('company_id'))
            if replaceable:
                logger.info("Order upload awaiting duplicate-replace decision",
                            extra={'company_id': context.get('company_id'),
                                   'duplicate_count': len(replaceable)})
                return {
                    'success': True,
                    'needs_confirmation': True,
                    'msg': (f"{len(replaceable)} order(s) in this file already exist and "
                            f"have not been invoiced yet, so they can be replaced with the "
                            f"new data. Choose Replace or Skip for them below."),
                    'duplicate_orders': [
                        {'order_id': oid, 'name': row['purchaser_name'] or '',
                         'status': row['status']}
                        for oid, row in replaceable.items()
                    ],
                    'processed_count': 0,
                    'error_count': 0,
                }, 200

        if 'Batch #' not in df.columns or 'Part #' not in df.columns:
            return None

        from api.modules.platform.catalog.product_upload_business import _batch_key
        from api.modules.fulfillment.order.business import classify_order_duplicates
        from api.repositories import product_repo

        company_id = context.get('company_id')
        rows = [r for _, r in df.iterrows() if str(r.get('Batch #') or '').strip()]
        if not rows:
            return None

        replaceable, blocked = classify_order_duplicates(df, company_id)
        skipped = set(blocked) | (set() if duplicate_action == 'replace' else set(replaceable))
        rows = [r for r in rows
                if str(r.get('Sales Order #') or '').strip() not in skipped]
        if not rows:
            return None

        products = product_repo.find_bulk_by_part_numbers(
            list({str(r.get('Part #') or '').strip() for r in rows}))

        wanted, missing = {}, []
        for r in rows:
            part = str(r.get('Part #') or '').strip()
            batch = str(r.get('Batch #') or '').strip()
            label = f"{str(r.get('Part Description') or part).strip()} (batch {batch})"
            product = products.get(part)
            if not product:
                missing.append(f"{label} — product not in the catalogue")
                continue
            wanted[_batch_key(product['product_id'], batch)] = label

        if wanted:
            placeholders = ','.join(['%s'] * len(wanted))
            found = {x['batch_hash'] for x in (mysql_manager.execute_query(
                f"SELECT batch_hash FROM sku_batch WHERE batch_hash IN ({placeholders})",
                tuple(wanted)) or [])}
            missing += [label for key, label in wanted.items() if key not in found]

        if not missing:
            return None

        shown = '; '.join(missing[:5]) + (f'; and {len(missing) - 5} more' if len(missing) > 5 else '')
        logger.info("Order upload refused: batches not received",
                    extra={'company_id': company_id, 'missing': len(missing)})
        return {
            'success': False,
            'msg': (f"Not uploaded — {len(missing)} line(s) name stock that has not been "
                    f"received, so this order could never be closed: {shown}. Receive the "
                    f"stock through Inventory Ingestion first, then upload again. "
                    f"Nothing was saved."),
            'processed_count': 0,
            'error_count': len(missing),
        }, 400

    def process_dataframe(self, df, context: dict) -> dict:
        clear_dealer_cache()
        company_id = context.get('company_id')
        result = process_order_dataframe(
            df,
            context['warehouse_id'],
            company_id,
            context['user_id'],
            context['upload_batch_id'],
            context.get('duplicate_action'),
        )

        out = {
            'processed_count': result['orders_processed'],
            'error_rows': result['error_rows'],
        }

        # Line items, from the same file, when it actually carries them. A file without
        # these columns behaves exactly as before: header only, lines supplied later by
        # the Products upload.
        if not all(c in df.columns for c in self.LINE_COLUMNS):
            return out

        # Lines are attached only to orders THIS upload created. The line pass replaces an
        # order's lines wholesale, so running it over a re-uploaded file would delete and
        # re-insert the lines of an order that already exists — one that may already be
        # closed, with its stock gone.
        created = result.get('created_order_ids') or set()
        if not created:
            return out
        line_df = df[df['Sales Order #'].astype(str).str.strip().isin(created)].copy()
        # The two uploads name the order column differently; the order file is the one
        # that says 'Sales Order #'.
        if 'Order #' not in line_df.columns:
            line_df['Order #'] = line_df['Sales Order #']

        try:
            lines = process_product_upload_dataframe(
                line_df, company_id, context['user_id'], context['upload_batch_id'])
        except Exception:
            # The orders are already committed. A failure here must not lose them or
            # present the upload as a total failure — it is reported as a row error so
            # the operator knows to run the Products upload for the missing lines.
            logger.exception("Order upload: line items could not be attached")
            out['error_rows'] = list(out['error_rows']) + [{
                'order_id': '', 'name': '',
                'reason': 'Orders were created but their line items could not be read — '
                          'upload the products file for them.'}]
            return out

        out['products_processed'] = lines.get('products_processed', 0)
        out['orders_updated'] = lines.get('orders_updated', 0)
        out['error_rows'] = list(out['error_rows']) + list(lines.get('error_rows') or [])
        logger.info("Order upload attached line items",
                    extra={'orders': out['processed_count'],
                           'lines': out['products_processed']})
        return out


# ── Backward-compatible shim ──────────────────────────────────────────────────

_service = OrderUploadService()


def process_order_upload(uploaded_file, warehouse_id, company_id, user_id, duplicate_action=None):
    """Process an uploaded order file. Returns (result_dict, http_status_code).

    duplicate_action — 'replace' or 'skip', only ever set on the confirm re-submit after
    before_processing asked about a replaceable duplicate (see OrderUploadService).
    """
    return _service.execute(
        uploaded_file,
        {'warehouse_id': warehouse_id, 'company_id': company_id, 'user_id': user_id,
         'duplicate_action': duplicate_action},
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
