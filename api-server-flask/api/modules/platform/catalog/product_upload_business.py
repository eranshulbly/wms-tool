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

from api.repositories import order_repo, product_repo
from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)


def _money(value):
    """A price cell as a float, or None when absent/unparseable.

    None, not 0: a line that simply was not priced must stay distinguishable from one
    priced at nothing, because the UI shows the first as blank and the second as a real
    zero.
    """
    if value is None:
        return None
    s = str(value).replace(',', '').replace('\u20b9', '').strip()
    if not s or s.lower() in ('nan', 'none', '-'):
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def _batch_key(product_id, batch_number, expiry_date):
    """Identity of a batch, matching how inventory ingestion hashes it."""
    from api.modules.inventory.ingestion.service import batch_hash
    return batch_hash(product_id, batch_number, expiry_date)


def _resolve_batch_ids(order_products, products_map):
    """{batch_hash: sku_batch.id} for every batch named across the upload.

    One query regardless of row count. Batches are created by inventory ingestion at
    receipt, so this only ever reads them — an outbound document must not invent a batch,
    because that would assert stock arrived when it never did.
    """
    hashes = set()
    for lines in order_products.values():
        for part_no, _desc, _qty, batch_number, expiry_date, _mrp, _rate in lines:
            product = products_map.get(part_no)
            if product and batch_number:
                hashes.add(_batch_key(product['product_id'], batch_number, expiry_date))
    if not hashes:
        return {}
    from api.shared.db_manager import mysql_manager
    placeholders = ','.join(['%s'] * len(hashes))
    rows = mysql_manager.execute_query(
        f"SELECT id, batch_hash FROM sku_batch WHERE batch_hash IN ({placeholders})",
        tuple(hashes))
    return {r['batch_hash']: r['id'] for r in (rows or [])}


def process_product_upload_dataframe(df, company_id, _user_id, _upload_batch_id=None):
    """
    Process a dataframe of product data and link products to orders.

    CSV columns used: Order #, Part Description, Part #, Reserved Qty
    Optional (PDF invoices only): Batch #, Expiry

    Args:
        df:               Pandas DataFrame
        company_id:       Owning company for products this upload has to create. Comes
                          from the uploader's selection, never from a column in the file.
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
    # order_products: potential_order_id → list of
    #   (part_no, description, qty, batch_number, expiry_date, mrp, rate)
    # The price travels WITH the line. Reading it back in phase 3 from the loop variable
    # would take the last row of this loop for every line of every order.
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
            # Batch text comes from PDF invoices; spreadsheet feeds leave it blank. It is
            # not stored — phase 3 resolves it to a sku_batch id, which is the only place
            # batch number and expiry live.
            order_products[pot_id].append((
                part_no, description, qty,
                str(row.get('Batch #', '') or '').strip() or None,
                row.get('Expiry') if str(row.get('Expiry', '') or '').strip() else None,
                _money(row.get('MRP')),
                _money(row.get('Rate')),
            ))

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
        product_repo.bulk_insert_products(new_products, current_time, company_id)
        fresh = product_repo.find_bulk_by_part_numbers(list(new_products.keys()))
        products_map.update(fresh)
        logger.debug("Inserted new products", extra={'count': len(new_products)})

    # 3b. DELETE existing potential_order_product rows for affected orders (replace mode)
    affected_order_ids = list(order_products.keys())
    product_repo.bulk_delete_order_products(affected_order_ids)
    logger.debug("Cleared existing products for orders",
                 extra={'order_count': len(affected_order_ids)})

    # 3c. Build and INSERT new potential_order_product rows
    # Resolve every (product, batch, expiry) to its sku_batch id in ONE query, keeping
    # this phase's round-trip count flat. The batch is created by inventory ingestion when
    # the stock is received; a line whose batch is absent is selling stock that was never
    # taken in, so it is reported rather than silently losing its traceability.
    batch_ids = _resolve_batch_ids(order_products, products_map)

    pop_rows = []
    for pot_id, lines in order_products.items():
        for part_no, _description, qty, batch_number, expiry_date, mrp, rate in lines:
            product = products_map.get(part_no)
            if not product:
                error_rows.append({
                    'order_id': '',
                    'name': '',
                    'reason': f"Product {part_no} could not be created or found"
                })
                continue
            batch_id = None
            if batch_number:
                batch_id = batch_ids.get(
                    _batch_key(product['product_id'], batch_number, expiry_date))
                if batch_id is None:
                    error_rows.append({
                        'order_id': '', 'name': part_no,
                        'reason': (f"Batch {batch_number} of {part_no} is not in inventory "
                                   f"— receive it before selling it"),
                    })

            # Price, when the file carries it. Feeds that do not price their lines
            # (Hero's order sheets) leave these NULL rather than 0 — a zero rate reads
            # as "free", which is a different claim from "not priced here".
            total = round(rate * qty, 2) if rate is not None else None

            pop_rows.append((
                pot_id,
                product['product_id'],
                qty,
                0,          # quantity_packed
                qty,        # quantity_remaining
                mrp,
                rate,       # net_rate — per unit, what this line is billed at
                total,      # total_price = rate x quantity
                current_time,
                current_time,
                batch_id,
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


# ── Auto-generated part numbers ──────────────────────────────────────────────
# `Part #` is how a row finds its product: it matches `product.product_string`, which is
# UNIQUE across the whole table. Some catalogues arrive without it — the supplier names
# products but assigns them no code. Rather than rejecting the file, a code can be
# derived from the description, but only with the operator's say-so: these codes become
# permanent catalogue identifiers, and a generated one cannot later be reconciled with
# whatever code the supplier eventually issues.

PART_NUMBER_COLUMN = 'Part #'


def _company_prefix(company_id):
    from api.modules.inventory.ingestion.service import _slug
    rows = mysql_manager.execute_query(
        "SELECT name FROM company WHERE company_id = %s", (company_id,)) if company_id else None
    return (_slug(rows[0]['name'], 4) if rows else '') or 'PROD'


def rows_missing_part_number(df):
    """Row indexes whose Part # is absent or blank."""
    if PART_NUMBER_COLUMN not in df.columns:
        return list(df.index)
    return [i for i, v in df[PART_NUMBER_COLUMN].items()
            if not str(v if v is not None else '').strip()
            or str(v).strip().lower() == 'nan']


def generate_part_numbers(df, company_id, indexes=None):
    """Fill blank Part # values with codes derived from the description.

    Returns [(index, description, generated_code)] for what it filled in.

    Codes follow the same <PREFIX>-<slug> shape the inventory ingestion flow uses, so a
    product created here and one created from a supplier PDF land on the SAME row rather
    than splitting that product's stock across two codes. Uniqueness is checked against
    the table AND against codes minted earlier in this same file, which the database
    cannot yet see.
    """
    from api.modules.inventory.ingestion.service import _slug

    if PART_NUMBER_COLUMN not in df.columns:
        df[PART_NUMBER_COLUMN] = ''
    if indexes is None:
        indexes = rows_missing_part_number(df)

    prefix = _company_prefix(company_id)
    taken = set()
    generated = []

    for idx in indexes:
        description = str(df.at[idx, 'Part Description'] or '').strip()
        base = f"{prefix}-{_slug(description)}"[:90] if description else f"{prefix}-ITEM"
        candidate, n = base, 1
        while True:
            clash = candidate in taken or mysql_manager.execute_query(
                "SELECT 1 FROM product WHERE product_string = %s LIMIT 1", (candidate,))
            if not clash:
                break
            n += 1
            candidate = f"{base[:90 - len(str(n)) - 1]}-{n}"
        taken.add(candidate)
        df.at[idx, PART_NUMBER_COLUMN] = candidate
        generated.append((idx, description, candidate))

    logger.info("Generated part numbers", extra={'count': len(generated),
                                                 'company_id': company_id})
    return generated
