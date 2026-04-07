# -*- encoding: utf-8 -*-
"""
Order Business Logic for MySQL — updated for new CSV format.
One row = one order (no product rows).
"""

from datetime import datetime
from ..models import PotentialOrder, OrderState, OrderStateHistory
from . import dealer_business


def process_order_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None):
    """
    Process a dataframe of order data (new format: one row = one order).

    Args:
        df: Pandas DataFrame with order data
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: ID of the user processing the orders
        upload_batch_id: Upload batch ID for tracking

    Returns:
        dict: Processing results
    """
    orders_processed = 0
    errors = []

    print(f"Processing DataFrame with {len(df)} rows")
    print(f"DataFrame columns: {df.columns.tolist()}")

    for index, row in df.iterrows():
        try:
            print(f"Processing row {index}: {dict(row)}")

            # --- Required field ---
            sales_order_id = str(row.get('Sales Order #', '') or '').strip()
            if not sales_order_id:
                errors.append(f"Row {index}: Missing Sales Order #. Skipping row.")
                continue

            # --- New columns ---
            b2b_po_number     = str(row.get('B2B PO#', '') or '').strip() or None
            order_type        = str(row.get('Order Type', '') or '').strip() or None
            vin_number        = str(row.get('Invoice # / VIN #', '') or '').strip() or None
            shipping_address  = str(row.get('Shipping Address', '') or '').strip() or None
            source_created_by = str(row.get('Created By', '') or '').strip() or None
            purchaser_sap_code = str(row.get('Purchaser SAP Code', '') or '').strip() or None
            purchaser_name    = str(row.get('Purchaser Name', '') or '').strip() or None

            # --- Date ---
            order_date_str = row.get('Submit Date')
            order_date = parse_order_date(order_date_str, index, errors)

            # --- Dealer (lookup/create by Purchaser Name only during order upload) ---
            dealer_id = None
            if purchaser_name:
                try:
                    dealer_id = dealer_business.get_or_create_dealer(purchaser_name)
                    print(f"Row {index}: Got dealer_id={dealer_id}")
                except Exception as e:
                    errors.append(f"Row {index}: Error resolving dealer: {str(e)}")
            else:
                errors.append(f"Row {index}: No Purchaser Name — order created without dealer association.")

            # --- Create order ---
            try:
                potential_order_id = create_potential_order(
                    original_order_id=sales_order_id,
                    b2b_po_number=b2b_po_number,
                    order_type=order_type,
                    vin_number=vin_number,
                    shipping_address=shipping_address,
                    source_created_by=source_created_by,
                    purchaser_sap_code=purchaser_sap_code,
                    purchaser_name=purchaser_name,
                    warehouse_id=warehouse_id,
                    company_id=company_id,
                    dealer_id=dealer_id,
                    order_date=order_date,
                    user_id=user_id,
                    upload_batch_id=upload_batch_id
                )
                orders_processed += 1
                print(f"Row {index}: Created order {potential_order_id} for Sales Order # {sales_order_id}")
            except Exception as e:
                errors.append(f"Row {index}: Error creating order: {str(e)}")
                continue

        except Exception as e:
            errors.append(f"Row {index}: Unexpected error: {str(e)}")
            print(f"Row {index}: Unexpected error: {str(e)}")
            continue

    print(f"Processing complete: {orders_processed} orders, {len(errors)} errors")

    return {
        'orders_processed': orders_processed,
        'products_processed': 0,  # products not used in new format
        'errors': errors
    }


def parse_order_date(order_date_str, row_index, errors):
    """Parse order date from various formats."""
    try:
        if isinstance(order_date_str, str) and order_date_str.strip():
            date_formats = [
                '%d/%m/%Y %I:%M:%S %p',  # 03/04/2026 08:59:37 AM (new format)
                '%d/%m/%Y %H:%M:%S',
                '%Y-%m-%d',
                '%d/%m/%Y',
                '%m/%d/%Y',
            ]
            for fmt in date_formats:
                try:
                    return datetime.strptime(order_date_str.strip(), fmt)
                except ValueError:
                    continue
            try:
                from dateutil import parser
                return parser.parse(order_date_str)
            except Exception:
                raise ValueError(f"Unrecognized date format: {order_date_str}")
        else:
            if hasattr(order_date_str, 'year'):
                return order_date_str
            return datetime.now()
    except Exception as e:
        errors.append(f"Row {row_index}: Could not parse date '{order_date_str}'. Using current date. Error: {str(e)}")
        return datetime.now()


def create_potential_order(original_order_id, b2b_po_number, order_type, vin_number,
                           shipping_address, source_created_by, purchaser_sap_code,
                           purchaser_name, warehouse_id, company_id, dealer_id,
                           order_date, user_id, upload_batch_id=None):
    """Create a new potential order — MySQL implementation."""
    current_time = datetime.utcnow()

    print(f"Creating potential order: {original_order_id}, warehouse={warehouse_id}, company={company_id}")

    potential_order = PotentialOrder(
        original_order_id=original_order_id,
        b2b_po_number=b2b_po_number,
        order_type=order_type,
        vin_number=vin_number,
        shipping_address=shipping_address,
        source_created_by=source_created_by,
        purchaser_sap_code=purchaser_sap_code,
        purchaser_name=purchaser_name,
        warehouse_id=warehouse_id,
        company_id=company_id,
        dealer_id=dealer_id,
        order_date=order_date,
        requested_by=user_id,
        status='Open',
        upload_batch_id=upload_batch_id,
        created_at=current_time,
        updated_at=current_time
    )
    potential_order.save()
    potential_order_id = potential_order.potential_order_id
    print(f"Created potential order with ID: {potential_order_id}")

    # Create initial Open state history
    try:
        initial_state = OrderState.find_by_name('Open')
        if not initial_state:
            initial_state = OrderState(
                state_name='Open',
                description='Order is open and ready for processing'
            )
            initial_state.save()

        state_history = OrderStateHistory(
            potential_order_id=potential_order_id,
            state_id=initial_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        state_history.save()
        print(f"Created state history for order {potential_order_id}")
    except Exception as e:
        print(f"Error creating state history: {str(e)}")
        # Don't fail order creation if state history fails

    return potential_order_id
