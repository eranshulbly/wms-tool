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

Performance design
──────────────────
process_invoice_dataframe runs in three phases to eliminate N+1 queries:
  Phase 1 — two DB calls: bulk pre-fetch all potential orders + load state id.
  Phase 2 — pure Python: classify every row against the in-memory map (zero DB).
  Phase 3 — repository calls: bulk invoice INSERTs, PO UPDATEs, Order INSERTs,
             StateHistory INSERTs, flagged PO UPDATEs.
Total DB round-trips: ~6 regardless of row count.
"""

from datetime import datetime

from ..models import Invoice, Order
from ..business.dealer_business import get_or_create_dealer
from ..business.order_state_machine import OrderStateMachine
from ..repositories import order_repo, invoice_repo
from ..core.logging import get_logger

logger = get_logger(__name__)


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
    current_time = datetime.utcnow()

    logger.debug("Processing invoice DataFrame",
                 extra={'row_count': len(df), 'batch_id': upload_batch_id,
                        'columns': df.columns.tolist()})

    # ── Phase 1: one-time DB lookups ─────────────────────────────────────────
    bypass_types = invoice_repo.get_bypass_order_types()
    logger.debug("Loaded bypass order types", extra={'bypass_types': list(bypass_types)})

    unique_order_ids = list({
        str(row.get('Order #', '') or '').strip()
        for _, row in df.iterrows()
        if str(row.get('Order #', '') or '').strip()
    })
    potential_orders_map = order_repo.find_bulk_by_original_ids(unique_order_ids)
    logger.debug("Pre-fetched potential orders",
                 extra={'fetched': len(potential_orders_map), 'requested': len(unique_order_ids)})

    invoiced_state = order_repo.get_or_create_state('Invoiced', 'Invoice uploaded for order')

    # ── Phase 2: classify every row in memory (zero DB calls) ────────────────
    invoices_to_create = []       # Invoice objects ready for bulk INSERT
    orders_to_invoice  = {}       # pot_order_id → PotentialOrder (deduped)
    orders_to_flag     = {}       # pot_order_id → PotentialOrder (deduped)
    dealer_backfills   = {}       # pot_order_id → dealer_id (for COALESCE update)
    error_rows         = []
    processed_order_ids = set()

    for index, row in df.iterrows():
        try:
            invoice_number    = str(row.get('Invoice #', '') or '').strip()
            original_order_id = str(row.get('Order #', '') or '').strip()

            if not invoice_number or not original_order_id:
                error_rows.append(_make_error_row(row, original_order_id, "Missing Invoice # or Order #"))
                continue

            potential_order = potential_orders_map.get(original_order_id)
            if not potential_order:
                error_rows.append(_make_error_row(
                    row, original_order_id,
                    f"No matching order found for Order #: {original_order_id}"
                ))
                continue

            current_status = potential_order.status

            if OrderStateMachine.is_terminal(current_status):
                error_rows.append(_make_error_row(
                    row, original_order_id,
                    f"Order already invoiced (current status: '{current_status}'). "
                    "Invoice may be a duplicate."
                ))
                continue

            is_bypass = potential_order.order_type in bypass_types
            is_packed = current_status == 'Packed'

            if is_bypass or is_packed:
                dealer_id = _resolve_dealer(row, index)

                if dealer_id and not potential_order.dealer_id:
                    dealer_backfills[potential_order.potential_order_id] = dealer_id
                    potential_order.dealer_id = dealer_id  # keep in-memory copy consistent

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
                    invoices_to_create.append(invoice)
                except Exception as e:
                    reason = (
                        f"Invoice {invoice_number} already exists"
                        if '1062' in str(e) or 'Duplicate entry' in str(e)
                        else f"Error preparing invoice: {str(e)}"
                    )
                    error_rows.append(_make_error_row(row, original_order_id, reason))
                    continue

                if potential_order.potential_order_id not in processed_order_ids:
                    orders_to_invoice[potential_order.potential_order_id] = potential_order
                    processed_order_ids.add(potential_order.potential_order_id)

            else:
                # Path B: flag the order (Open/Picking, non-bypass)
                if potential_order.potential_order_id not in processed_order_ids:
                    if not potential_order.invoice_submitted:
                        orders_to_flag[potential_order.potential_order_id] = potential_order
                    processed_order_ids.add(potential_order.potential_order_id)

        except Exception as e:
            original_order_id = str(row.get('Order #', '') or '').strip()
            error_rows.append(_make_error_row(row, original_order_id, f"Unexpected error: {str(e)}"))
            logger.exception("Unexpected error processing invoice row", extra={'row': index})

    # ── Phase 3: bulk DB writes via repositories ──────────────────────────────
    invoices_saved = invoice_repo.bulk_insert_invoices(invoices_to_create)
    invoice_repo.bulk_transition_to_invoiced(
        orders_to_invoice, dealer_backfills, invoiced_state.state_id, user_id, current_time
    )
    invoice_repo.bulk_migrate_products_to_order(orders_to_invoice, current_time)
    invoice_repo.bulk_flag_orders(orders_to_flag, current_time)

    logger.info(
        "Invoice processing complete",
        extra={
            'invoices_created': invoices_saved,
            'orders_invoiced': len(orders_to_invoice),
            'orders_flagged': len(orders_to_flag),
            'error_count': len(error_rows),
        }
    )

    return {
        'invoices_processed': invoices_saved,
        'orders_invoiced': len(orders_to_invoice),
        'orders_flagged': len(orders_to_flag),
        'error_rows': error_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Single-order transition (used by routes.py auto-transition hook)
# ─────────────────────────────────────────────────────────────────────────────

def update_order_to_invoiced(potential_order, user_id):
    """
    Transition a single potential order to Invoiced state.

    Used by the Packed auto-transition hook when a flagged order reaches Packed.
    For bulk invoice uploads use the repository's bulk_transition_to_invoiced instead.
    """
    current_time = datetime.utcnow()

    potential_order.status = 'Invoiced'
    potential_order.invoice_submitted = False
    potential_order.updated_at = current_time
    potential_order.save()

    final_order = order_repo.find_order_by_potential_id(potential_order.potential_order_id)
    if not final_order:
        final_order = Order(
            potential_order_id=potential_order.potential_order_id,
            order_number=(
                f"ORD-{potential_order.potential_order_id}"
                f"-{current_time.strftime('%Y%m%d%H%M')}"
            ),
            status='Invoiced',
            box_count=potential_order.box_count or 1,
            created_at=current_time,
            updated_at=current_time
        )
        final_order.save()
        logger.debug("Created Order record at Invoiced",
                     extra={'original_order_id': potential_order.original_order_id})
    else:
        final_order.status = 'Invoiced'
        final_order.updated_at = current_time
        final_order.save()
        logger.debug("Updated Order record to Invoiced",
                     extra={'original_order_id': potential_order.original_order_id})

    invoiced_state = order_repo.get_or_create_state('Invoiced', 'Invoice uploaded for order')
    order_repo.create_state_history(
        potential_order.potential_order_id, invoiced_state.state_id, user_id, current_time
    )

    invoice_repo.migrate_products_to_order_single(
        potential_order.potential_order_id, final_order.order_id, current_time
    )

    logger.info("Order moved to Invoiced",
                extra={'original_order_id': potential_order.original_order_id})


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (pure Python — no DB access)
# ─────────────────────────────────────────────────────────────────────────────

def _make_error_row(row, order_id, reason):
    name = str(row.get('Account Name', '') or row.get('Cash Customer Name', '') or '').strip()
    return {'order_id': order_id or '', 'name': name, 'reason': reason}


def _resolve_dealer(row, index):
    """Look up or create dealer from invoice row's Code + Account Name."""
    dealer_code  = str(row.get('Code', '') or '').strip() or None
    account_name = str(row.get('Account Name', '') or '').strip() or None

    if not dealer_code and not account_name:
        logger.debug("No dealer Code or Account Name — invoice saved without dealer link",
                     extra={'row': index})
        return None

    try:
        return get_or_create_dealer(dealer_name=account_name or dealer_code, dealer_code=dealer_code)
    except Exception as e:
        logger.warning("Error resolving dealer",
                       extra={'row': index, 'dealer_code': dealer_code, 'error': str(e)})
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Invoice record creation (pure Python — returns an unsaved Invoice object)
# ─────────────────────────────────────────────────────────────────────────────

def create_invoice_from_row(row, potential_order_id, warehouse_id, company_id,
                             dealer_id, user_id, upload_batch_id):
    """
    Create an Invoice object from a DataFrame row.
    Do not call .save() — pass the object to invoice_repo.bulk_insert_invoices() instead.
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
                for fmt in ('%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
                            '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %I:%M:%S %p'):
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
