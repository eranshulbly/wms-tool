# -*- encoding: utf-8 -*-
"""
Product Upload Business Logic for MySQL.

Performance design
──────────────────
process_product_upload_dataframe runs in three phases:
  Phase 1 — two DB calls (via repositories):
             1. Bulk pre-fetch all potential orders by Order #
             2. Bulk pre-fetch all existing products by Part #
  Phase 2 — pure Python: classify every row against in-memory maps (zero DB calls).
  Phase 3 — four DB calls (via repositories):
             1. INSERT IGNORE new products into product table
             2. Re-fetch newly inserted product IDs
             3. DELETE existing potential_order_product rows for affected orders (replace mode)
             4. INSERT new potential_order_product rows via executemany
Total DB round-trips: ~5 regardless of row count.
"""

from datetime import datetime

from ..repositories import order_repo, product_repo
from ..core.logging import get_logger

logger = get_logger(__name__)


def process_product_upload_dataframe(df, _company_id, _user_id, _upload_batch_id=None):
    """
    Process a dataframe of product data and link products to orders.

    CSV columns used: Order #, Part Description, Part #, Reserved Qty

    Args:
        df:               Pandas DataFrame
        _company_id:      Company ID (part of uniform upload API; not used in SQL)
        _user_id:         User performing the upload (part of uniform upload API; not used in SQL)
        _upload_batch_id: Upload batch tracking ID (part of uniform upload API; not used in SQL)

    Returns:
        dict: { products_processed, orders_updated, error_rows }
    """
    current_time = datetime.utcnow()

    # ── Phase 1: bulk DB lookups ──────────────────────────────────────────────
    unique_order_ids = list({
        str(row.get('Order #', '') or '').strip()
        for _, row in df.iterrows()
        if str(row.get('Order #', '') or '').strip()
    })

    unique_part_numbers = list({
        str(row.get('Part #', '') or '').strip()
        for _, row in df.iterrows()
        if str(row.get('Part #', '') or '').strip()
    })

    orders_map = order_repo.find_bulk_by_original_ids(unique_order_ids)
    logger.debug("Pre-fetched orders",
                 extra={'fetched': len(orders_map), 'requested': len(unique_order_ids)})

    products_map = product_repo.find_bulk_by_part_numbers(unique_part_numbers)
    logger.debug("Pre-fetched products",
                 extra={'fetched': len(products_map), 'requested': len(unique_part_numbers)})

    # ── Phase 2: classify rows in memory (zero DB calls) ─────────────────────
    # order_products: potential_order_id → list of (part_no, description, qty)
    order_products = {}
    new_products = {}           # part_no → description (to be created)
    error_rows = []
    processed_line_keys = set()  # (potential_order_id, part_no) — skip duplicates within upload

    for index, row in df.iterrows():
        try:
            original_order_id = str(row.get('Order #', '') or '').strip()
            part_no = str(row.get('Part #', '') or '').strip()
            description = str(row.get('Part Description', '') or '').strip()
            qty_raw = row.get('Reserved Qty', '') or ''

            if not original_order_id:
                error_rows.append({'order_id': '', 'name': '', 'reason': f"Row {index}: Missing Order #"})
                continue

            if not part_no:
                error_rows.append({'order_id': original_order_id, 'name': '',
                                   'reason': f"Row {index}: Missing Part #"})
                continue

            potential_order = orders_map.get(original_order_id)
            if not potential_order:
                error_rows.append({
                    'order_id': original_order_id,
                    'name': '',
                    'reason': f"No matching order found for Order #: {original_order_id}"
                })
                continue

            try:
                qty = int(float(str(qty_raw).strip())) if str(qty_raw).strip() else 0
                if qty < 0:
                    qty = 0
            except (ValueError, TypeError):
                qty = 0

            pot_id = potential_order.potential_order_id
            line_key = (pot_id, part_no)

            # Skip duplicate line items within this upload (same order + same part)
            if line_key in processed_line_keys:
                continue
            processed_line_keys.add(line_key)

            if part_no not in products_map:
                new_products[part_no] = description or part_no

            if pot_id not in order_products:
                order_products[pot_id] = []
            order_products[pot_id].append((part_no, description, qty))

        except Exception as e:
            original_order_id = str(row.get('Order #', '') or '').strip()
            error_rows.append({
                'order_id': original_order_id,
                'name': '',
                'reason': f"Unexpected error: {str(e)}"
            })
            logger.exception("Unexpected error processing product row", extra={'row': index})

    if not order_products:
        return {'products_processed': 0, 'orders_updated': 0, 'error_rows': error_rows}

    # ── Phase 3: bulk DB writes via repositories ──────────────────────────────

    # 3a. INSERT IGNORE new products; re-fetch to get their IDs
    if new_products:
        product_repo.bulk_insert_products(new_products, current_time)
        fresh = product_repo.find_bulk_by_part_numbers(list(new_products.keys()))
        products_map.update(fresh)
        logger.debug("Inserted new products", extra={'count': len(new_products)})

    # 3b. DELETE existing potential_order_product rows for affected orders (replace mode)
    affected_order_ids = list(order_products.keys())
    product_repo.bulk_delete_order_products(affected_order_ids)
    logger.debug("Cleared existing products for orders",
                 extra={'order_count': len(affected_order_ids)})

    # 3c. Build and INSERT new potential_order_product rows
    pop_rows = []
    for pot_id, lines in order_products.items():
        for part_no, _description, qty in lines:
            product = products_map.get(part_no)
            if not product:
                error_rows.append({
                    'order_id': '',
                    'name': '',
                    'reason': f"Product {part_no} could not be created or found"
                })
                continue
            pop_rows.append((
                pot_id,
                product['product_id'],
                qty,
                0,          # quantity_packed
                qty,        # quantity_remaining
                None,       # mrp
                None,       # total_price
                current_time,
                current_time,
            ))

    products_saved = product_repo.bulk_insert_order_products(pop_rows)

    logger.info(
        "Product upload complete",
        extra={
            'product_lines': products_saved,
            'orders_updated': len(order_products),
            'error_count': len(error_rows),
        }
    )

    return {
        'products_processed': products_saved,
        'orders_updated': len(order_products),
        'error_rows': error_rows,
    }
