# -*- encoding: utf-8 -*-
"""
Invoice Business Logic for MySQL
"""
from datetime import datetime
from ..models import (
    PotentialOrder,OrderState, OrderStateHistory, Invoice
)


def process_invoice_dataframe(df, warehouse_id, company_id, user_id):
    """
    Process a dataframe of invoice data and update order statuses - MySQL implementation

    Args:
        df: Pandas DataFrame with invoice data
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: ID of the user processing the invoices

    Returns:
        dict: Processing results with success and error data
    """
    import uuid

    invoices_processed = 0
    orders_completed = 0
    errors = []
    error_rows = []
    upload_batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    print(f"Processing DataFrame with {len(df)} rows for batch {upload_batch_id}")
    print(f"DataFrame columns: {df.columns.tolist()}")

    # Track processed orders to avoid duplicate updates
    processed_orders = set()

    # Process each row in the dataframe
    for index, row in df.iterrows():
        try:
            print(f"Processing row {index}: {dict(row)}")

            # Extract critical data
            narration = str(row.get('Narration', '')).strip()
            original_order_id = narration  # The narration contains the original order ID
            invoice_number = str(row.get('Invoice Number', ''))

            # Skip rows with missing critical data
            if not original_order_id or not invoice_number:
                error_msg = f"Row {index}: Missing Invoice Number or Narration (Original Order ID)"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            print(f"Row {index}: Processing invoice {invoice_number} for order {original_order_id}")

            # Find the corresponding potential order
            potential_order = find_potential_order_by_original_id(
                original_order_id, warehouse_id, company_id
            )

            if not potential_order:
                error_msg = f"Row {index}: No matching order found for Original Order ID: {original_order_id}"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            # Check if order is in "Dispatch Ready" status
            if potential_order.status != 'Dispatch Ready':
                error_msg = f"Row {index}: Order {original_order_id} is in '{potential_order.status}' status, not 'Dispatch Ready'"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            # Create invoice record
            try:
                invoice = create_invoice_from_row(
                    row, potential_order.potential_order_id, warehouse_id,
                    company_id, user_id, upload_batch_id
                )
                invoice.save()
                invoices_processed += 1
                print(f"Row {index}: Created invoice record for {invoice_number}")

                # Update order status to completed (only once per order)
                if potential_order.potential_order_id not in processed_orders:
                    update_order_to_completed(potential_order, user_id)
                    processed_orders.add(potential_order.potential_order_id)
                    orders_completed += 1
                    print(f"Row {index}: Updated order {original_order_id} to Completed status")

            except Exception as e:
                error_msg = f"Row {index}: Error creating invoice record: {str(e)}"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

        except Exception as e:
            error_msg = f"Row {index}: Unexpected error: {str(e)}"
            errors.append(error_msg)
            error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
            print(f"Row {index}: Unexpected error: {str(e)}")
            continue

    print(
        f"Processing complete: {invoices_processed} invoices, {orders_completed} orders completed, {len(errors)} errors")

    return {
        'invoices_processed': invoices_processed,
        'orders_completed': orders_completed,
        'errors': errors,
        'error_rows': error_rows,
        'upload_batch_id': upload_batch_id
    }


def find_potential_order_by_original_id(original_order_id, warehouse_id, company_id):
    """
    Find a potential order by its original order ID - MySQL implementation

    Args:
        original_order_id: The original order ID from narration
        warehouse_id: Warehouse ID filter
        company_id: Company ID filter

    Returns:
        PotentialOrder: Found order or None
    """
    try:
        return PotentialOrder.find_by_original_order_id(original_order_id, warehouse_id, company_id)
    except Exception as e:
        print(f"Error finding order for {original_order_id}: {str(e)}")
        return None


def create_invoice_from_row(row, potential_order_id, warehouse_id, company_id, user_id, upload_batch_id):
    """
    Create an Invoice object from a DataFrame row - MySQL implementation with proper NaN handling

    Args:
        row: DataFrame row with invoice data
        potential_order_id: Associated potential order ID
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: User who uploaded
        upload_batch_id: Batch identifier

    Returns:
        Invoice: Created invoice object
    """
    from decimal import Decimal, InvalidOperation
    import pandas as pd
    import numpy as np

    current_time = datetime.utcnow()

    # Helper function to safely convert to decimal
    def safe_decimal(value, default=None):
        if value is None or value == '' or str(value).strip() == '' or pd.isna(value) or (
                isinstance(value, float) and np.isnan(value)):
            return default
        try:
            # Convert pandas/numpy types to string first
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return default
            return Decimal(str_value)
        except (InvalidOperation, ValueError, TypeError):
            return default

    # Helper function to safely convert to integer
    def safe_int(value, default=None):
        if value is None or value == '' or str(value).strip() == '' or pd.isna(value) or (
                isinstance(value, float) and np.isnan(value)):
            return default
        try:
            # Convert pandas/numpy types to string first
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return default
            # Handle float values that need to be converted to int
            if '.' in str_value:
                return int(float(str_value))
            return int(str_value)
        except (ValueError, TypeError):
            return default

    # Helper function to safely convert to string
    def safe_string(value, default='', max_length=None):
        if value is None or pd.isna(value) or (isinstance(value, float) and np.isnan(value)):
            return default
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null']:
                return default
            # Truncate if max_length is specified
            if max_length and len(str_value) > max_length:
                return str_value[:max_length]
            return str_value
        except (TypeError, AttributeError):
            return default

    # Helper function to safely parse dates
    def safe_date(value):
        if value is None or value == '' or pd.isna(value) or (isinstance(value, float) and np.isnan(value)):
            return None
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return None

            if isinstance(value, str):
                # Try different date formats
                date_formats = ['%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S']
                for fmt in date_formats:
                    try:
                        return datetime.strptime(str_value, fmt)
                    except ValueError:
                        continue
                # If none work, try pandas datetime parsing
                try:
                    parsed_date = pd.to_datetime(str_value, errors='coerce')
                    if pd.isna(parsed_date):
                        return None
                    return parsed_date.to_pydatetime()
                except:
                    return None
            elif hasattr(value, 'year'):  # Already a datetime object
                return value
            else:
                return None
        except Exception:
            return None

    # Helper function to safely get row value
    def safe_get(row, key, default=None):
        try:
            value = row.get(key, default)
            if pd.isna(value) or (isinstance(value, float) and np.isnan(value)):
                return default
            return value
        except:
            return default

    invoice = Invoice(
        # Foreign keys
        potential_order_id=potential_order_id,
        warehouse_id=warehouse_id,
        company_id=company_id,

        # Invoice identification
        invoice_number=safe_string(safe_get(row, 'Invoice Number'), ''),
        dealer_code=safe_string(safe_get(row, 'Dealer Code'), ''),
        original_order_id=safe_string(safe_get(row, 'Narration'), ''),

        # Customer information
        customer_name=safe_string(safe_get(row, 'Customer Name'), '', 500),  # Truncate to field length
        customer_code=safe_string(safe_get(row, 'Customer Code'), ''),
        customer_category=safe_string(safe_get(row, 'Customer Category'), ''),

        # Invoice details
        invoice_date=safe_date(safe_get(row, 'Invoice Date')),
        invoice_status=safe_string(safe_get(row, 'Invoice Status'), ''),
        invoice_type=safe_string(safe_get(row, 'Invoice Type'), ''),
        invoice_format=safe_string(safe_get(row, 'Invoice Format'), ''),

        # Product information
        part_no=safe_string(safe_get(row, 'Part NO'), ''),
        part_name=safe_string(safe_get(row, 'Part Name'), '', 500),
        uom=safe_string(safe_get(row, 'UOM'), ''),
        hsn_number=safe_string(safe_get(row, 'HSN Number'), ''),
        product_type=safe_string(safe_get(row, 'Product Type'), ''),
        product_category=safe_string(safe_get(row, 'Product Category'), ''),

        # Quantity and pricing
        quantity=safe_int(safe_get(row, 'Quantity')),
        unit_price=safe_decimal(safe_get(row, 'Unit Price')),
        line_item_discount_percent=safe_decimal(safe_get(row, 'Line Item Discount %')),
        line_item_discount=safe_decimal(safe_get(row, 'Line Item Discount')),
        net_selling_price=safe_decimal(safe_get(row, 'Net Selling Price')),
        assessable_value=safe_decimal(safe_get(row, 'Assessable Value')),

        # Tax information
        vat_amount=safe_decimal(safe_get(row, 'VAT AMOUNT')),
        cgst_percent=safe_decimal(safe_get(row, 'CGST %')),
        cgst_amount=safe_decimal(safe_get(row, 'CGST Amt')),
        sgst_percent=safe_decimal(safe_get(row, 'SGST %')),
        sgst_amount=safe_decimal(safe_get(row, 'SGST Amt')),
        utgst_percent=safe_decimal(safe_get(row, 'UT GST %')),
        utgst_amount=safe_decimal(safe_get(row, 'UT GST Amt')),
        igst_percent=safe_decimal(safe_get(row, 'IGST %')),
        igst_amount=safe_decimal(safe_get(row, 'IGST Amt')),
        cess_percent=safe_decimal(safe_get(row, 'CESS %')),
        cess_amount=safe_decimal(safe_get(row, 'CESS Amt')),

        # Additional tax amounts
        additional_tax_amt=safe_decimal(safe_get(row, 'Additional Tax Amt')),
        additional_tax_amt2=safe_decimal(safe_get(row, 'Additional Tax Amt2')),
        additional_tax_amt3=safe_decimal(safe_get(row, 'Additional Tax Amt3')),
        additional_tax_amt4=safe_decimal(safe_get(row, 'Additional Tax Amt4')),
        additional_tax_amt5=safe_decimal(safe_get(row, 'Additional Tax Amt5')),

        # Freight and packaging
        freight_amount=safe_decimal(safe_get(row, 'Freight AMT')),
        packaging_charges=safe_decimal(safe_get(row, 'Packaging Charges')),

        # Freight/Packaging GST
        frt_pkg_cgst_percent=safe_decimal(safe_get(row, 'FRT PKG CGST %')),
        frt_pkg_cgst_amount=safe_decimal(safe_get(row, 'FRT PKG CGST AMT')),
        frt_pkg_sgst_percent=safe_decimal(safe_get(row, 'FRT PKG SGST/UTGST %')),
        frt_pkg_sgst_amount=safe_decimal(safe_get(row, 'FRT PKG SGST/UTGST AMT')),
        frt_pkg_igst_percent=safe_decimal(safe_get(row, 'FRT PKG IGST %')),
        frt_pkg_igst_amount=safe_decimal(safe_get(row, 'FRT PKG IGST AMT')),
        frt_pkg_cess_percent=safe_decimal(safe_get(row, 'FRT PKG CESS %')),
        frt_pkg_cess_amount=safe_decimal(safe_get(row, 'FRT PKG CESS AMT')),

        # Totals and discounts
        total_invoice_amount=safe_decimal(safe_get(row, 'Total Invoice Amount')),
        additional_discount_percent=safe_decimal(safe_get(row, 'Additional Discount %')),
        cash_discount_percent=safe_decimal(safe_get(row, 'Cash Discount %')),
        credit_days=safe_int(safe_get(row, 'Credit Days')),

        # Location and tax details
        location_code=safe_string(safe_get(row, 'Location Code'), ''),
        state=safe_string(safe_get(row, 'State'), ''),
        state_code=safe_string(safe_get(row, 'State Code'), ''),
        gstin=safe_string(safe_get(row, 'GSTIN'), ''),

        # System fields
        record_updated_dt=safe_date(safe_get(row, 'Record Updated dt')),
        login=safe_string(safe_get(row, 'LOGIN'), ''),
        voucher=safe_string(safe_get(row, 'VOUCHER'), ''),
        type_field=safe_string(safe_get(row, 'Type'), ''),
        parent=safe_string(safe_get(row, 'Parent'), ''),
        sale_return_date=safe_date(safe_get(row, 'Sale Return Date')),
        narration=safe_string(safe_get(row, 'Narration'), ''),
        cancellation_date=safe_date(safe_get(row, 'Cancellation Date')),
        executive_name=safe_string(safe_get(row, 'Executive Name'), ''),

        # Upload tracking
        uploaded_by=user_id,
        upload_batch_id=upload_batch_id,
        created_at=current_time,
        updated_at=current_time
    )

    return invoice


def update_order_to_completed(potential_order, user_id):
    """
    Update a potential order status to Completed - MySQL implementation

    Args:
        potential_order: PotentialOrder instance
        user_id: User ID making the update
    """
    try:
        current_time = datetime.utcnow()

        # Update order status
        potential_order.status = 'Completed'
        potential_order.updated_at = current_time
        potential_order.save()

        # Create or get the Completed state
        completed_state = OrderState.find_by_name('Completed')
        if not completed_state:
            completed_state = OrderState(
                state_name='Completed',
                description='Order completed via invoice processing'
            )
            completed_state.save()

        # Add state history
        state_history = OrderStateHistory(
            potential_order_id=potential_order.potential_order_id,
            state_id=completed_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        state_history.save()

        print(f"Updated order {potential_order.original_order_id} to Completed status")

    except Exception as e:
        print(f"Error updating order {potential_order.original_order_id} to completed: {str(e)}")
        raise e


def create_error_dataframe(error_rows):
    """
    Create a pandas DataFrame from error rows for CSV export

    Args:
        error_rows: List of error row dictionaries

    Returns:
        DataFrame: Error data ready for CSV export
    """
    if not error_rows:
        return None

    import pandas as pd
    return pd.DataFrame(error_rows)