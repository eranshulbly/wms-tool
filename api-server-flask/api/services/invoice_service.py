# -*- encoding: utf-8 -*-
"""
Invoice Upload Service for MySQL - Complete MySQL Implementation
"""

import os

import pandas as pd

from ..models import mysql_manager
from ..business.invoice_business import process_invoice_dataframe
from ..utils.upload_utils import (
    make_upload_response, read_upload_file, resolve_required_columns,
    save_temp_file, cleanup_temp_file, create_upload_batch,
)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def analyze_errors(errors):
    """
    Analyze error messages to provide meaningful summary

    Args:
        errors: List of error messages

    Returns:
        str: Summary of error types
    """
    if not errors:
        return "Unknown errors occurred."

    error_types = {
        'missing_orders': 0,
        'wrong_status': 0,
        'missing_data': 0,
        'other': 0
    }

    for error in errors:
        error_lower = error.lower()
        if 'no matching order found' in error_lower:
            error_types['missing_orders'] += 1
        elif 'already invoiced' in error_lower or 'dispatch ready' in error_lower or 'partially completed' in error_lower:
            error_types['wrong_status'] += 1
        elif 'missing' in error_lower:
            error_types['missing_data'] += 1
        else:
            error_types['other'] += 1

    # Create meaningful summary
    summary_parts = []

    if error_types['missing_orders'] > 0:
        summary_parts.append(f"{error_types['missing_orders']} invoices had no matching orders in the system")

    if error_types['wrong_status'] > 0:
        summary_parts.append(f"{error_types['wrong_status']} orders were already invoiced or in a terminal state")

    if error_types['missing_data'] > 0:
        summary_parts.append(f"{error_types['missing_data']} rows had missing required data")

    if error_types['other'] > 0:
        summary_parts.append(f"{error_types['other']} rows had other issues")

    if summary_parts:
        return ". ".join(summary_parts) + ". Please download the error report for detailed information."
    else:
        return "Please download the error report for detailed information."


def process_invoice_upload(uploaded_file, warehouse_id, company_id, user_id):
    """
    Process the uploaded invoice file and update order statuses using MySQL.

    Returns:
        tuple: (result_dict, status_code)
    """
    temp_path = None

    try:
        temp_path, file_extension = save_temp_file(uploaded_file, BASE_DIR)

        if file_extension not in ('.csv', '.xls', '.xlsx'):
            return {'success': False, 'msg': 'Unsupported file format. Please upload a CSV or Excel file.',
                    'processed_count': 0, 'error_count': 0}, 400

        df = read_upload_file(temp_path, file_extension)
        df = df.dropna(how='all')
        df.columns = df.columns.str.replace('\n', ' ').str.replace('\r', ' ').str.strip()

        df, error = resolve_required_columns(df, ['Invoice #', 'Order #'])
        if error:
            return {'success': False, 'msg': error, 'processed_count': 0, 'error_count': 0}, 400

        original_filename = uploaded_file.filename
        upload_batch_id = create_upload_batch(mysql_manager, 'invoices', original_filename, warehouse_id, company_id, user_id)

        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                result = process_invoice_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id)

                if result['invoices_processed'] > 0:
                    cursor.connection.commit()
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
                            (result['invoices_processed'], upload_batch_id), fetch=False
                        )
                else:
                    cursor.connection.rollback()
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False
                        )
                    upload_batch_id = None

        except Exception as db_error:
            if upload_batch_id:
                try:
                    mysql_manager.execute_query(
                        "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False
                    )
                except Exception:
                    pass
            raise db_error

        cleanup_temp_file(temp_path)

        return make_upload_response(
            result['invoices_processed'],
            result['error_rows'],
            orders_invoiced=result['orders_invoiced'],
            orders_flagged=result['orders_flagged'],
            upload_batch_id=upload_batch_id,
        )

    except Exception as e:
        print(f"Processing error: {str(e)}")
        cleanup_temp_file(temp_path)
        return {'success': False, 'msg': f'Error processing file: {str(e)}',
                'processed_count': 0, 'error_count': 0}, 400


def get_invoice_statistics(warehouse_id=None, company_id=None, batch_id=None):
    """
    Get statistics about invoice uploads using MySQL

    Args:
        warehouse_id: Optional warehouse filter
        company_id: Optional company filter
        batch_id: Optional batch filter

    Returns:
        dict: Statistics about invoices
    """
    try:
        # Build base query for total invoices
        base_query = "SELECT COUNT(*) as count FROM invoice WHERE 1=1"
        params = []

        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)
        if company_id:
            base_query += " AND company_id = %s"
            params.append(company_id)
        if batch_id:
            base_query += " AND upload_batch_id = %s"
            params.append(batch_id)

        # Get total invoices
        total_result = mysql_manager.execute_query(base_query, params)
        total_invoices = total_result[0]['count'] if total_result else 0

        # Get unique orders affected
        unique_query = base_query.replace("COUNT(*)", "COUNT(DISTINCT potential_order_id)")
        unique_result = mysql_manager.execute_query(unique_query, params)
        unique_orders = unique_result[0]['COUNT(DISTINCT potential_order_id)'] if unique_result else 0

        # Get total amount
        amount_query = base_query.replace("COUNT(*)", "SUM(total_invoice_amount)")
        amount_result = mysql_manager.execute_query(amount_query, params)
        total_amount = amount_result[0]['SUM(total_invoice_amount)'] if amount_result else 0

        # Get recent batches
        recent_batches_query = """
            SELECT upload_batch_id, COUNT(*) as invoice_count, 
                   MAX(created_at) as upload_date,
                   SUM(total_invoice_amount) as batch_total
            FROM invoice
            WHERE 1=1
        """
        recent_params = []

        if warehouse_id:
            recent_batches_query += " AND warehouse_id = %s"
            recent_params.append(warehouse_id)
        if company_id:
            recent_batches_query += " AND company_id = %s"
            recent_params.append(company_id)

        recent_batches_query += """
            GROUP BY upload_batch_id 
            ORDER BY MAX(created_at) DESC 
            LIMIT 10
        """

        recent_batches_result = mysql_manager.execute_query(recent_batches_query, recent_params)

        # Format recent batches
        recent_batches = []
        for batch in recent_batches_result:
            recent_batches.append({
                'batch_id': batch['upload_batch_id'],
                'invoice_count': batch['invoice_count'],
                'upload_date': batch['upload_date'].isoformat() if batch['upload_date'] else None,
                'batch_total': float(batch['batch_total']) if batch['batch_total'] else 0.0
            })

        # Get invoices by status
        status_query = """
            SELECT invoice_status, COUNT(*) as count 
            FROM invoice 
            WHERE 1=1
        """
        status_params = []

        if warehouse_id:
            status_query += " AND warehouse_id = %s"
            status_params.append(warehouse_id)
        if company_id:
            status_query += " AND company_id = %s"
            status_params.append(company_id)
        if batch_id:
            status_query += " AND upload_batch_id = %s"
            status_params.append(batch_id)

        status_query += " GROUP BY invoice_status"

        status_result = mysql_manager.execute_query(status_query, status_params)
        status_breakdown = {}
        for result in status_result:
            status_breakdown[result['invoice_status'] or 'Unknown'] = result['count']

        return {
            'total_invoices': total_invoices,
            'unique_orders': unique_orders,
            'total_amount': float(total_amount or 0),
            'recent_batches': recent_batches,
            'status_breakdown': status_breakdown
        }

    except Exception as e:
        print(f"Error getting invoice statistics: {str(e)}")
        return {
            'total_invoices': 0,
            'unique_orders': 0,
            'total_amount': 0.0,
            'recent_batches': [],
            'status_breakdown': {}
        }


def validate_invoice_data(df):
    """
    Validate invoice data before processing

    Args:
        df: DataFrame with invoice data

    Returns:
        tuple: (is_valid, error_messages)
    """
    errors = []

    # Check if dataframe is empty
    if df.empty:
        errors.append("File contains no data")
        return False, errors

    # Check for required columns
    required_cols = ['Invoice #', 'Order #']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {', '.join(missing_cols)}")

    # Check for empty critical fields
    if 'Invoice #' in df.columns:
        empty_invoices = df[df['Invoice #'].isnull() | (df['Invoice #'] == '')].shape[0]
        if empty_invoices > 0:
            errors.append(f"{empty_invoices} rows have empty Invoice # field")

    if 'Order #' in df.columns:
        empty_orders = df[df['Order #'].isnull() | (df['Order #'] == '')].shape[0]
        if empty_orders > 0:
            errors.append(f"{empty_orders} rows have empty Order # field (Sales Order / PSAO number)")

    # Check for numeric fields if they exist
    numeric_fields = ['Total Invoice Amount', 'Quantity', 'Unit Price']
    for field in numeric_fields:
        if field in df.columns:
            try:
                pd.to_numeric(df[field], errors='coerce')
                invalid_values = df[pd.to_numeric(df[field], errors='coerce').isnull() &
                                    df[field].notna() & (df[field] != '')].shape[0]
                if invalid_values > 0:
                    errors.append(f"{invalid_values} rows have invalid {field} values")
            except Exception:
                errors.append(f"Unable to validate {field} column")

    return len(errors) == 0, errors


def get_invoice_batch_details(batch_id):
    """
    Get detailed information about a specific invoice batch

    Args:
        batch_id: The batch ID to get details for

    Returns:
        dict: Batch details including invoices and statistics
    """
    try:
        # Get batch summary
        batch_query = """
            SELECT COUNT(*) as invoice_count,
                   SUM(total_invoice_amount) as batch_total,
                   MIN(created_at) as start_time,
                   MAX(created_at) as end_time,
                   COUNT(DISTINCT potential_order_id) as unique_orders,
                   uploaded_by
            FROM invoice 
            WHERE upload_batch_id = %s
        """

        batch_result = mysql_manager.execute_query(batch_query, (batch_id,))

        if not batch_result or batch_result[0]['invoice_count'] == 0:
            return {
                'found': False,
                'message': 'Batch not found'
            }

        batch_info = batch_result[0]

        # Get invoices in this batch
        invoices_query = """
            SELECT invoice_id, invoice_number, original_order_id, 
                   customer_name, invoice_date, total_invoice_amount,
                   invoice_status, created_at
            FROM invoice 
            WHERE upload_batch_id = %s
            ORDER BY created_at
        """

        invoices_result = mysql_manager.execute_query(invoices_query, (batch_id,))

        # Format invoices
        invoices = []
        for invoice in invoices_result:
            invoices.append({
                'invoice_id': invoice['invoice_id'],
                'invoice_number': invoice['invoice_number'],
                'original_order_id': invoice['original_order_id'],
                'customer_name': invoice['customer_name'],
                'invoice_date': invoice['invoice_date'].isoformat() if invoice['invoice_date'] else None,
                'total_amount': float(invoice['total_invoice_amount']) if invoice['total_invoice_amount'] else 0.0,
                'status': invoice['invoice_status'],
                'processed_at': invoice['created_at'].isoformat()
            })

        # Get error summary if available (this would require storing errors in a separate table)
        # For now, we'll just return the basic info

        return {
            'found': True,
            'batch_id': batch_id,
            'summary': {
                'invoice_count': batch_info['invoice_count'],
                'batch_total': float(batch_info['batch_total']) if batch_info['batch_total'] else 0.0,
                'unique_orders': batch_info['unique_orders'],
                'start_time': batch_info['start_time'].isoformat() if batch_info['start_time'] else None,
                'end_time': batch_info['end_time'].isoformat() if batch_info['end_time'] else None,
                'uploaded_by': batch_info['uploaded_by']
            },
            'invoices': invoices
        }

    except Exception as e:
        print(f"Error getting batch details for {batch_id}: {str(e)}")
        return {
            'found': False,
            'message': f'Error retrieving batch details: {str(e)}'
        }


def get_invoices_by_order(order_id):
    """
    Get all invoices for a specific order

    Args:
        order_id: The original order ID or potential order ID

    Returns:
        list: List of invoices for the order
    """
    try:
        # Try to find by original order ID first
        invoices_query = """
            SELECT i.*, po.status as order_status
            FROM invoice i
            LEFT JOIN potential_order po ON i.potential_order_id = po.potential_order_id
            WHERE i.original_order_id = %s
            ORDER BY i.created_at DESC
        """

        invoices_result = mysql_manager.execute_query(invoices_query, (order_id,))

        # If not found, try by potential order ID
        if not invoices_result:
            try:
                potential_order_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
                invoices_query = """
                    SELECT i.*, po.status as order_status
                    FROM invoice i
                    LEFT JOIN potential_order po ON i.potential_order_id = po.potential_order_id
                    WHERE i.potential_order_id = %s
                    ORDER BY i.created_at DESC
                """
                invoices_result = mysql_manager.execute_query(invoices_query, (potential_order_id,))
            except (ValueError, TypeError):
                pass  # Invalid ID format

        # Format results
        invoices = []
        for invoice_data in invoices_result:
            invoice = {
                'invoice_id': invoice_data['invoice_id'],
                'invoice_number': invoice_data['invoice_number'],
                'original_order_id': invoice_data['original_order_id'],
                'customer_name': invoice_data['customer_name'],
                'invoice_date': invoice_data['invoice_date'].isoformat() if invoice_data['invoice_date'] else None,
                'total_amount': float(invoice_data['total_invoice_amount']) if invoice_data[
                    'total_invoice_amount'] else 0.0,
                'invoice_status': invoice_data['invoice_status'],
                'order_status': invoice_data['order_status'],
                'part_no': invoice_data['part_no'],
                'part_name': invoice_data['part_name'],
                'quantity': invoice_data['quantity'],
                'unit_price': float(invoice_data['unit_price']) if invoice_data['unit_price'] else 0.0,
                'upload_batch_id': invoice_data['upload_batch_id'],
                'created_at': invoice_data['created_at'].isoformat()
            }
            invoices.append(invoice)

        return invoices

    except Exception as e:
        print(f"Error getting invoices for order {order_id}: {str(e)}")
        return []


def cleanup_temporary_files():
    """
    Clean up old temporary files
    """
    try:
        tmp_dir = os.path.join(BASE_DIR, 'tmp')
        if os.path.exists(tmp_dir):
            import time
            current_time = time.time()

            for filename in os.listdir(tmp_dir):
                file_path = os.path.join(tmp_dir, filename)
                if os.path.isfile(file_path):
                    # Remove files older than 1 hour
                    if current_time - os.path.getmtime(file_path) > 3600:
                        try:
                            os.remove(file_path)
                            print(f"Cleaned up old temp file: {filename}")
                        except Exception as e:
                            print(f"Error removing temp file {filename}: {e}")

    except Exception as e:
        print(f"Error during cleanup: {e}")


def get_invoice_trends(warehouse_id=None, company_id=None, days=30):
    """
    Get invoice trends over the specified number of days

    Args:
        warehouse_id: Optional warehouse filter
        company_id: Optional company filter
        days: Number of days to analyze (default 30)

    Returns:
        dict: Trend data
    """
    try:
        # Build query for daily invoice counts
        daily_query = """
            SELECT DATE(created_at) as invoice_date, 
                   COUNT(*) as invoice_count,
                   SUM(total_invoice_amount) as daily_total
            FROM invoice 
            WHERE DATE(created_at) >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        """
        params = [days]

        if warehouse_id:
            daily_query += " AND warehouse_id = %s"
            params.append(warehouse_id)
        if company_id:
            daily_query += " AND company_id = %s"
            params.append(company_id)

        daily_query += " GROUP BY DATE(created_at) ORDER BY invoice_date"

        daily_results = mysql_manager.execute_query(daily_query, params)

        # Format daily data
        daily_trends = []
        for result in daily_results:
            daily_trends.append({
                'date': result['invoice_date'].isoformat(),
                'invoice_count': result['invoice_count'],
                'daily_total': float(result['daily_total']) if result['daily_total'] else 0.0
            })

        # Calculate summary statistics
        if daily_results:
            total_invoices = sum(r['invoice_count'] for r in daily_results)
            total_amount = sum(float(r['daily_total']) if r['daily_total'] else 0.0 for r in daily_results)
            avg_daily_invoices = total_invoices / len(daily_results)
            avg_daily_amount = total_amount / len(daily_results)
        else:
            total_invoices = 0
            total_amount = 0.0
            avg_daily_invoices = 0.0
            avg_daily_amount = 0.0

        return {
            'daily_trends': daily_trends,
            'summary': {
                'period_days': days,
                'total_invoices': total_invoices,
                'total_amount': total_amount,
                'avg_daily_invoices': round(avg_daily_invoices, 2),
                'avg_daily_amount': round(avg_daily_amount, 2)
            }
        }

    except Exception as e:
        print(f"Error getting invoice trends: {str(e)}")
        return {
            'daily_trends': [],
            'summary': {
                'period_days': days,
                'total_invoices': 0,
                'total_amount': 0.0,
                'avg_daily_invoices': 0.0,
                'avg_daily_amount': 0.0
            }
        }