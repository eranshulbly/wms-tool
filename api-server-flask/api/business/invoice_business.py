# -*- encoding: utf-8 -*-
"""
Invoice Business Logic for MySQL.

State-transition rules for invoice upload
──────────────────────────────────────────
1. Bypass order types (e.g. ZGOI, from invoice_processing_config):
     Any state in {Open, Picking, Packed} → create invoice record + move to Invoiced.

2. Non-bypass orders in Packed state:
     Create invoice record + move to Invoiced.

3. Non-bypass orders NOT yet in Packed (Open / Picking):
     Do NOT create invoice record.
     Set invoice_submitted = True flag on the order.
     When the user later moves the order to Packed in Order Management,
     the backend auto-transitions it to Invoiced and clears the flag.

4. Orders already in {Invoiced, Dispatch Ready, Completed}:
     Treated as duplicates — added to the error report.
"""

from datetime import datetime

from ..models import (
    PotentialOrder, OrderState, OrderStateHistory, Invoice, Order,
    InvoiceProcessingConfig,
)
from ..business.dealer_business import get_or_create_dealer


# States from which an invoice upload is never accepted (already done / too late)
_TERMINAL_STATES = {'Invoiced', 'Dispatch Ready', 'Completed'}

# States that are valid sources for the flag path (non-bypass, not yet Packed)
_PRE_PACKED_STATES = {'Open', 'Picking'}


def process_invoice_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None):
    """
    Process a dataframe of invoice data and update order statuses.

    Returns:
        dict with keys:
          invoices_processed  — invoice records created in DB
          orders_invoiced     — orders transitioned to Invoiced
          orders_flagged      — orders that received the invoice_submitted flag
          error_rows          — list of row-level errors
    """
    invoices_processed = 0
    orders_invoiced = 0
    orders_flagged = 0
    error_rows = []

    print(f"Processing DataFrame with {len(df)} rows for batch {upload_batch_id}")
    print(f"DataFrame columns: {df.columns.tolist()}")

    bypass_types = InvoiceProcessingConfig.get_bypass_order_types()
    print(f"Active bypass order types: {bypass_types}")

    # Track orders already processed this upload to avoid duplicate transitions
    processed_order_ids = set()

    for index, row in df.iterrows():
        try:
            # ── Required fields ──────────────────────────────────────────────
            invoice_number = str(row.get('Invoice #', '') or '').strip()
            original_order_id = str(row.get('Order #', '') or '').strip()

            if not invoice_number or not original_order_id:
                error_rows.append(_make_error_row(row, original_order_id, "Missing Invoice # or Order #"))
                continue

            print(f"Row {index}: Processing invoice {invoice_number} for order {original_order_id}")

            # ── Match potential order ─────────────────────────────────────────
            potential_order = PotentialOrder.find_by_original_order_id(
                original_order_id, warehouse_id, company_id
            )
            if not potential_order:
                error_rows.append(_make_error_row(
                    row, original_order_id,
                    f"No matching order found for Order #: {original_order_id}"
                ))
                continue

            current_status = potential_order.status

            # ── Reject terminal states (duplicate / already processed) ────────
            if current_status in _TERMINAL_STATES:
                error_rows.append(_make_error_row(
                    row, original_order_id,
                    f"Order already invoiced (current status: '{current_status}'). "
                    "Invoice may be a duplicate."
                ))
                continue

            # ── Determine routing ─────────────────────────────────────────────
            is_bypass = potential_order.order_type in bypass_types
            is_packed = current_status == 'Packed'
            eligible_for_invoice = is_bypass or is_packed

            if eligible_for_invoice:
                # ── Path A: create invoice record + transition to Invoiced ────
                dealer_id = _resolve_dealer(row, index)

                if dealer_id and not potential_order.dealer_id:
                    potential_order.dealer_id = dealer_id
                    potential_order.save()
                    print(f"Row {index}: Backfilled dealer_id={dealer_id} on order {original_order_id}")

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

                    if potential_order.potential_order_id not in processed_order_ids:
                        update_order_to_invoiced(potential_order, user_id)
                        processed_order_ids.add(potential_order.potential_order_id)
                        orders_invoiced += 1
                        print(f"Row {index}: Moved order {original_order_id} to Invoiced "
                              f"({'bypass type' if is_bypass else 'was Packed'})")

                except Exception as e:
                    if '1062' in str(e) or 'Duplicate entry' in str(e):
                        reason = f"Invoice {invoice_number} already exists"
                    else:
                        reason = f"Error saving invoice: {str(e)}"
                    error_rows.append(_make_error_row(row, original_order_id, reason))

            else:
                # ── Path B: flag the order (Open/Picking, non-bypass) ─────────
                if potential_order.potential_order_id not in processed_order_ids:
                    if not potential_order.invoice_submitted:
                        potential_order.invoice_submitted = True
                        potential_order.save()
                    processed_order_ids.add(potential_order.potential_order_id)
                    orders_flagged += 1
                    print(f"Row {index}: Flagged order {original_order_id} "
                          f"(status='{current_status}', not bypass, not Packed)")

        except Exception as e:
            original_order_id = str(row.get('Order #', '') or '').strip()
            error_rows.append(_make_error_row(row, original_order_id, f"Unexpected error: {str(e)}"))
            print(f"Row {index}: Unexpected error: {str(e)}")

    print(
        f"Processing complete: {invoices_processed} invoices created, "
        f"{orders_invoiced} orders invoiced, "
        f"{orders_flagged} orders flagged, "
        f"{len(error_rows)} errors"
    )

    return {
        'invoices_processed': invoices_processed,
        'orders_invoiced': orders_invoiced,
        'orders_flagged': orders_flagged,
        'error_rows': error_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# State transition helpers
# ─────────────────────────────────────────────────────────────────────────────

def update_order_to_invoiced(potential_order, user_id):
    """
    Transition a potential order to Invoiced state.

    Works regardless of the order's prior state (Packed, Open, Picking) so it
    can be called both from invoice upload and from the auto-transition hook
    that fires when a flagged order reaches Packed.
    """
    try:
        current_time = datetime.utcnow()

        potential_order.status = 'Invoiced'
        potential_order.invoice_submitted = False  # clear flag if it was set
        potential_order.updated_at = current_time
        potential_order.save()

        # Keep the associated Order record in sync
        final_order = Order.find_by_potential_order_id(potential_order.potential_order_id)
        if final_order:
            final_order.status = 'Invoiced'
            final_order.updated_at = current_time
            final_order.save()
            print(f"Updated Order record to Invoiced for order {potential_order.original_order_id}")

        invoiced_state = _get_or_create_state('Invoiced', 'Invoice uploaded for order')

        state_history = OrderStateHistory(
            potential_order_id=potential_order.potential_order_id,
            state_id=invoiced_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        state_history.save()

        print(f"Moved order {potential_order.original_order_id} to Invoiced")

    except Exception as e:
        print(f"Error updating order {potential_order.original_order_id} to Invoiced: {str(e)}")
        raise


def _get_or_create_state(state_name: str, description: str) -> OrderState:
    state = OrderState.find_by_name(state_name)
    if not state:
        state = OrderState(state_name=state_name, description=description)
        state.save()
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_error_row(row, order_id, reason):
    name = str(row.get('Account Name', '') or row.get('Cash Customer Name', '') or '').strip()
    return {'order_id': order_id or '', 'name': name, 'reason': reason}


def _resolve_dealer(row, index):
    """Look up or create dealer from invoice row's Code + Account Name."""
    dealer_code = str(row.get('Code', '') or '').strip() or None
    account_name = str(row.get('Account Name', '') or '').strip() or None

    if not dealer_code and not account_name:
        print(f"Row {index}: No dealer Code or Account Name — invoice saved without dealer link.")
        return None

    try:
        return get_or_create_dealer(dealer_name=account_name or dealer_code, dealer_code=dealer_code)
    except Exception as e:
        print(f"Row {index}: Error resolving dealer (Code={dealer_code}): {str(e)}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Invoice record creation
# ─────────────────────────────────────────────────────────────────────────────

def create_invoice_from_row(row, potential_order_id, warehouse_id, company_id,
                             dealer_id, user_id, upload_batch_id):
    """
    Create an Invoice object from a DataFrame row.
    Caller must call .save() on the returned object.
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
        potential_order_id=potential_order_id,
        warehouse_id=warehouse_id,
        company_id=company_id,
        dealer_id=dealer_id,

        invoice_number=safe_string(sg('Invoice #'), ''),
        original_order_id=safe_string(sg('Order #'), ''),
        invoice_date=safe_date(sg('Invoice Date')),
        invoice_type=safe_string(sg('Invoice Type'), ''),
        cancellation_date=safe_date(sg('Invoice Cancel Date')),
        total_invoice_amount=safe_decimal(sg('Invoice Amount')),
        invoice_header_type=safe_string(sg('Invoice Header Type'), ''),

        order_date=safe_date(sg('Order Date')),
        b2b_purchase_order_number=safe_string(sg('B2B Purchase Order #'), ''),
        b2b_order_type=safe_string(sg('B2B Order Type'), ''),

        account_tin=safe_string(sg('Account TIN#'), ''),
        cash_customer_name=safe_string(sg('Cash Customer Name'), ''),
        contact_first_name=safe_string(sg('Contact First Name'), ''),
        contact_last_name=safe_string(sg('Contact Last Name'), ''),
        customer_category=safe_string(sg('Customer Category'), ''),

        round_off_amount=safe_decimal(sg('Round Off Amount')),
        invoice_round_off_amount=safe_decimal(sg('Invoice Round Off Amount')),
        short_amount=safe_decimal(sg('Short Amount')),
        realized_amount=safe_decimal(sg('Realized Amount')),

        hmcgl_card_no=safe_string(sg('HMCGL Card No'), ''),
        campaign=safe_string(sg('Campaign'), ''),

        packaging_forwarding_charges=safe_decimal(sg('Packaging & Forwarding Charges')),
        tax_on_pf=safe_decimal(sg('Tax on Package & Forwarding')),
        type_of_tax_pf=safe_string(sg('Type of Tax P&F'), ''),

        irn_number=safe_string(sg('IRN#'), ''),
        irn_status=safe_string(sg('IRN Status'), ''),
        ack_number=safe_string(sg('Ack#'), ''),
        ack_date=safe_date(sg('Ack Date')),

        credit_note_number=safe_string(sg('Credit Note# (Canc.>24h)'), ''),
        irn_cancel=safe_string(sg('IRN# (Canc.>24h)'), ''),
        irn_status_cancel=safe_string(sg('IRN Status (Canc.>24h)'), ''),
        ack_number_cancel=safe_string(sg('Ack# (Canc.>24h)'), ''),
        ack_date_cancel=safe_date(sg('Ack Date (Canc.>24h)')),

        uploaded_by=user_id,
        upload_batch_id=upload_batch_id,
        created_at=current_time,
        updated_at=current_time
    )
