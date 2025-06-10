# -*- encoding: utf-8 -*-
"""
Invoice Upload Service for MySQL
"""

import os
import uuid
import chardet
import pandas as pd
import csv
from io import StringIO
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import db, Warehouse, Company
from ..business import invoice_business

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
    Process the uploaded invoice file and update order statuses

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
            # Try case-insensitive match
            found = False
            for col in df.columns:
                if req_col.lower() == col.lower():
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
            df = df.rename(columns={v: k for k, v in column_mapping.items() if k != v})

        # Start a proper transaction
        try:
            print("Starting database transaction...")

            # Process the dataframe using the business logic
            result = invoice_business.process_invoice_dataframe(
                df, warehouse_id, company_id, user_id
            )

            print(f"Business logic result: {result}")

            # Create error CSV if there are errors
            if result['error_rows']:
                error_df = invoice_business.create_error_dataframe(result['error_rows'])
                if error_df is not None:
                    # Convert to CSV string
                    csv_buffer = StringIO()
                    error_df.to_csv(csv_buffer, index=False)
                    error_csv_content = csv_buffer.getvalue()
                    print(f"Created error CSV with {len(result['error_rows'])} rows")

            # Only commit if we have successful processing
            if result['invoices_processed'] > 0:
                db.session.commit()
                print("Transaction committed successfully")

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
                db.session.rollback()
                print("No invoices were processed successfully")

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

        except Exception as e:
            print(f"Database transaction error: {str(e)}")
            # Rollback the transaction in case of any exception
            db.session.rollback()
            raise e

    except Exception as e:
        print(f"Processing error: {str(e)}")

        return {
            'success': False,
            'msg': f'Error processing file: {str(e)}',
            'invoices_processed': 0,
            'orders_completed': 0,
            'errors': [str(e)]
        }, 400, None

    finally:
        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                print("Cleaned up temporary file")
            except Exception as cleanup_error:
                print(f"Warning: Could not clean up temp file: {cleanup_error}")


def get_invoice_statistics(warehouse_id=None, company_id=None, batch_id=None):
    """
    Get statistics about invoice uploads

    Args:
        warehouse_id: Optional warehouse filter
        company_id: Optional company filter
        batch_id: Optional batch filter

    Returns:
        dict: Statistics about invoices
    """
    try:
        from ..models import Invoice

        query = db.session.query(Invoice)

        if warehouse_id:
            query = query.filter(Invoice.warehouse_id == warehouse_id)
        if company_id:
            query = query.filter(Invoice.company_id == company_id)
        if batch_id:
            query = query.filter(Invoice.upload_batch_id == batch_id)

        total_invoices = query.count()

        # Get unique orders affected
        unique_orders = query.with_entities(Invoice.potential_order_id).distinct().count()

        # Get total amount
        total_amount = query.with_entities(
            db.func.sum(Invoice.total_invoice_amount)
        ).scalar() or 0

        # Get recent batches
        recent_batches = db.session.query(
            Invoice.upload_batch_id,
            db.func.count(Invoice.invoice_id).label('invoice_count'),
            db.func.max(Invoice.created_at).label('upload_date')
        ).group_by(
            Invoice.upload_batch_id
        ).order_by(
            db.func.max(Invoice.created_at).desc()
        ).limit(10).all()

        return {
            'total_invoices': total_invoices,
            'unique_orders': unique_orders,
            'total_amount': float(total_amount),
            'recent_batches': [
                {
                    'batch_id': batch.upload_batch_id,
                    'invoice_count': batch.invoice_count,
                    'upload_date': batch.upload_date.isoformat() if batch.upload_date else None
                }
                for batch in recent_batches
            ]
        }

    except Exception as e:
        print(f"Error getting invoice statistics: {str(e)}")
        return {
            'total_invoices': 0,
            'unique_orders': 0,
            'total_amount': 0,
            'recent_batches': []
        }