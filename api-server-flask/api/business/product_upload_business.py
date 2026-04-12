# -*- encoding: utf-8 -*-
"""
Product Upload Business Logic for MySQL.

Performance design
──────────────────
process_product_upload_dataframe runs in three phases:
  Phase 1 — two DB calls:
             1. Bulk pre-fetch all potential orders by Order #
             2. Bulk pre-fetch all existing products by Part #
  Phase 2 — pure Python: classify every row against in-memory maps (zero DB calls).
  Phase 3 — four DB calls:
             1. INSERT IGNORE new products into product table
             2. Re-fetch newly inserted product IDs
             3. DELETE existing potential_order_product rows for affected orders (replace mode)
             4. INSERT new potential_order_product rows via executemany
Total DB round-trips: ~5 regardless of row count.
"""

from datetime import datetime

from ..models import PotentialOrder
from ..db_manager import mysql_manager, partition_filter


def process_product_upload_dataframe(df, company_id, user_id, upload_batch_id=None):
    """
    Process a dataframe of product data and link products to orders.

    CSV columns used: Order #, Part Description, Part #, Reserved Qty

    Args:
        df:               Pandas DataFrame
        company_id:       Company ID (used for scoping)
        user_id:          ID of user performing the upload
        upload_batch_id:  Upload batch tracking ID

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

    orders_map = PotentialOrder.find_bulk_by_original_order_ids(unique_order_ids)
    print(f"Pre-fetched {len(orders_map)}/{len(unique_order_ids)} potential orders (1 query)")

    products_map = _bulk_fetch_products(unique_part_numbers)
    print(f"Pre-fetched {len(products_map)}/{len(unique_part_numbers)} existing products (1 query)")

    # ── Phase 2: classify rows in memory (zero DB calls) ─────────────────────
    # order_products: potential_order_id → list of (part_no, description, qty)
    order_products = {}
    new_products = {}          # part_no → description (to be created)
    error_rows = []
    processed_line_keys = set()   # (potential_order_id, part_no) — skip duplicates within upload

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
                error_rows.append({'order_id': original_order_id, 'name': '', 'reason': f"Row {index}: Missing Part #"})
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
            print(f"Row {index}: Unexpected error: {str(e)}")

    if not order_products:
        return {'products_processed': 0, 'orders_updated': 0, 'error_rows': error_rows}

    # ── Phase 3: bulk DB writes ───────────────────────────────────────────────

    # 3a. INSERT IGNORE new products; re-fetch to get their IDs
    if new_products:
        _bulk_insert_products(new_products, current_time)
        fresh = _bulk_fetch_products(list(new_products.keys()))
        products_map.update(fresh)
        print(f"Inserted {len(new_products)} new products")

    # 3b. DELETE existing potential_order_product rows for affected orders (replace mode)
    affected_order_ids = list(order_products.keys())
    _bulk_delete_order_products(affected_order_ids)
    print(f"Cleared existing products for {len(affected_order_ids)} orders")

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

    products_saved = _bulk_insert_order_products(pop_rows)

    print(
        f"Product upload complete: {products_saved} product lines, "
        f"{len(order_products)} orders updated, {len(error_rows)} errors"
    )

    return {
        'products_processed': products_saved,
        'orders_updated': len(order_products),
        'error_rows': error_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Bulk helpers
# ─────────────────────────────────────────────────────────────────────────────

def _bulk_fetch_products(part_numbers):
    """Fetch products by product_string in one IN query. Returns dict: part_no → row dict."""
    if not part_numbers:
        return {}
    placeholders = ','.join(['%s'] * len(part_numbers))
    results = mysql_manager.execute_query(
        f"SELECT product_id, product_string, name, description "
        f"FROM product WHERE product_string IN ({placeholders})",
        tuple(part_numbers)
    )
    return {r['product_string']: r for r in results} if results else {}


def _bulk_insert_products(new_products, current_time):
    """INSERT IGNORE new products (product_string, name, description) into the product table."""
    rows = [
        (part_no, description, description, current_time, current_time)
        for part_no, description in new_products.items()
    ]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT IGNORE INTO product
               (product_string, name, description, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s)""",
            rows
        )


def _bulk_delete_order_products(potential_order_ids):
    """DELETE all potential_order_product rows for the given potential_order_ids (partition-aware)."""
    if not potential_order_ids:
        return
    pf_sql, pf_params = partition_filter('potential_order_product')
    placeholders = ','.join(['%s'] * len(potential_order_ids))
    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            f"DELETE FROM potential_order_product "
            f"WHERE {pf_sql} AND potential_order_id IN ({placeholders})",
            pf_params + tuple(potential_order_ids)
        )


def _bulk_insert_order_products(rows):
    """INSERT potential_order_product rows in one executemany call."""
    if not rows:
        return 0
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT INTO potential_order_product
               (potential_order_id, product_id, quantity, quantity_packed,
                quantity_remaining, mrp, total_price, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows
        )
        return cursor.rowcount
