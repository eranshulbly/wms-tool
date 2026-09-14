# -*- encoding: utf-8 -*-
"""
Invoice Upload Service — extends BaseUploadService for the Template Method pipeline.

Backward-compatible module-level function kept so existing route calls
(invoice_service.process_invoice_upload(...)) require no changes.
"""

import os

import pandas as pd

from api.models import mysql_manager
from api.modules.fulfillment.invoice.business import process_invoice_dataframe
from api.core.logging import get_logger
from api.shared.upload_base import BaseUploadService

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


class InvoiceUploadService(BaseUploadService):
    """Upload service for invoice files."""

    upload_type = 'invoices'
    required_columns = ['Invoice #', 'Order #']

    def process_dataframe(self, df, context: dict) -> dict:
        # A Tax Invoice PDF arrives as one row PER LINE ITEM, because its line items are
        # what tells the stock ledger which goods left. The invoice RECORD is header-level
        # though — one row is one invoice — so only the first row is billed. Without this
        # a three-line invoice would create three identical invoice records.
        #
        # Spreadsheet feeds carry no 'Source Doc' and are untouched: they already arrive
        # at the grain this service has always expected.
        is_pdf_invoice = ('Source Doc' in df.columns
                          and (df['Source Doc'] == 'tax_invoice').any())
        header_df = df.head(1) if is_pdf_invoice else df

        result = process_invoice_dataframe(
            header_df,
            context['warehouse_id'],
            context.get('company_id'),
            context['user_id'],
            context['upload_batch_id'],
        )

        # Invoiced goods have been billed and have left the building, so they come off the
        # shelf. Done ONLY when an invoice was actually created: a re-upload of the same
        # invoice is refused upstream (the order is already Invoiced), and reducing stock
        # again would take the same goods out twice.
        stock = None
        if is_pdf_invoice and result['invoices_processed'] > 0:
            from api.modules.fulfillment.order import temp_inventory
            stock = temp_inventory.reduce_stock([
                {'part_number': row.get('Part #'), 'quantity': row.get('Reserved Qty')}
                for _, row in df.iterrows()
            ])
            logger.info("Invoice upload reduced stock", extra={
                'parts_reduced': stock['parts'], 'units_reduced': stock['units'],
                'parts_not_in_stock_sheet': len(stock['missing'])})

        out = {
            'processed_count': result['invoices_processed'],
            'error_rows': result['error_rows'],
            'orders_invoiced': result['orders_invoiced'],
            'orders_flagged': result['orders_flagged'],
        }
        if stock is not None:
            out['stock_parts_reduced'] = stock['parts']
            out['stock_units_reduced'] = stock['units']
            # Named plainly: these parts were billed but the stock sheet has never heard
            # of them, so nothing could be deducted for them.
            out['stock_parts_missing'] = stock['missing']
        return out


# ── Backward-compatible shim ──────────────────────────────────────────────────

_service = InvoiceUploadService()


def process_invoice_upload(uploaded_file, warehouse_id, company_id, user_id):
    """Process an uploaded invoice file. Returns (result_dict, http_status_code)."""
    return _service.execute(
        uploaded_file,
        {'warehouse_id': warehouse_id, 'company_id': company_id, 'user_id': user_id},
    )


# ── Ancillary helpers (not part of the upload pipeline) ──────────────────────

def analyze_errors(errors):
    """Summarise a list of error messages into a human-readable string."""
    if not errors:
        return "Unknown errors occurred."

    counts = {'missing_orders': 0, 'wrong_status': 0, 'missing_data': 0, 'other': 0}
    for error in errors:
        e = error.lower()
        if 'no matching order found' in e:
            counts['missing_orders'] += 1
        elif 'already invoiced' in e or 'dispatch ready' in e or 'partially completed' in e:
            counts['wrong_status'] += 1
        elif 'missing' in e:
            counts['missing_data'] += 1
        else:
            counts['other'] += 1

    parts = []
    if counts['missing_orders']:
        parts.append(f"{counts['missing_orders']} invoices had no matching orders in the system")
    if counts['wrong_status']:
        parts.append(f"{counts['wrong_status']} orders were already invoiced or in a terminal state")
    if counts['missing_data']:
        parts.append(f"{counts['missing_data']} rows had missing required data")
    if counts['other']:
        parts.append(f"{counts['other']} rows had other issues")

    suffix = ". Please download the error report for detailed information."
    return (". ".join(parts) + suffix) if parts else "Please download the error report for detailed information."


def validate_invoice_data(df):
    """
    Validate invoice DataFrame before processing.

    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []

    if df.empty:
        errors.append("File contains no data")
        return False, errors

    required_cols = ['Invoice #', 'Order #']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {', '.join(missing_cols)}")

    if 'Invoice #' in df.columns:
        empty = df[df['Invoice #'].isnull() | (df['Invoice #'] == '')].shape[0]
        if empty:
            errors.append(f"{empty} rows have empty Invoice # field")

    if 'Order #' in df.columns:
        empty = df[df['Order #'].isnull() | (df['Order #'] == '')].shape[0]
        if empty:
            errors.append(f"{empty} rows have empty Order # field (Sales Order / PSAO number)")

    for field in ('Total Invoice Amount', 'Quantity', 'Unit Price'):
        if field in df.columns:
            try:
                invalid = df[
                    pd.to_numeric(df[field], errors='coerce').isnull()
                    & df[field].notna()
                    & (df[field] != '')
                ].shape[0]
                if invalid:
                    errors.append(f"{invalid} rows have invalid {field} values")
            except Exception:
                errors.append(f"Unable to validate {field} column")

    return len(errors) == 0, errors


def get_invoice_statistics(warehouse_id=None, company_ids=None, batch_id=None):
    """Return aggregate statistics about invoices in the DB.

    `company_ids` is the caller's resolved tenant scope (permissions.resolve_company_scope),
    not a raw request parameter.
    """
    try:
        from api.permissions import company_filter_sql
        cf_sql, cf_params = company_filter_sql(company_ids)
        base_query = f"SELECT COUNT(*) as count FROM invoice WHERE {cf_sql}"
        params = list(cf_params)
        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)
        if batch_id:
            base_query += " AND upload_batch_id = %s"
            params.append(batch_id)

        total_result = mysql_manager.execute_query(base_query, params)
        total_invoices = total_result[0]['count'] if total_result else 0

        # base_query aliases its aggregate `as count`, so the substituted aggregate lands
        # under that same alias — reading it by the expression text raises KeyError and
        # silently zeroed this whole endpoint via the except block below.
        unique_result = mysql_manager.execute_query(
            base_query.replace("COUNT(*)", "COUNT(DISTINCT potential_order_id)"), params
        )
        unique_orders = unique_result[0]['count'] if unique_result else 0

        amount_result = mysql_manager.execute_query(
            base_query.replace("COUNT(*)", "SUM(total_invoice_amount)"), params
        )
        total_amount = amount_result[0]['count'] if amount_result else 0

        recent_q = (
            "SELECT upload_batch_id, COUNT(*) as invoice_count, "
            "MAX(created_at) as upload_date, SUM(total_invoice_amount) as batch_total "
            f"FROM invoice WHERE {cf_sql}"
        )
        recent_params = list(cf_params)
        if warehouse_id:
            recent_q += " AND warehouse_id = %s"
            recent_params.append(warehouse_id)
        recent_q += " GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 10"

        recent_batches = [
            {
                'batch_id': r['upload_batch_id'],
                'invoice_count': r['invoice_count'],
                'upload_date': r['upload_date'].isoformat() if r['upload_date'] else None,
                'batch_total': float(r['batch_total']) if r['batch_total'] else 0.0,
            }
            for r in mysql_manager.execute_query(recent_q, recent_params)
        ]

        status_q = f"SELECT invoice_status, COUNT(*) as count FROM invoice WHERE {cf_sql}"
        status_params = list(cf_params)
        if warehouse_id:
            status_q += " AND warehouse_id = %s"
            status_params.append(warehouse_id)
        if batch_id:
            status_q += " AND upload_batch_id = %s"
            status_params.append(batch_id)
        status_q += " GROUP BY invoice_status"

        status_breakdown = {
            r['invoice_status'] or 'Unknown': r['count']
            for r in mysql_manager.execute_query(status_q, status_params)
        }

        return {
            'total_invoices': total_invoices,
            'unique_orders': unique_orders,
            'total_amount': float(total_amount or 0),
            'recent_batches': recent_batches,
            'status_breakdown': status_breakdown,
        }

    except Exception:
        logger.exception("Error getting invoice statistics")
        return {
            'total_invoices': 0,
            'unique_orders': 0,
            'total_amount': 0.0,
            'recent_batches': [],
            'status_breakdown': {},
        }


def get_invoice_batch_details(batch_id):
    """Return detailed information about a specific invoice batch."""
    try:
        batch_result = mysql_manager.execute_query(
            "SELECT COUNT(*) as invoice_count, SUM(total_invoice_amount) as batch_total, "
            "MIN(created_at) as start_time, MAX(created_at) as end_time, "
            "COUNT(DISTINCT potential_order_id) as unique_orders, uploaded_by "
            "FROM invoice WHERE upload_batch_id = %s",
            (batch_id,),
        )

        if not batch_result or batch_result[0]['invoice_count'] == 0:
            return {'found': False, 'message': 'Batch not found'}

        info = batch_result[0]
        invoices = [
            {
                'invoice_id': r['invoice_id'],
                'invoice_number': r['invoice_number'],
                'original_order_id': r['original_order_id'],
                'customer_name': r['cash_customer_name'],
                'invoice_date': r['invoice_date'].isoformat() if r['invoice_date'] else None,
                'total_amount': float(r['total_invoice_amount']) if r['total_invoice_amount'] else 0.0,
                'status': r['invoice_status'],
                'processed_at': r['created_at'].isoformat(),
            }
            for r in mysql_manager.execute_query(
                "SELECT invoice_id, invoice_number, original_order_id, cash_customer_name, "
                "invoice_date, total_invoice_amount, invoice_status, created_at "
                "FROM invoice WHERE upload_batch_id = %s ORDER BY created_at",
                (batch_id,),
            )
        ]

        return {
            'found': True,
            'batch_id': batch_id,
            'summary': {
                'invoice_count': info['invoice_count'],
                'batch_total': float(info['batch_total']) if info['batch_total'] else 0.0,
                'unique_orders': info['unique_orders'],
                'start_time': info['start_time'].isoformat() if info['start_time'] else None,
                'end_time': info['end_time'].isoformat() if info['end_time'] else None,
                'uploaded_by': info['uploaded_by'],
            },
            'invoices': invoices,
        }

    except Exception:
        logger.exception("Error getting batch details", extra={'batch_id': batch_id})
        return {'found': False, 'message': 'Error retrieving batch details'}


def get_invoices_by_order(order_id):
    """Return all invoices for a given order (by original_order_id or potential_order_id)."""
    try:
        base_q = (
            "SELECT i.*, po.status as order_status "
            "FROM invoice i "
            "LEFT JOIN potential_order po ON i.potential_order_id = po.potential_order_id "
            "WHERE i.{col} = %s ORDER BY i.created_at DESC"
        )
        results = mysql_manager.execute_query(base_q.format(col='original_order_id'), (order_id,))

        if not results:
            try:
                pot_id = int(order_id.replace('PO', '')) if str(order_id).startswith('PO') else int(order_id)
                results = mysql_manager.execute_query(base_q.format(col='potential_order_id'), (pot_id,))
            except (ValueError, TypeError):
                pass

        return [
            {
                'invoice_id': r['invoice_id'],
                'invoice_number': r['invoice_number'],
                'original_order_id': r['original_order_id'],
                'customer_name': r['cash_customer_name'],
                'invoice_date': r['invoice_date'].isoformat() if r['invoice_date'] else None,
                'total_amount': float(r['total_invoice_amount']) if r['total_invoice_amount'] else 0.0,
                'invoice_status': r['invoice_status'],
                'order_status': r['order_status'],
                'part_no': r['part_no'],
                'part_name': r['part_name'],
                'quantity': r['quantity'],
                'unit_price': float(r['unit_price']) if r['unit_price'] else 0.0,
                'upload_batch_id': r['upload_batch_id'],
                'created_at': r['created_at'].isoformat(),
            }
            for r in results
        ]

    except Exception:
        logger.exception("Error getting invoices for order", extra={'order_id': order_id})
        return []


def get_invoice_trends(warehouse_id=None, company_ids=None, days=30):
    """Return daily invoice counts and amounts over the past `days` days."""
    try:
        q = (
            "SELECT DATE(created_at) as invoice_date, COUNT(*) as invoice_count, "
            "SUM(total_invoice_amount) as daily_total "
            "FROM invoice WHERE DATE(created_at) >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
        )
        from api.permissions import company_filter_sql
        cf_sql, cf_params = company_filter_sql(company_ids)
        q += f" AND {cf_sql}"
        params = [days] + list(cf_params)
        if warehouse_id:
            q += " AND warehouse_id = %s"
            params.append(warehouse_id)
        q += " GROUP BY DATE(created_at) ORDER BY invoice_date"

        daily_results = mysql_manager.execute_query(q, params)
        daily_trends = [
            {
                'date': r['invoice_date'].isoformat(),
                'invoice_count': r['invoice_count'],
                'daily_total': float(r['daily_total']) if r['daily_total'] else 0.0,
            }
            for r in daily_results
        ]

        if daily_results:
            total_inv = sum(r['invoice_count'] for r in daily_results)
            total_amt = sum(float(r['daily_total']) if r['daily_total'] else 0.0 for r in daily_results)
            n = len(daily_results)
        else:
            total_inv = total_amt = n = 0

        return {
            'daily_trends': daily_trends,
            'summary': {
                'period_days': days,
                'total_invoices': total_inv,
                'total_amount': total_amt,
                'avg_daily_invoices': round(total_inv / n, 2) if n else 0.0,
                'avg_daily_amount': round(total_amt / n, 2) if n else 0.0,
            },
        }

    except Exception:
        logger.exception("Error getting invoice trends")
        return {
            'daily_trends': [],
            'summary': {
                'period_days': days,
                'total_invoices': 0,
                'total_amount': 0.0,
                'avg_daily_invoices': 0.0,
                'avg_daily_amount': 0.0,
            },
        }


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
