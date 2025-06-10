# -*- encoding: utf-8 -*-
"""
FIXED: Order Upload Service for MySQL
"""

import os
import uuid
import chardet
import pandas as pd
import csv
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import db, Warehouse, Company
from ..business import order_business, dealer_business, product_business

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    """
    FIXED: Process the uploaded order file within a single database transaction

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

    print(f"Processing upload: {filename}, extension: {file_extension}")

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

        # Read the file based on its extension with more robust error handling
        if file_extension == '.csv':
            try:
                # Use more robust CSV parsing options
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
                print("Successfully read CSV file")
            except Exception as e:
                print(f"First CSV attempt failed: {str(e)}")
                # Fallback to a different parser if the first approach fails
                try:
                    df = pd.read_csv(
                        temp_path,
                        encoding='cp1252',
                        sep=None,
                        engine='python',
                        quoting=csv.QUOTE_NONE,
                        escapechar='\\',
                        dtype=str
                    )
                    print("Successfully read CSV with fallback method")
                except Exception as inner_e:
                    raise Exception(f"Failed to parse CSV: {str(e)}. Additional info: {str(inner_e)}")

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

        # Log the DataFrame structure for debugging
        print(f"DataFrame columns: {df.columns.tolist()}")
        print(f"DataFrame shape: {df.shape}")
        print(f"First few rows:\n{df.head()}")

        # Clear caches to ensure fresh data
        dealer_business.clear_dealer_cache()
        product_business.clear_product_cache()

        # FIXED: Start a proper transaction
        try:
            print("Starting database transaction...")

            # Process the dataframe using the business logic
            result = order_business.process_order_dataframe(
                df, warehouse_id, company_id, user_id
            )

            print(f"Business logic result: {result}")

            # FIXED: Only commit if we have successful processing
            if result['orders_processed'] > 0 or result['products_processed'] > 0:
                db.session.commit()
                print("Transaction committed successfully")
            else:
                db.session.rollback()
                print("No data processed, rolling back transaction")
                return {
                    'success': False,
                    'msg': 'No valid data found in the uploaded file',
                    'orders_processed': 0,
                    'products_processed': 0,
                    'errors': result['errors']
                }, 400

            # Clean up the temporary file
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
                print("Cleaned up temporary file")

            return {
                'success': True,
                'msg': f'Orders uploaded successfully. Processed {result["orders_processed"]} orders and {result["products_processed"]} products.',
                'orders_processed': result['orders_processed'],
                'products_processed': result['products_processed'],
                'errors': result['errors']
            }, 200

        except Exception as e:
            print(f"Database transaction error: {str(e)}")
            # Rollback the transaction in case of any exception
            db.session.rollback()
            raise e

    except Exception as e:
        print(f"Processing error: {str(e)}")

        # Clean up temp file if it exists
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

        return {
            'success': False,
            'msg': f'Error processing file: {str(e)}',
            'orders_processed': orders_processed,
            'products_processed': products_processed,
            'errors': [str(e)]
        }, 400