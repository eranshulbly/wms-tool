# -*- encoding: utf-8 -*-
"""
Order Upload Service
"""

import os
import uuid
import pandas as pd
from werkzeug.utils import secure_filename
from flask import current_app

from ..models import Warehouse, Company
from ..business import order_business, dealer_business, product_business

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

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
        # Save the file temporarily
        temp_path = os.path.join(BASE_DIR, '/tmp', f"{uuid.uuid4()}{file_extension}")
        uploaded_file.save(temp_path)

        # Read the file based on its extension
        if file_extension == '.csv':
            df = pd.read_csv(temp_path, encoding='cp1252')
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