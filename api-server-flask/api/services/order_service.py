# -*- encoding: utf-8 -*-
"""
Order Upload Service
"""

import os
import uuid
import chardet
import pandas as pd
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import Warehouse, Company
from ..business import order_business, dealer_business, product_business

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

# Update the process_order_upload function in api/services/order_service.py

def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    """
    Process the uploaded order file

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

    # Initialize tracking variables
    orders_processed = 0
    products_processed = 0
    errors = []

    # Verify warehouse and company exist
    try:
        warehouse = Warehouse.get_by_id(warehouse_id)
        company = Company.get_by_id(company_id)
    except Exception as e:
        return {
            'success': False,
            'msg': 'Invalid warehouse or company ID',
            'orders_processed': 0,
            'products_processed': 0,
            'errors': [str(e)]
        }, 400

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

        with open(temp_path, 'rb') as f:
            result = chardet.detect(f.read())
            encoding = result['encoding']

        # Read the file based on its extension with more robust error handling
        if file_extension == '.csv':
            try:
                import csv
                # Use more robust CSV parsing options

                df = pd.read_csv(
                    temp_path,
                    encoding=encoding,
                    sep=",",
                    quotechar='"',  # Use double quotes for quoting
                    doublequote=True,  # Handle "" as an escaped "
                    escapechar='\\',  # Use backslash as escape character
                    engine='python',  # Use more flexible engine
                    quoting=csv.QUOTE_MINIMAL,  # Only quote fields when necessary
                    on_bad_lines='warn',  # Just warn about bad lines (pandas 1.3+)
                    dtype={
                        'Part #': str,  # Force these columns to be strings
                        'Part Description': str,  # to prevent conversion attempts
                        'Order #': str,
                        'Account Name': str
                    }
                )
            except Exception as e:
                # Fallback to a different parser if the first approach fails
                try:
                    # Try with the C engine but with very permissive settings
                    df = pd.read_csv(
                        temp_path,
                        encoding='cp1252',
                        sep=None,  # Try to detect the separator
                        engine='python',
                        quoting=csv.QUOTE_NONE,
                        escapechar='\\'
                    )
                except Exception as inner_e:
                    raise Exception(f"Failed to parse CSV: {str(e)}. Additional info: {str(inner_e)}")
        elif file_extension in ['.xls', '.xlsx']:
            df = pd.read_excel(temp_path)
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

        # Process the dataframe
        result = order_business.process_order_dataframe(
            df, warehouse_id, company_id, user_id
        )

        # Clean up the temporary file
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

        return {
            'success': True,
            'msg': 'Orders uploaded successfully',
            'orders_processed': result['orders_processed'],
            'products_processed': result['products_processed'],
            'errors': result['errors']
        }, 200

    except Exception as e:
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