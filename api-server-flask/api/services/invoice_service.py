# -*- encoding: utf-8 -*-
"""
Invoice Upload Service for MySQL - Complete MySQL Implementation
"""

import os
import uuid
import chardet
import pandas as pd
import csv
from io import StringIO
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import Warehouse, Company, Invoice, mysql_manager
from ..business.invoice_business import process_invoice_dataframe, create_error_dataframe

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
        elif 'status' in error_lower and 'not' in error_lower and 'dispatch ready' in error_lower:
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
        summary_parts.append(f"{error_types['wrong_status']} orders were not in 'Dispatch Ready' status")

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
    Process the uploaded invoice file and update order statuses using MySQL

    Args:
        uploaded_file: The uploaded file object
        warehouse_id: The ID of the warehouse
        company_id: The ID of the company
        user_id: The ID of the user who uploaded the file

    Returns:
        tuple: (result_dict, status_code, error_csv_content)
    """
    # Create a secure filename and temporary save location
    filename = secure_filename(uploaded_file.filename)
    file_extension = os.path.splitext(filename)[1].lower()

    print(f"Processing invoice upload: {filename}, extension: {file_extension}")

    # Initialize tracking variables
    invoices_processed = 0
    orders_completed = 0
    errors = []
    error_csv_content = None

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
                # First attempt - standard CSV parsing
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
                    dtype=str  # Read everything as strings initially
                )
                print("Successfully read CSV file with standard method")
            except Exception as e:
                print(f"Standard CSV parsing failed: {str(e)}")
                # Fallback method - clean the file first
                try:
                    # Read the raw file and clean headers
                    with open(temp_path, 'r', encoding=encoding, errors='ignore') as f:
                        content = f.read()

                    # Clean the content - remove newlines from headers and fix common issues
                    lines = content.split('\n')
                    if lines:
                        # Clean the header line - remove newlines and extra whitespace
                        header_line = lines[0].replace('\r', '').replace('\n', '').strip()
                        cleaned_lines = [header_line] + lines[1:]
                        cleaned_content = '\n'.join(cleaned_lines)

                        # Write cleaned content to a temporary file
                        import tempfile
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                                         encoding='utf-8') as temp_csv:
                            temp_csv.write(cleaned_content)
                            temp_csv_path = temp_csv.name

                        # Try parsing the cleaned file
                        df = pd.read_csv(
                            temp_csv_path,
                            encoding='utf-8',
                            sep=',',
                            engine='python',
                            dtype=str,
                            on_bad_lines='skip'  # Skip problematic lines
                        )

                        # Clean up temporary file
                        os.remove(temp_csv_path)
                        print("Successfully read CSV with cleaned headers")
                    else:
                        raise Exception("CSV file appears to be empty")

                except Exception as inner_e:
                    print(f"Cleaned CSV parsing also failed: {str(inner_e)}")
                    # Final fallback - try with different encoding and separators
                    try:
                        df = pd.read_csv(
                            temp_path,
                            encoding='cp1252',
                            sep=None,
                            engine='python',
                            dtype=str,
                            on_bad_lines='skip'
                        )
                        print("Successfully read CSV with fallback encoding")
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
                'invoices_processed': 0,
                'orders_completed': 0,
                'errors': ['Unsupported file format']
            }, 400, None

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
        required_columns = ['Invoice Number', 'Narration']
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
                    if req_col.lower().replace(' ', '') in col.lower().replace(' ', ''):
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
                'invoices_processed': 0,
                'orders_completed': 0,
                'errors': [f'Missing required columns: {", ".join(missing_columns)}']
            }, 400, None

        # Rename columns to standard names if mapping was needed
        if column_mapping:
            reverse_mapping = {v: k for k, v in column_mapping.items() if k != v}
            if reverse_mapping:
                df = df.rename(columns=reverse_mapping)
                print(f"Renamed columns: {reverse_mapping}")

        # Use MySQL transaction context manager for proper transaction handling
        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                print("Starting MySQL transaction for invoice processing...")

                # Process the dataframe using the business logic
                result = process_invoice_dataframe(
                    df, warehouse_id, company_id, user_id
                )

                print(f"Business logic result: {result}")

                # Create error CSV if there are errors
                if result['error_rows']:
                    error_df = create_error_dataframe(result['error_rows'])
                    if error_df is not None:
                        # Convert to CSV string
                        csv_buffer = StringIO()
                        error_df.to_csv(csv_buffer, index=False)
                        error_csv_content = csv_buffer.getvalue()
                        print(f"Created error CSV with {len(result['error_rows'])} rows")

                # Check if we have successful processing
                if result['invoices_processed'] > 0:
                    # Commit the transaction
                    cursor.connection.commit()
                    print("MySQL transaction committed successfully")

                    # Clean up the temporary file
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                        print("Cleaned up temporary file")

                    success_msg = f'Invoice upload completed successfully. '
                    success_msg += f'Processed {result["invoices_processed"]} invoices, '
                    success_msg += f'completed {result["orders_completed"]} orders.'

                    if result['errors']:
                        success_msg += f' {len(result["errors"])} errors occurred (see error file).'

                    return {
                        'success': True,
                        'msg': success_msg,
                        'invoices_processed': result['invoices_processed'],
                        'orders_completed': result['orders_completed'],
                        'errors': result['errors'],
                        'upload_batch_id': result['upload_batch_id'],
                        'has_errors': len(result['errors']) > 0
                    }, 200, error_csv_content
                else:
                    # Rollback the transaction
                    cursor.connection.rollback()
                    print("No invoices were processed successfully, rolling back MySQL transaction")

                    # Create a meaningful error message based on the types of errors
                    error_summary = analyze_errors(result['errors'])

                    # Always return the error CSV for download when no data is processed
                    return {
                        'success': False,
                        'msg': f'No invoices could be processed. {error_summary}',
                        'invoices_processed': 0,
                        'orders_completed': 0,
                        'errors': result['errors'],
                        'upload_batch_id': result['upload_batch_id'],
                        'has_errors': True,
                        'total_rows': len(df),
                        'error_rows': len(result['error_rows'])
                    }, 400, error_csv_content

        except Exception as db_error:
            print(f"MySQL transaction error: {str(db_error)}")
            # Transaction will auto-rollback due to context manager
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
            'invoices_processed': 0,
            'orders_completed': 0,
            'errors': [str(e)]
        }, 400, None


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
    required_cols = ['Invoice Number', 'Narration']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        errors.append(f"Missing required columns: {', '.join(missing_cols)}")

    # Check for empty critical fields
    if 'Invoice Number' in df.columns:
        empty_invoices = df[df['Invoice Number'].isnull() | (df['Invoice Number'] == '')].shape[0]
        if empty_invoices > 0:
            errors.append(f"{empty_invoices} rows have empty Invoice Number field")

    if 'Narration' in df.columns:
        empty_narrations = df[df['Narration'].isnull() | (df['Narration'] == '')].shape[0]
        if empty_narrations > 0:
            errors.append(f"{empty_narrations} rows have empty Narration field (contains Order ID)")

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