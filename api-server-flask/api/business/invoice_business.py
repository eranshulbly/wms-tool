# -*- encoding: utf-8 -*-
"""
Invoice Business Logic for MySQL
"""

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from ..models import db, Invoice, PotentialOrder, OrderState, OrderStateHistory


def process_invoice_dataframe(df, warehouse_id, company_id, user_id):
    """
    Process a dataframe of invoice data and update order statuses

    Args:
        df: Pandas DataFrame with invoice data
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: ID of the user processing the invoices

    Returns:
        dict: Processing results with success and error data
    """
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
                db.session.add(invoice)
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
    Find a potential order by its original order ID

    Args:
        original_order_id: The original order ID from narration
        warehouse_id: Warehouse ID filter
        company_id: Company ID filter

    Returns:
        PotentialOrder: Found order or None
    """
    try:
        return db.session.query(PotentialOrder).filter(
            PotentialOrder.original_order_id == original_order_id,
            PotentialOrder.warehouse_id == warehouse_id,
            PotentialOrder.company_id == company_id
        ).first()
    except Exception as e:
        print(f"Error finding order for {original_order_id}: {str(e)}")
        return None


def create_invoice_from_row(row, potential_order_id, warehouse_id, company_id, user_id, upload_batch_id):
    """
    Create an Invoice object from a DataFrame row

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
    current_time = datetime.utcnow()

    # Helper function to safely convert to decimal
    def safe_decimal(value, default=None):
        if value is None or value == '' or str(value).strip() == '':
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return default

    # Helper function to safely convert to integer
    def safe_int(value, default=None):
        if value is None or value == '' or str(value).strip() == '':
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default

    # Helper function to safely parse dates
    def safe_date(value):
        if value is None or value == '' or str(value).strip() == '':
            return None
        try:
            if isinstance(value, str):
                # Try different date formats
                date_formats = ['%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
                for fmt in date_formats:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                # If none work, try pandas datetime parsing
                import pandas as pd
                return pd.to_datetime(value).to_pydatetime()
            elif hasattr(value, 'year'):  # Already a datetime object
                return value
            else:
                return None
        except Exception:
            return None

    invoice = Invoice(
        # Foreign keys
        potential_order_id=potential_order_id,
        warehouse_id=warehouse_id,
        company_id=company_id,

        # Invoice identification
        invoice_number=str(row.get('Invoice Number', '')),
        dealer_code=str(row.get('Dealer Code', '')),
        original_order_id=str(row.get('Narration', '')),

        # Customer information
        customer_name=str(row.get('Customer Name', ''))[:500],  # Truncate to field length
        customer_code=str(row.get('Customer Code', '')),
        customer_category=str(row.get('Customer Category', '')),

        # Invoice details
        invoice_date=safe_date(row.get('Invoice Date')),
        invoice_status=str(row.get('Invoice Status', '')),
        invoice_type=str(row.get('Invoice Type', '')),
        invoice_format=str(row.get('Invoice Format', '')),

        # Product information
        part_no=str(row.get('Part NO', '')),
        part_name=str(row.get('Part Name', ''))[:500],
        uom=str(row.get('UOM', '')),
        hsn_number=str(row.get('HSN Number', '')),
        product_type=str(row.get('Product Type', '')),
        product_category=str(row.get('Product Category', '')),

        # Quantity and pricing
        quantity=safe_int(row.get('Quantity')),
        unit_price=safe_decimal(row.get('Unit Price')),
        line_item_discount_percent=safe_decimal(row.get('Line Item Discount %')),
        line_item_discount=safe_decimal(row.get('Line Item Discount')),
        net_selling_price=safe_decimal(row.get('Net Selling Price')),
        assessable_value=safe_decimal(row.get('Assessable Value')),

        # Tax information
        vat_amount=safe_decimal(row.get('VAT AMOUNT')),
        cgst_percent=safe_decimal(row.get('CGST %')),
        cgst_amount=safe_decimal(row.get('CGST Amt')),
        sgst_percent=safe_decimal(row.get('SGST %')),
        sgst_amount=safe_decimal(row.get('SGST Amt')),
        utgst_percent=safe_decimal(row.get('UT GST %')),
        utgst_amount=safe_decimal(row.get('UT GST Amt')),
        igst_percent=safe_decimal(row.get('IGST %')),
        igst_amount=safe_decimal(row.get('IGST Amt')),
        cess_percent=safe_decimal(row.get('CESS %')),
        cess_amount=safe_decimal(row.get('CESS Amt')),

        # Additional tax amounts
        additional_tax_amt=safe_decimal(row.get('Additional Tax Amt')),
        additional_tax_amt2=safe_decimal(row.get('Additional Tax Amt2')),
        additional_tax_amt3=safe_decimal(row.get('Additional Tax Amt3')),
        additional_tax_amt4=safe_decimal(row.get('Additional Tax Amt4')),
        additional_tax_amt5=safe_decimal(row.get('Additional Tax Amt5')),

        # Freight and packaging
        freight_amount=safe_decimal(row.get('Freight AMT')),
        packaging_charges=safe_decimal(row.get('Packaging Charges')),

        # Freight/Packaging GST
        frt_pkg_cgst_percent=safe_decimal(row.get('FRT PKG CGST %')),
        frt_pkg_cgst_amount=safe_decimal(row.get('FRT PKG CGST AMT')),
        frt_pkg_sgst_percent=safe_decimal(row.get('FRT PKG SGST/UTGST %')),
        frt_pkg_sgst_amount=safe_decimal(row.get('FRT PKG SGST/UTGST AMT')),
        frt_pkg_igst_percent=safe_decimal(row.get('FRT PKG IGST %')),
        frt_pkg_igst_amount=safe_decimal(row.get('FRT PKG IGST AMT')),
        frt_pkg_cess_percent=safe_decimal(row.get('FRT PKG CESS %')),
        frt_pkg_cess_amount=safe_decimal(row.get('FRT PKG CESS AMT')),

        # Totals and discounts
        total_invoice_amount=safe_decimal(row.get('Total Invoice Amount')),
        additional_discount_percent=safe_decimal(row.get('Additional Discount %')),
        cash_discount_percent=safe_decimal(row.get('Cash Discount %')),
        credit_days=safe_int(row.get('Credit Days')),

        # Location and tax details
        location_code=str(row.get('Location Code', '')),
        state=str(row.get('State', '')),
        state_code=str(row.get('State Code', '')),
        gstin=str(row.get('GSTIN', '')),

        # System fields
        record_updated_dt=safe_date(row.get('Record Updated dt')),
        login=str(row.get('LOGIN', '')),
        voucher=str(row.get('VOUCHER', '')),
        type_field=str(row.get('Type', '')),
        parent=str(row.get('Parent', '')),
        sale_return_date=safe_date(row.get('Sale Return Date')),
        narration=str(row.get('Narration', '')),
        cancellation_date=safe_date(row.get('Cancellation Date')),
        executive_name=str(row.get('Executive Name', '')),

        # Upload tracking
        uploaded_by=user_id,
        upload_batch_id=upload_batch_id,
        created_at=current_time,
        updated_at=current_time
    )

    return invoice


def update_order_to_completed(potential_order, user_id):
    """
    Update a potential order status to Completed

    Args:
        potential_order: PotentialOrder instance
        user_id: User ID making the update
    """
    try:
        current_time = datetime.utcnow()

        # Update order status
        potential_order.status = 'Completed'
        potential_order.updated_at = current_time

        # Create or get the Completed state
        completed_state = db.session.query(OrderState).filter(
            OrderState.state_name == 'Completed'
        ).first()

        if not completed_state:
            completed_state = OrderState(
                state_name='Completed',
                description='Order completed via invoice processing'
            )
            db.session.add(completed_state)
            db.session.flush()

        # Add state history
        state_history = OrderStateHistory(
            potential_order_id=potential_order.potential_order_id,
            state_id=completed_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        db.session.add(state_history)

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