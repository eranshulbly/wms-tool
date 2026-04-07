"""
Order Upload Service
"""

import os
import uuid
import chardet
import pandas as pd
import csv
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import Warehouse, Company, mysql_manager
from ..business.order_business import process_order_dataframe
from ..business.dealer_business import clear_dealer_cache
BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    """
    Process the uploaded order file within a single MySQL transaction

    Args:
        uploaded_file: The uploaded file object
        warehouse_id: The ID of the warehouse
        company_id: The ID of the company
        user_id: The ID of the user who uploaded the file

    Returns:
        tuple: (result_dict, status_code)
    """
    # Create a secure filename and temporary save location
    filename = secure_filename(uploaded_file.filename)
    file_extension = os.path.splitext(filename)[1].lower()

    print(f"Processing order upload: {filename}, extension: {file_extension}")

    # Initialize tracking variables
    orders_processed = 0
    products_processed = 0
    errors = []

    # Save and process the file
    temp_path = None

    try:
        # Create tmp directory if it doesn't exist
        tmp_dir = os.path.join(BASE_DIR, 'tmp')
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

        # Save the file temporarily
        temp_path = os.path.join(tmp_dir, f"{uuid.uuid4()}{file_extension}")
        uploaded_file.save(temp_path)
        print(f"Saved file to: {temp_path}")

        # Detect encoding
        with open(temp_path, 'rb') as f:
            result = chardet.detect(f.read())
            encoding = result['encoding'] or 'utf-8'

        print(f"Detected encoding: {encoding}")

        # Read the file based on its extension with robust error handling
        if file_extension == '.csv':
            try:
                # UTF-16 files (new format: tab-separated, UTF-16 LE with BOM)
                if encoding and 'utf-16' in encoding.lower():
                    df = pd.read_csv(
                        temp_path,
                        encoding='utf-16',
                        sep='\t',
                        engine='python',
                        dtype=str,
                        index_col=False,
                        on_bad_lines='warn'
                    )
                    print("Successfully read CSV file as UTF-16 tab-separated")
                else:
                    # Legacy format: comma-separated
                    df = pd.read_csv(
                        temp_path,
                        encoding=encoding,
                        sep=",",
                        quotechar='"',
                        doublequote=True,
                        escapechar='\\',
                        engine='python',
                        quoting=csv.QUOTE_MINIMAL,
                        on_bad_lines='warn',
                        dtype=str
                    )
                    print("Successfully read CSV file with standard method")
            except Exception as e:
                print(f"Primary CSV parsing failed: {str(e)}")
                # Fallback: auto-detect separator
                try:
                    df = pd.read_csv(
                        temp_path,
                        encoding='utf-16',
                        sep=None,
                        engine='python',
                        dtype=str,
                        index_col=False,
                        on_bad_lines='skip'
                    )
                    print("Successfully read CSV with UTF-16 auto-separator fallback")
                except Exception as inner_e:
                    print(f"UTF-16 fallback failed: {str(inner_e)}")
                    try:
                        df = pd.read_csv(
                            temp_path,
                            encoding='cp1252',
                            sep=None,
                            engine='python',
                            dtype=str,
                            on_bad_lines='skip'
                        )
                        print("Successfully read CSV with cp1252 fallback")
                    except Exception as final_e:
                        raise Exception(
                            f"All CSV parsing methods failed. Original error: {str(e)}. Final error: {str(final_e)}")

        elif file_extension in ['.xls', '.xlsx']:
            try:
                df = pd.read_excel(temp_path, dtype=str)
                print("Successfully read Excel file")
            except Exception as e:
                raise Exception(f"Failed to parse Excel file: {str(e)}")
        else:
            return {
                'success': False,
                'msg': 'Unsupported file format. Please upload a CSV or Excel file.',
                'orders_processed': 0,
                'products_processed': 0,
                'errors': ['Unsupported file format']
            }, 400

        # After parsing, clean up the dataframe
        # Remove completely empty rows
        df = df.dropna(how='all')

        # Clean column names - remove newlines, extra spaces, and normalize
        df.columns = df.columns.str.replace('\n', ' ').str.replace('\r', ' ').str.strip()

        # Log the DataFrame structure for debugging
        print(f"DataFrame columns after cleaning: {df.columns.tolist()}")
        print(f"DataFrame shape: {df.shape}")
        print(f"First few rows:\n{df.head()}")

        # Validate required columns with fuzzy matching
        required_columns = ['Sales Order #']
        missing_columns = []
        column_mapping = {}

        for req_col in required_columns:
            # Try exact match first
            found = False
            for col in df.columns:
                if req_col == col:
                    column_mapping[req_col] = col
                    found = True
                    break

            # If not found, try case-insensitive match
            if not found:
                for col in df.columns:
                    if req_col.lower() == col.lower():
                        column_mapping[req_col] = col
                        found = True
                        break

            # If still not found, try partial matching
            if not found:
                for col in df.columns:
                    if req_col.lower().replace(' ', '').replace('#', '') in col.lower().replace(' ', '').replace('#',
                                                                                                                 ''):
                        column_mapping[req_col] = col
                        found = True
                        break

            if not found:
                missing_columns.append(req_col)

        if missing_columns:
            available_columns = list(df.columns)
            return {
                'success': False,
                'msg': f'Missing required columns: {", ".join(missing_columns)}. Available columns: {", ".join(available_columns)}',
                'orders_processed': 0,
                'products_processed': 0,
                'errors': [f'Missing required columns: {", ".join(missing_columns)}']
            }, 400

        # Rename columns to standard names if mapping was needed
        if column_mapping:
            reverse_mapping = {v: k for k, v in column_mapping.items() if k != v}
            if reverse_mapping:
                df = df.rename(columns=reverse_mapping)
                print(f"Renamed columns: {reverse_mapping}")

        # Clear caches to ensure fresh data
        clear_dealer_cache()

        # Create upload batch record before processing
        upload_batch_id = None
        try:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO upload_batches (upload_type, filename, warehouse_id, company_id, uploaded_by)
                       VALUES (%s, %s, %s, %s, %s)""",
                    ('orders', filename, warehouse_id, company_id, user_id)
                )
                upload_batch_id = cursor.lastrowid
            print(f"Created upload batch record: {upload_batch_id}")
        except Exception as e:
            print(f"Warning: Could not create upload batch record: {e}")

        # Use MySQL transaction context manager for proper transaction handling
        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                print("Starting MySQL transaction for order processing...")

                # Process the dataframe using the business logic
                result = process_order_dataframe(
                    df, warehouse_id, company_id, user_id, upload_batch_id
                )

                print(f"Business logic result: {result}")

                # Check if we have successful processing
                if result['orders_processed'] > 0 or result['products_processed'] > 0:
                    cursor.connection.commit()
                    print("MySQL transaction committed successfully")

                    # Update batch record count
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
                            (result['orders_processed'], upload_batch_id), fetch=False
                        )

                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)

                    return {
                        'success': True,
                        'msg': f'Orders uploaded successfully. Processed {result["orders_processed"]} orders.',
                        'orders_processed': result['orders_processed'],
                        'errors': result['errors'],
                        'upload_batch_id': upload_batch_id
                    }, 200
                else:
                    cursor.connection.rollback()
                    print("No data processed, rolling back MySQL transaction")

                    # Delete the batch record since nothing was saved
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False
                        )

                    return {
                        'success': False,
                        'msg': 'No valid data found in the uploaded file. Please check the file format and required columns.',
                        'orders_processed': 0,
                        'products_processed': 0,
                        'errors': result['errors']
                    }, 400

        except Exception as db_error:
            print(f"MySQL transaction error: {str(db_error)}")
            if upload_batch_id:
                try:
                    mysql_manager.execute_query(
                        "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False
                    )
                except Exception:
                    pass
            raise db_error

    except Exception as e:
        print(f"Processing error: {str(e)}")

        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                print("Cleaned up temporary file after error")
            except Exception as cleanup_error:
                print(f"Warning: Could not clean up temp file: {cleanup_error}")

        return {
            'success': False,
            'msg': f'Error processing file: {str(e)}',
            'orders_processed': 0,
            'products_processed': 0,
            'errors': [str(e)]
        }, 400


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