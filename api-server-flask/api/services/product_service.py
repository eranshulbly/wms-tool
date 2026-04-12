# -*- encoding: utf-8 -*-
"""
Product Upload Service for MySQL.
"""

import os

from ..models import mysql_manager
from ..business.product_upload_business import process_product_upload_dataframe
from ..utils.upload_utils import (
    make_upload_response, read_upload_file, resolve_required_columns,
    save_temp_file, cleanup_temp_file, create_upload_batch,
)

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def process_product_upload(uploaded_file, company_id, user_id):
    """
    Parse the uploaded file and link products to orders.

    Returns:
        tuple: (result_dict, http_status_code)
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

        df, error = resolve_required_columns(df, ['Order #', 'Part #', 'Part Description', 'Reserved Qty'])
        if error:
            return {'success': False, 'msg': error, 'processed_count': 0, 'error_count': 0}, 400

        upload_batch_id = create_upload_batch(
            mysql_manager, 'products', uploaded_file.filename, None, company_id, user_id
        )

        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                result = process_product_upload_dataframe(df, company_id, user_id, upload_batch_id)

                if result['products_processed'] > 0:
                    cursor.connection.commit()
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
                            (result['products_processed'], upload_batch_id), fetch=False
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
            result['products_processed'],
            result['error_rows'],
            orders_updated=result['orders_updated'],
            upload_batch_id=upload_batch_id,
        )

    except Exception as e:
        print(f"Product upload error: {str(e)}")
        cleanup_temp_file(temp_path)
        return {'success': False, 'msg': f'Error processing file: {str(e)}',
                'processed_count': 0, 'error_count': 0}, 400
