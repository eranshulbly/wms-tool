"""
Order Upload Service
"""

import os

from ..models import mysql_manager
from ..business.order_business import process_order_dataframe
from ..business.dealer_business import clear_dealer_cache
from ..utils.upload_utils import (
    make_upload_response, read_upload_file, resolve_required_columns,
    save_temp_file, cleanup_temp_file, create_upload_batch,
)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    """
    Process the uploaded order file within a single MySQL transaction.

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

        df, error = resolve_required_columns(df, ['Sales Order #'])
        if error:
            return {'success': False, 'msg': error, 'processed_count': 0, 'error_count': 0}, 400

        clear_dealer_cache()

        upload_batch_id = create_upload_batch(
            mysql_manager, 'orders', uploaded_file.filename, warehouse_id, company_id, user_id
        )

        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                result = process_order_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id)

                if result['orders_processed'] > 0:
                    cursor.connection.commit()
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
                            (result['orders_processed'], upload_batch_id), fetch=False
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
            result['orders_processed'],
            result['error_rows'],
            upload_batch_id=upload_batch_id,
        )

    except Exception as e:
        print(f"Processing error: {str(e)}")
        cleanup_temp_file(temp_path)
        return {'success': False, 'msg': f'Error processing file: {str(e)}',
                'processed_count': 0, 'error_count': 0}, 400


def validate_order_data(df):
    """
    Validate order data before processing

    Args:
        df: DataFrame with order data

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


def get_upload_statistics(warehouse_id=None, company_id=None):
    """
    Get statistics about order uploads

    Args:
        warehouse_id: Optional warehouse filter
        company_id: Optional company filter

    Returns:
        dict: Statistics about orders
    """
    try:
        # Build base query
        base_query = "SELECT COUNT(*) as count FROM potential_order WHERE 1=1"
        params = []

        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            base_query += " AND company_id = %s"
            params.append(company_id)

        # Get total orders
        total_result = mysql_manager.execute_query(base_query, params)
        total_orders = total_result[0]['count'] if total_result else 0

        # Get orders by status
        status_query = base_query.replace("COUNT(*)", "status, COUNT(*) as count") + " GROUP BY status"
        status_results = mysql_manager.execute_query(status_query, params)

        status_breakdown = {}
        for result in status_results:
            status_breakdown[result['status']] = result['count']

        # Get recent uploads (last 7 days)
        recent_query = base_query + " AND DATE(created_at) >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
        recent_result = mysql_manager.execute_query(recent_query, params)
        recent_orders = recent_result[0]['count'] if recent_result else 0

        # Get total products
        product_query = """
            SELECT COUNT(*) as count FROM potential_order_product pop
            JOIN potential_order po ON pop.potential_order_id = po.potential_order_id
            WHERE 1=1
        """
        product_params = []

        if warehouse_id:
            product_query += " AND po.warehouse_id = %s"
            product_params.append(warehouse_id)

        if company_id:
            product_query += " AND po.company_id = %s"
            product_params.append(company_id)

        product_result = mysql_manager.execute_query(product_query, product_params)
        total_products = product_result[0]['count'] if product_result else 0

        return {
            'total_orders': total_orders,
            'total_products': total_products,
            'recent_orders': recent_orders,
            'status_breakdown': status_breakdown
        }

    except Exception as e:
        print(f"Error getting upload statistics: {str(e)}")
        return {
            'total_orders': 0,
            'total_products': 0,
            'recent_orders': 0,
            'status_breakdown': {}
        }


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