# -*- encoding: utf-8 -*-
"""
Order Business Logic for MySQL — updated for new CSV format.
One row = one order (no product rows).
"""

from datetime import datetime
from ..models import PotentialOrder, OrderState, OrderStateHistory, Order, OrderBox, Dealer
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
    error_rows = []

    print(f"Processing DataFrame with {len(df)} rows")
    print(f"DataFrame columns: {df.columns.tolist()}")

    for index, row in df.iterrows():
        try:
            print(f"Processing row {index}: {dict(row)}")

            # --- Required field ---
            sales_order_id = str(row.get('Sales Order #', '') or '').strip()
            purchaser_name = str(row.get('Purchaser Name', '') or '').strip() or None

            if not sales_order_id:
                error_rows.append(_make_error_row('', purchaser_name, f"Row {index}: Missing Sales Order #"))
                continue

            # --- New columns ---
            b2b_po_number     = str(row.get('B2B PO#', '') or '').strip() or None
            order_type        = str(row.get('Order Type', '') or '').strip() or None
            vin_number        = str(row.get('Invoice # / VIN #', '') or '').strip() or None
            shipping_address  = str(row.get('Shipping Address', '') or '').strip() or None
            source_created_by = str(row.get('Created By', '') or '').strip() or None
            purchaser_sap_code = str(row.get('Purchaser SAP Code', '') or '').strip() or None

            # --- Date ---
            order_date_str = row.get('Submit Date')
            order_date = parse_order_date(order_date_str, index)

            # --- Dealer (lookup/create by Purchaser Name only during order upload) ---
            dealer_id = None
            if purchaser_name:
                try:
                    dealer_id = dealer_business.get_or_create_dealer(purchaser_name)
                    print(f"Row {index}: Got dealer_id={dealer_id}")
                except Exception as e:
                    print(f"Row {index}: Error resolving dealer: {str(e)}")
            else:
                print(f"Row {index}: No Purchaser Name — order created without dealer association.")

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
                if '1062' in str(e) or 'Duplicate entry' in str(e):
                    reason = f"Order {sales_order_id} already exists"
                else:
                    reason = f"Error creating order: {str(e)}"
                error_rows.append(_make_error_row(sales_order_id, purchaser_name, reason))
                continue

        except Exception as e:
            sales_order_id = str(row.get('Sales Order #', '') or '').strip()
            purchaser_name = str(row.get('Purchaser Name', '') or '').strip()
            error_rows.append(_make_error_row(sales_order_id, purchaser_name, f"Unexpected error: {str(e)}"))
            print(f"Row {index}: Unexpected error: {str(e)}")
            continue

    print(f"Processing complete: {orders_processed} orders, {len(error_rows)} errors")

    return {
        'orders_processed': orders_processed,
        'error_rows': error_rows,
    }


def _make_error_row(order_id, name, reason):
    return {'order_id': order_id or '', 'name': name or '', 'reason': reason}


def parse_order_date(order_date_str, row_index=None):
    """Parse order date from various formats. Returns datetime.now() on failure."""
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
        print(f"Row {row_index}: Could not parse date '{order_date_str}'. Using current date. Error: {str(e)}")
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


# ---------------------------------------------------------------------------
# Bulk status update (from Excel file upload on Manage Orders page)
# ---------------------------------------------------------------------------

# Forward-only chain: key = expected current status → value = valid target
_VALID_TRANSITIONS = {
    'Open': 'Picking',
    'Picking': 'Packed',
    'Dispatch Ready': 'Completed',
}
# Reverse lookup: target → required source
_SOURCE_FOR_TARGET = {v: k for k, v in _VALID_TRANSITIONS.items()}

_FRONTEND_TO_DB_STATUS = {
    'open': 'Open',
    'picking': 'Picking',
    'packed': 'Packed',
    'dispatch-ready': 'Dispatch Ready',
    'completed': 'Completed',
    'partially-completed': 'Partially Completed',
}


def process_bulk_status_update(df, target_status, warehouse_id, company_id, user_id):
    """
    Bulk-transition orders from an uploaded Excel DataFrame.

    Required columns:
        'Order ID'  — the original_order_id
    Required when target_status == 'packed':
        'Number of Boxes'

    Returns:
        {'orders_processed': int, 'error_rows': list}
    """
    db_target = _FRONTEND_TO_DB_STATUS.get(
        target_status.lower().replace(' ', '-')
    )
    if not db_target:
        return {
            'orders_processed': 0,
            'error_rows': [{'order_id': '', 'name': '',
                            'reason': f'Invalid target status: {target_status}'}]
        }

    required_source = _SOURCE_FOR_TARGET.get(db_target)
    if not required_source:
        return {
            'orders_processed': 0,
            'error_rows': [{'order_id': '', 'name': '',
                            'reason': f'Cannot bulk-move orders to "{db_target}" status. '
                                      f'Only Picking, Packed, and Completed are valid bulk targets.'}]
        }

    needs_boxes = (db_target == 'Packed')
    orders_processed = 0
    error_rows = []

    # ------------------------------------------------------------------ #
    # Pre-fetch all PotentialOrders in one query instead of N queries.    #
    # Also pre-load OrderState objects so we don't hit the DB per row.    #
    # ------------------------------------------------------------------ #
    all_order_ids = [
        str(row.get('Order ID', '') or '').strip()
        for _, row in df.iterrows()
    ]
    all_order_ids = [oid for oid in all_order_ids if oid]
    potential_orders_map = PotentialOrder.find_bulk_by_original_order_ids(all_order_ids)

    # Pre-load/create the target OrderState once
    new_state = OrderState.find_by_name(db_target)
    if not new_state:
        new_state = OrderState(state_name=db_target, description=f'{db_target} state')
        new_state.save()

    invoiced_state = None
    if needs_boxes:
        invoiced_state = OrderState.find_by_name('Invoiced')
        if not invoiced_state:
            invoiced_state = OrderState(state_name='Invoiced', description='Invoice uploaded for order')
            invoiced_state.save()

    for index, row in df.iterrows():
        original_order_id = str(row.get('Order ID', '') or '').strip()
        if not original_order_id:
            error_rows.append({'order_id': '', 'name': '', 'reason': 'Missing Order ID'})
            continue

        # Resolve potential order from pre-fetched map
        potential_order = potential_orders_map.get(original_order_id)
        if not potential_order:
            error_rows.append({
                'order_id': original_order_id, 'name': '',
                'reason': f'Order not found: {original_order_id}'
            })
            continue

        # Get dealer name for error rows
        dealer_name = ''
        if potential_order.dealer_id:
            dealer = Dealer.get_by_id(potential_order.dealer_id)
            if dealer:
                dealer_name = dealer.name

        # Validate strict chain
        if potential_order.status != required_source:
            error_rows.append({
                'order_id': original_order_id, 'name': dealer_name,
                'reason': (f'Order is in "{potential_order.status}" status. '
                           f'Expected "{required_source}" to move to "{db_target}".')
            })
            continue

        # Parse number_of_boxes when needed
        number_of_boxes = 1
        if needs_boxes:
            raw = str(row.get('Number of Boxes', '') or '').strip()
            try:
                number_of_boxes = int(float(raw))
                if number_of_boxes < 1:
                    raise ValueError()
            except Exception:
                error_rows.append({
                    'order_id': original_order_id, 'name': dealer_name,
                    'reason': 'Invalid or missing "Number of Boxes" (must be a positive integer)'
                })
                continue

        # Perform the transition
        try:
            current_time = datetime.utcnow()

            # Use pre-fetched OrderState objects (no extra DB query per row)
            potential_order.status = db_target
            potential_order.updated_at = current_time
            potential_order.save()

            OrderStateHistory(
                potential_order_id=potential_order.potential_order_id,
                state_id=new_state.state_id,
                changed_by=user_id,
                changed_at=current_time
            ).save()

            # When moving to Packed: create the Order record + boxes
            if db_target == 'Packed':
                final_order = None
                existing_order = Order.find_by_potential_order_id(
                    potential_order.potential_order_id
                )
                if not existing_order:
                    final_order = Order(
                        potential_order_id=potential_order.potential_order_id,
                        order_number=(
                            f"ORD-{potential_order.potential_order_id}"
                            f"-{current_time.strftime('%Y%m%d%H%M')}"
                        ),
                        status='Packed',
                        created_at=current_time,
                        updated_at=current_time
                    )
                    final_order.save()
                    for i in range(number_of_boxes):
                        OrderBox(
                            order_id=final_order.order_id,
                            name=f'Box-{i + 1}',
                            created_at=current_time,
                            updated_at=current_time
                        ).save()
                else:
                    final_order = existing_order

                # Auto-transition: invoice was already submitted while order was
                # in Open/Picking — Packed state history is already recorded above;
                # now transition straight to Invoiced.
                if potential_order.invoice_submitted:
                    potential_order.status = 'Invoiced'
                    potential_order.invoice_submitted = False
                    potential_order.updated_at = current_time
                    potential_order.save()

                    if final_order:
                        final_order.status = 'Invoiced'
                        final_order.updated_at = current_time
                        final_order.save()

                    # Record the Invoiced state history entry (use pre-fetched state)
                    OrderStateHistory(
                        potential_order_id=potential_order.potential_order_id,
                        state_id=invoiced_state.state_id,
                        changed_by=user_id,
                        changed_at=current_time
                    ).save()
                    db_target = 'Invoiced'

            # When moving to Completed: update final Order record
            if db_target == 'Completed':
                final_order = Order.find_by_potential_order_id(
                    potential_order.potential_order_id
                )
                if final_order:
                    final_order.status = 'Completed'
                    final_order.dispatched_date = current_time
                    final_order.updated_at = current_time
                    final_order.save()

            orders_processed += 1
            print(f"Bulk: moved order {original_order_id} → {db_target}")

        except Exception as e:
            # Best-effort rollback
            try:
                potential_order.status = required_source
                potential_order.save()
            except Exception:
                pass
            error_rows.append({
                'order_id': original_order_id, 'name': dealer_name,
                'reason': f'Error transitioning order: {str(e)}'
            })

    return {'orders_processed': orders_processed, 'error_rows': error_rows}
