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
  Phase 2 — pure Python: classify every row against the in-memory map.
  Phase 3 — four DB calls: executemany for invoice INSERTs, PO UPDATEs,
             Order INSERTs, and StateHistory INSERTs (+ one more for flagged POs).
Total DB round-trips: ~6 regardless of row count (was ~5 × N before).
"""

from datetime import datetime

from ..models import (
    PotentialOrder, OrderState, OrderStateHistory, Invoice, Order,
    InvoiceProcessingConfig,
)
from ..business.dealer_business import get_or_create_dealer
from ..db_manager import mysql_manager, partition_filter


# States from which an invoice upload is never accepted (already done / too late)
# Bug 46 fix: include 'Partially Completed' so invoices cannot be re-uploaded
# against orders that have already been partially dispatched.
_TERMINAL_STATES = {'Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed'}

# States that are valid sources for the flag path (non-bypass, not yet Packed)
_PRE_PACKED_STATES = {'Open', 'Picking'}

# Fixed column order for bulk invoice INSERT — matches fields set by create_invoice_from_row.
_INVOICE_COLUMNS = (
    'potential_order_id', 'warehouse_id', 'company_id', 'dealer_id',
    'invoice_number', 'original_order_id', 'invoice_date', 'invoice_type',
    'cancellation_date', 'total_invoice_amount', 'invoice_header_type',
    'order_date', 'b2b_purchase_order_number', 'b2b_order_type',
    'account_tin', 'cash_customer_name', 'contact_first_name',
    'contact_last_name', 'customer_category',
    'round_off_amount', 'invoice_round_off_amount', 'short_amount', 'realized_amount',
    'hmcgl_card_no', 'campaign',
    'packaging_forwarding_charges', 'tax_on_pf', 'type_of_tax_pf',
    'irn_number', 'irn_status', 'ack_number', 'ack_date',
    'credit_note_number', 'irn_cancel', 'irn_status_cancel',
    'ack_number_cancel', 'ack_date_cancel',
    'uploaded_by', 'upload_batch_id', 'created_at', 'updated_at',
)


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

    print(f"Processing DataFrame with {len(df)} rows for batch {upload_batch_id}")
    print(f"DataFrame columns: {df.columns.tolist()}")

    # ── Phase 1: one-time DB lookups ─────────────────────────────────────────
    bypass_types = InvoiceProcessingConfig.get_bypass_order_types()
    print(f"Active bypass order types: {bypass_types}")

    unique_order_ids = list({
        str(row.get('Order #', '') or '').strip()
        for _, row in df.iterrows()
        if str(row.get('Order #', '') or '').strip()
    })
    potential_orders_map = PotentialOrder.find_bulk_by_original_order_ids(unique_order_ids)
    print(f"Pre-fetched {len(potential_orders_map)}/{len(unique_order_ids)} potential orders (1 query)")

    invoiced_state = _get_or_create_state('Invoiced', 'Invoice uploaded for order')

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

            if current_status in _TERMINAL_STATES:
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
            print(f"Row {index}: Unexpected error: {str(e)}")

    # ── Phase 3: bulk DB writes ───────────────────────────────────────────────
    invoices_saved = _bulk_insert_invoices(invoices_to_create)
    _bulk_transition_to_invoiced(
        orders_to_invoice, dealer_backfills, invoiced_state.state_id, user_id, current_time
    )
    _bulk_migrate_products_to_order(orders_to_invoice, current_time)
    _bulk_flag_orders(orders_to_flag, current_time)

    print(
        f"Processing complete: {invoices_saved} invoices created, "
        f"{len(orders_to_invoice)} orders invoiced, "
        f"{len(orders_to_flag)} orders flagged, "
        f"{len(error_rows)} errors"
    )

    return {
        'invoices_processed': invoices_saved,
        'orders_invoiced': len(orders_to_invoice),
        'orders_flagged': len(orders_to_flag),
        'error_rows': error_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bulk write helpers (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

def _bulk_insert_invoices(invoices):
    """INSERT all invoice rows in a single executemany call."""
    if not invoices:
        return 0

    col_str = ', '.join(_INVOICE_COLUMNS)
    ph_str  = ', '.join(['%s'] * len(_INVOICE_COLUMNS))
    # INSERT IGNORE so duplicate invoice_numbers are skipped without aborting the batch
    sql = f"INSERT IGNORE INTO invoice ({col_str}) VALUES ({ph_str})"

    rows = [tuple(getattr(inv, col) for col in _INVOICE_COLUMNS) for inv in invoices]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(sql, rows)
        return cursor.rowcount


def _bulk_transition_to_invoiced(orders_to_invoice, dealer_backfills, state_id, user_id, current_time):
    """
    Transition a batch of PotentialOrders to Invoiced in three executemany calls:
      1. UPDATE potential_order  — status + dealer backfill
      2. INSERT `order`          — one row per unique potential order (box_count, no box rows)
      3. INSERT order_state_history
    """
    if not orders_to_invoice:
        return

    ts_str = current_time.strftime('%Y%m%d%H%M')

    # 1. Bulk UPDATE potential_orders
    po_params = [
        (dealer_backfills.get(pot_id), current_time, pot_id)
        for pot_id in orders_to_invoice
    ]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """UPDATE potential_order
               SET status = 'Invoiced',
                   invoice_submitted = 0,
                   dealer_id = COALESCE(dealer_id, %s),
                   updated_at = %s
               WHERE potential_order_id = %s""",
            po_params
        )

    # 2. Bulk INSERT Order records (box_count stored directly; no order_box rows created)
    order_params = [
        (
            pot_id,
            f"ORD-{pot_id}-{ts_str}",
            'Invoiced',
            po.box_count or 1,
            current_time,
            current_time,
        )
        for pot_id, po in orders_to_invoice.items()
    ]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT IGNORE INTO `order`
               (potential_order_id, order_number, status, box_count, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            order_params
        )

    # 3. Bulk INSERT state history
    hist_params = [
        (pot_id, state_id, user_id, current_time)
        for pot_id in orders_to_invoice
    ]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT INTO order_state_history
               (potential_order_id, state_id, changed_by, changed_at)
               VALUES (%s, %s, %s, %s)""",
            hist_params
        )


def _bulk_migrate_products_to_order(orders_to_invoice, current_time):
    """
    Copy potential_order_product rows into order_product for all just-invoiced orders.

    Two SELECTs + one executemany INSERT — runs after _bulk_transition_to_invoiced
    has committed the `order` records.
    """
    if not orders_to_invoice:
        return

    pot_ids = list(orders_to_invoice.keys())
    placeholders = ','.join(['%s'] * len(pot_ids))

    # 1. Fetch order_id for each potential_order_id (just inserted above)
    pf_sql_o, pf_params_o = partition_filter('order')
    order_rows = mysql_manager.execute_query(
        f"SELECT order_id, potential_order_id FROM `order` "
        f"WHERE {pf_sql_o} AND potential_order_id IN ({placeholders})",
        pf_params_o + tuple(pot_ids)
    )
    if not order_rows:
        return

    pot_to_order = {r['potential_order_id']: r['order_id'] for r in order_rows}

    # 2. Bulk fetch all product rows for those potential orders
    pf_sql_p, pf_params_p = partition_filter('potential_order_product')
    pop_rows = mysql_manager.execute_query(
        f"SELECT potential_order_id, product_id, quantity, mrp, total_price "
        f"FROM potential_order_product "
        f"WHERE {pf_sql_p} AND potential_order_id IN ({placeholders})",
        pf_params_p + tuple(pot_ids)
    )
    if not pop_rows:
        return

    # 3. Bulk INSERT into order_product
    op_rows = [
        (
            pot_to_order[r['potential_order_id']],
            r['product_id'],
            r['quantity'],
            r['mrp'],
            r['total_price'],
            current_time,
            current_time,
        )
        for r in pop_rows
        if r['potential_order_id'] in pot_to_order
    ]

    if op_rows:
        with mysql_manager.get_cursor() as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO order_product
                   (order_id, product_id, quantity, mrp, total_price, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                op_rows
            )
        print(f"Migrated {len(op_rows)} product rows to order_product for {len(pot_to_order)} orders")


def _migrate_products_to_order_single(potential_order_id, order_id, current_time):
    """
    Copy potential_order_product rows into order_product for a single order.
    Used by the single-order invoicing path.
    """
    pf_sql, pf_params = partition_filter('potential_order_product')
    pop_rows = mysql_manager.execute_query(
        f"SELECT product_id, quantity, mrp, total_price FROM potential_order_product "
        f"WHERE {pf_sql} AND potential_order_id = %s",
        pf_params + (potential_order_id,)
    )
    if not pop_rows:
        return

    op_rows = [
        (order_id, r['product_id'], r['quantity'], r['mrp'], r['total_price'], current_time, current_time)
        for r in pop_rows
    ]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT IGNORE INTO order_product
               (order_id, product_id, quantity, mrp, total_price, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            op_rows
        )
    print(f"Migrated {len(op_rows)} product rows to order_product for order {order_id}")


def _bulk_flag_orders(orders_to_flag, current_time):
    """Set invoice_submitted=1 on a batch of PotentialOrders in one executemany call."""
    if not orders_to_flag:
        return
    params = [(current_time, pot_id) for pot_id in orders_to_flag]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """UPDATE potential_order
               SET invoice_submitted = 1, updated_at = %s
               WHERE potential_order_id = %s""",
            params
        )


# ─────────────────────────────────────────────────────────────────────────────
# Single-order transition (used by routes.py auto-transition hook)
# ─────────────────────────────────────────────────────────────────────────────

def update_order_to_invoiced(potential_order, user_id):
    """
    Transition a single potential order to Invoiced state.

    Used by the Packed auto-transition hook when a flagged order reaches Packed.
    For bulk invoice uploads use _bulk_transition_to_invoiced instead.
    """
    current_time = datetime.utcnow()

    potential_order.status = 'Invoiced'
    potential_order.invoice_submitted = False
    potential_order.updated_at = current_time
    potential_order.save()

    final_order = Order.find_by_potential_order_id(potential_order.potential_order_id)
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
        print(f"Created Order record at Invoiced for order {potential_order.original_order_id}")
    else:
        final_order.status = 'Invoiced'
        final_order.updated_at = current_time
        final_order.save()
        print(f"Updated Order record to Invoiced for order {potential_order.original_order_id}")

    invoiced_state = _get_or_create_state('Invoiced', 'Invoice uploaded for order')
    OrderStateHistory(
        potential_order_id=potential_order.potential_order_id,
        state_id=invoiced_state.state_id,
        changed_by=user_id,
        changed_at=current_time
    ).save()

    _migrate_products_to_order_single(
        potential_order.potential_order_id, final_order.order_id, current_time
    )

    print(f"Moved order {potential_order.original_order_id} to Invoiced")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_state(state_name: str, description: str) -> OrderState:
    state = OrderState.find_by_name(state_name)
    if not state:
        state = OrderState(state_name=state_name, description=description)
        state.save()
    return state


def _make_error_row(row, order_id, reason):
    name = str(row.get('Account Name', '') or row.get('Cash Customer Name', '') or '').strip()
    return {'order_id': order_id or '', 'name': name, 'reason': reason}


def _resolve_dealer(row, index):
    """Look up or create dealer from invoice row's Code + Account Name."""
    dealer_code  = str(row.get('Code', '') or '').strip() or None
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
    Do not call .save() on the result — pass the object to _bulk_insert_invoices instead.
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
