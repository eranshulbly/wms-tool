# -*- encoding: utf-8 -*-
"""
Shared utilities for file upload processing.

To add support for a new upload type:
  1. Build error_rows in your business logic as a list of dicts with 'order_id', 'name', 'reason'.
  2. Call make_upload_response(...) in your service layer.
  3. That's it — error Excel generation and response shaping are handled here.
"""

import base64
import csv
import os
import uuid
from io import BytesIO

import chardet
import pandas as pd
from werkzeug.utils import secure_filename


# ---------------------------------------------------------------------------
# File-reading helpers (shared by order and invoice upload services)
# ---------------------------------------------------------------------------

def read_upload_file(temp_path, file_extension):
    """
    Parse an uploaded file into a DataFrame regardless of encoding/format.

    Args:
        temp_path: path to the saved temp file
        file_extension: '.csv', '.xls', or '.xlsx'

    Returns:
        pd.DataFrame

    Raises:
        Exception on unrecoverable parse failure
    """
    if file_extension in ('.xls', '.xlsx'):
        try:
            return pd.read_excel(temp_path, dtype=str)
        except Exception as e:
            raise Exception(f"Failed to parse Excel file: {str(e)}")

    if file_extension == '.csv':
        with open(temp_path, 'rb') as f:
            encoding = chardet.detect(f.read())['encoding'] or 'utf-8'
        return _read_csv(temp_path, encoding)

    raise Exception("Unsupported file format. Please upload a CSV or Excel file.")


def _read_csv(temp_path, encoding):
    """Try progressively looser strategies to parse a CSV file."""
    if encoding and 'utf-16' in encoding.lower():
        try:
            return pd.read_csv(temp_path, encoding='utf-16', sep='\t',
                               engine='python', dtype=str, index_col=False,
                               on_bad_lines='warn')
        except Exception:
            pass

    try:
        return pd.read_csv(temp_path, encoding=encoding, sep=',',
                           quotechar='"', doublequote=True, escapechar='\\',
                           engine='python', quoting=csv.QUOTE_MINIMAL,
                           on_bad_lines='warn', dtype=str)
    except Exception:
        pass

    try:
        return pd.read_csv(temp_path, encoding='utf-16', sep=None,
                           engine='python', dtype=str, index_col=False,
                           on_bad_lines='skip')
    except Exception:
        pass

    try:
        return pd.read_csv(temp_path, encoding='cp1252', sep=None,
                           engine='python', dtype=str, on_bad_lines='skip')
    except Exception as e:
        raise Exception(f"All CSV parsing strategies failed: {str(e)}")


def resolve_required_columns(df, required_columns):
    """
    Fuzzy-match required column names (exact → case-insensitive → partial).

    Returns:
        (renamed_df, error_msg)  — error_msg is None on success
    """
    mapping = {}
    missing = []

    for req in required_columns:
        match = None
        for col in df.columns:
            if req == col:
                match = col
                break
        if not match:
            for col in df.columns:
                if req.lower() == col.lower():
                    match = col
                    break
        if not match:
            for col in df.columns:
                if req.lower().replace(' ', '').replace('#', '') in \
                        col.lower().replace(' ', '').replace('#', ''):
                    match = col
                    break
        if match:
            mapping[req] = match
        else:
            missing.append(req)

    if missing:
        available = ', '.join(df.columns)
        return df, f"Missing required columns: {', '.join(missing)}. Available: {available}"

    rename = {v: k for k, v in mapping.items() if k != v}
    if rename:
        df = df.rename(columns=rename)
    return df, None


def save_temp_file(uploaded_file, base_dir):
    """
    Save an uploaded file to a tmp sub-directory.

    Returns:
        (temp_path, file_extension)
    """
    from werkzeug.utils import secure_filename
    filename = secure_filename(uploaded_file.filename)
    file_extension = os.path.splitext(filename)[1].lower()
    tmp_dir = os.path.join(base_dir, 'tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    temp_path = os.path.join(tmp_dir, f"{uuid.uuid4()}{file_extension}")
    uploaded_file.save(temp_path)
    return temp_path, file_extension


def cleanup_temp_file(temp_path):
    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass


def create_upload_batch(mysql_manager, upload_type, filename, warehouse_id, company_id, user_id):
    """Insert an upload_batches row and return its id (or None on failure)."""
    try:
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO upload_batches (upload_type, filename, warehouse_id, company_id, uploaded_by)
                   VALUES (%s, %s, %s, %s, %s)""",
                (upload_type, filename, warehouse_id, company_id, user_id)
            )
            return cursor.lastrowid
    except Exception as e:
        print(f"Warning: Could not create upload batch record: {e}")
        return None


def generate_error_excel(error_rows):
    """
    Build a 3-column error Excel (Order ID | Name | Reason) and return as base64 string.

    Args:
        error_rows: list of dicts, each with 'order_id', 'name', 'reason'

    Returns:
        base64-encoded xlsx string
    """
    rows = [
        {
            'Order ID': r.get('order_id', ''),
            'Name':     r.get('name', ''),
            'Reason':   r.get('reason', ''),
        }
        for r in error_rows
    ]
    df = pd.DataFrame(rows)
    buf = BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def make_upload_response(processed_count, error_rows, **extra):
    """
    Build a standardized upload response dict.

    Args:
        processed_count: number of successfully processed rows
        error_rows:      list of structured error dicts (order_id, name, reason)
        **extra:         any additional fields to merge in (e.g. orders_completed, upload_batch_id)

    Returns:
        (response_dict, http_status_code)
    """
    error_count = len(error_rows)
    success = processed_count > 0

    response = {
        'success': success,
        'processed_count': processed_count,
        'error_count': error_count,
        **extra,
    }

    if error_count > 1:
        response['error_report'] = generate_error_excel(error_rows)

    if not success:
        response['msg'] = 'No rows could be processed. Download the error report for details.'

    status_code = 200 if success else 400
    return response, status_code
