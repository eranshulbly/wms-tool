# -*- encoding: utf-8 -*-
"""
Invoice Business Logic for MySQL — updated for new CSV format.
"""
from datetime import datetime
from ..models import PotentialOrder, OrderState, OrderStateHistory, Invoice
from ..business.dealer_business import get_or_create_dealer


def process_invoice_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None):
    """
    Process a dataframe of invoice data and update order statuses.

    Args:
        df: Pandas DataFrame with invoice data
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: ID of the user processing the invoices
        upload_batch_id: Batch identifier

    Returns:
        dict: Processing results
    """
    invoices_processed = 0
    orders_updated = 0
    errors = []
    error_rows = []

    print(f"Processing DataFrame with {len(df)} rows for batch {upload_batch_id}")
    print(f"DataFrame columns: {df.columns.tolist()}")

    # Track orders already transitioned this upload (avoid duplicate state changes)
    processed_orders = set()

    for index, row in df.iterrows():
        try:
            print(f"Processing row {index}: {dict(row)}")

            # --- Required fields ---
            invoice_number = str(row.get('Invoice #', '') or '').strip()
            original_order_id = str(row.get('Order #', '') or '').strip()

            if not invoice_number or not original_order_id:
                error_msg = f"Row {index}: Missing Invoice # or Order #"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            print(f"Row {index}: Processing invoice {invoice_number} for order {original_order_id}")

            # --- Match potential order ---
            potential_order = PotentialOrder.find_by_original_order_id(
                original_order_id, warehouse_id, company_id
            )

            if not potential_order:
                error_msg = f"Row {index}: No matching order found for Order #: {original_order_id}"
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            # --- Status check: order must be Invoice Ready ---
            if potential_order.status != 'Invoice Ready':
                error_msg = (
                    f"Row {index}: Order {original_order_id} is in '{potential_order.status}' "
                    f"status, not 'Invoice Ready'"
                )
                errors.append(error_msg)
                error_rows.append({**dict(row), 'Error': error_msg, 'Row_Number': index + 1})
                continue

            # --- Dealer resolution: Code + Account Name → dealer_id ---
            dealer_id = _resolve_dealer(row, index, errors)

            # --- Backfill potential_order.dealer_id if not already set ---
            if dealer_id and not potential_order.dealer_id:
                potential_order.dealer_id = dealer_id
                potential_order.save()
                print(f"Row {index}: Backfilled dealer_id={dealer_id} on order {original_order_id}")

            # --- Create invoice record ---
            try:
                invoice = create_invoice_from_row(
                    row=row,
                    potential_order_id=potential_order.potential_order_id,
                    warehouse_id=warehouse_id,
                    company_id=company_id,
                    dealer_id=dealer_id,
                    user_id=user_id,
                    upload_batch_id=upload_batch_id
                )
                invoice.save()
                invoices_processed += 1
                print(f"Row {index}: Created invoice record for {invoice_number}")

                # --- Transition order: Invoice Ready → Dispatch Ready (once per order) ---
                if potential_order.potential_order_id not in processed_orders:
                    update_order_to_dispatch_ready(potential_order, user_id)
                    processed_orders.add(potential_order.potential_order_id)
                    orders_updated += 1
                    print(f"Row {index}: Moved order {original_order_id} to Dispatch Ready")

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

    print(f"Processing complete: {invoices_processed} invoices, {orders_updated} orders updated, {len(errors)} errors")

    return {
        'invoices_processed': invoices_processed,
        'orders_completed': orders_updated,
        'errors': errors,
        'error_rows': error_rows,
        'upload_batch_id': upload_batch_id
    }


def _resolve_dealer(row, index, errors):
    """Look up or create dealer from invoice row's Code + Account Name."""
    dealer_code = str(row.get('Code', '') or '').strip() or None
    account_name = str(row.get('Account Name', '') or '').strip() or None

    if not dealer_code and not account_name:
        errors.append(f"Row {index}: No dealer Code or Account Name — invoice saved without dealer link.")
        return None

    try:
        dealer_id = get_or_create_dealer(
            dealer_name=account_name or dealer_code,
            dealer_code=dealer_code
        )
        return dealer_id
    except Exception as e:
        errors.append(f"Row {index}: Error resolving dealer (Code={dealer_code}): {str(e)}")
        return None


def create_invoice_from_row(row, potential_order_id, warehouse_id, company_id,
                             dealer_id, user_id, upload_batch_id):
    """
    Create an Invoice object from a new-format DataFrame row.

    Args:
        row: DataFrame row with invoice data
        potential_order_id: Associated potential order ID
        warehouse_id: Warehouse ID
        company_id: Company ID
        dealer_id: Resolved dealer ID (FK)
        user_id: Uploading user ID
        upload_batch_id: Batch identifier

    Returns:
        Invoice: Unsaved Invoice object (caller must call .save())
    """
    from decimal import Decimal, InvalidOperation
    import pandas as pd

    current_time = datetime.utcnow()

    def safe_decimal(value, default=None):
        if value is None or value == '':
            return default
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return default
            return Decimal(str_value.replace(',', ''))
        except (InvalidOperation, ValueError, TypeError):
            return default

    def safe_int(value, default=None):
        if value is None or value == '':
            return default
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return default
            return int(float(str_value))
        except (ValueError, TypeError):
            return default

    def safe_string(value, default='', max_length=None):
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null']:
                return default
            if max_length and len(str_value) > max_length:
                return str_value[:max_length]
            return str_value
        except (TypeError, AttributeError):
            return default

    def safe_date(value):
        if value is None or value == '':
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        try:
            str_value = str(value).strip()
            if str_value.lower() in ['nan', 'none', 'null', '']:
                return None
            if isinstance(value, str):
                date_formats = [
                    '%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
                    '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %I:%M:%S %p'
                ]
                for fmt in date_formats:
                    try:
                        return datetime.strptime(str_value, fmt)
                    except ValueError:
                        continue
                parsed = pd.to_datetime(str_value, errors='coerce')
                return parsed.to_pydatetime() if not pd.isna(parsed) else None
            elif hasattr(value, 'year'):
                return value
        except Exception:
            pass
        return None

    def sg(key, default=None):
        """Safe row.get with NaN guard."""
        val = row.get(key, default)
        try:
            if pd.isna(val):
                return default
        except (TypeError, ValueError):
            pass
        return val

    return Invoice(
        # Foreign keys
        potential_order_id=potential_order_id,
        warehouse_id=warehouse_id,
        company_id=company_id,
        dealer_id=dealer_id,

        # Core invoice fields
        invoice_number=safe_string(sg('Invoice #'), ''),
        original_order_id=safe_string(sg('Order #'), ''),
        invoice_date=safe_date(sg('Invoice Date')),
        invoice_type=safe_string(sg('Invoice Type'), ''),
        cancellation_date=safe_date(sg('Invoice Cancel Date')),
        total_invoice_amount=safe_decimal(sg('Invoice Amount')),
        invoice_header_type=safe_string(sg('Invoice Header Type'), ''),

        # Order linkage
        order_date=safe_date(sg('Order Date')),
        b2b_purchase_order_number=safe_string(sg('B2B Purchase Order #'), ''),
        b2b_order_type=safe_string(sg('B2B Order Type'), ''),

        # Customer/dealer info (raw strings for audit; canonical info via dealer FK)
        account_tin=safe_string(sg('Account TIN#'), ''),
        cash_customer_name=safe_string(sg('Cash Customer Name'), ''),
        contact_first_name=safe_string(sg('Contact First Name'), ''),
        contact_last_name=safe_string(sg('Contact Last Name'), ''),
        customer_category=safe_string(sg('Customer Category'), ''),

        # Financial
        round_off_amount=safe_decimal(sg('Round Off Amount')),
        invoice_round_off_amount=safe_decimal(sg('Invoice Round Off Amount')),
        short_amount=safe_decimal(sg('Short Amount')),
        realized_amount=safe_decimal(sg('Realized Amount')),

        # Misc
        hmcgl_card_no=safe_string(sg('HMCGL Card No'), ''),
        campaign=safe_string(sg('Campaign'), ''),

        # Packaging & forwarding
        packaging_forwarding_charges=safe_decimal(sg('Packaging & Forwarding Charges')),
        tax_on_pf=safe_decimal(sg('Tax on Package & Forwarding')),
        type_of_tax_pf=safe_string(sg('Type of Tax P&F'), ''),

        # GST e-invoice (IRN / Ack)
        irn_number=safe_string(sg('IRN#'), ''),
        irn_status=safe_string(sg('IRN Status'), ''),
        ack_number=safe_string(sg('Ack#'), ''),
        ack_date=safe_date(sg('Ack Date')),

        # Cancellation IRN / Ack
        credit_note_number=safe_string(sg('Credit Note# (Canc.>24h)'), ''),
        irn_cancel=safe_string(sg('IRN# (Canc.>24h)'), ''),
        irn_status_cancel=safe_string(sg('IRN Status (Canc.>24h)'), ''),
        ack_number_cancel=safe_string(sg('Ack# (Canc.>24h)'), ''),
        ack_date_cancel=safe_date(sg('Ack Date (Canc.>24h)')),

        # Upload tracking
        uploaded_by=user_id,
        upload_batch_id=upload_batch_id,
        created_at=current_time,
        updated_at=current_time
    )


def update_order_to_dispatch_ready(potential_order, user_id):
    """
    Transition a potential order from Invoice Ready → Dispatch Ready.

    Args:
        potential_order: PotentialOrder instance
        user_id: User ID making the update
    """
    try:
        current_time = datetime.utcnow()

        potential_order.status = 'Dispatch Ready'
        potential_order.updated_at = current_time
        potential_order.save()

        dispatch_ready_state = OrderState.find_by_name('Dispatch Ready')
        if not dispatch_ready_state:
            dispatch_ready_state = OrderState(
                state_name='Dispatch Ready',
                description='Invoices uploaded, order ready for physical dispatch'
            )
            dispatch_ready_state.save()

        state_history = OrderStateHistory(
            potential_order_id=potential_order.potential_order_id,
            state_id=dispatch_ready_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        state_history.save()

        print(f"Moved order {potential_order.original_order_id} to Dispatch Ready")

    except Exception as e:
        print(f"Error updating order {potential_order.original_order_id} to Dispatch Ready: {str(e)}")
        raise e


def create_error_dataframe(error_rows):
    """Create a pandas DataFrame from error rows for CSV export."""
    if not error_rows:
        return None
    import pandas as pd
    return pd.DataFrame(error_rows)
