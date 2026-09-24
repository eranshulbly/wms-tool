# -*- encoding: utf-8 -*-
"""
ProductRepository — all SQL for the product upload pipeline.

Covers the product table and potential_order_product linking table.
"""

from api.core.logging import get_logger
from api.shared.base_repository import BaseRepository

logger = get_logger(__name__)


class ProductRepository(BaseRepository):
    """Data access layer for product and order-product linking tables."""

    def find_bulk_by_part_numbers(self, part_numbers: list) -> dict:
        """
        Fetch products by product_string in one IN query.

        Returns:
            dict mapping product_string → row dict (with product_id, etc.)
        """
        if not part_numbers:
            return {}
        placeholders = ','.join(['%s'] * len(part_numbers))
        rows = self._db.execute_query(
            f"SELECT product_id, product_string, name, description "
            f"FROM product WHERE product_string IN ({placeholders})",
            tuple(part_numbers)
        )
        return {r['product_string']: r for r in rows} if rows else {}

    def bulk_insert_products(self, new_products: dict, current_time, company_id=None) -> None:
        """
        INSERT IGNORE new products (product_string, name, description) into the product table.

        Args:
            new_products: dict mapping part_no → description
            current_time: datetime to use for created_at / updated_at
            company_id:   owning company for the new rows. Products auto-created by an
                          upload used to land with company_id NULL, which hides them from
                          every company-scoped user and from the New Order picker. The
                          uploader always chooses a company, so pass it through.
        """
        rows = [
            (part_no, description, description, company_id, current_time, current_time)
            for part_no, description in new_products.items()
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO product
                   (product_string, name, description, company_id, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                rows
            )

    # ── Cursor-scoped variants ────────────────────────────────────────────────
    # The methods above each open their own cursor, which commits on exit. The
    # pick-list importer ingests one PDF as one transaction — products, order lines
    # and the order_picklist row land together or not at all — so it needs to drive
    # the writes on a cursor it already holds. Same SQL, caller's transaction.

    def find_bulk_by_part_numbers_on(self, cursor, part_numbers: list) -> dict:
        """find_bulk_by_part_numbers, but on the caller's cursor.

        This has to exist. The plain version borrows its own connection from the pool,
        so it cannot see rows the caller has inserted but not yet committed — a
        pick-list import that auto-creates a product and then looks it up would find
        nothing and report the part as unresolved.
        """
        if not part_numbers:
            return {}
        placeholders = ','.join(['%s'] * len(part_numbers))
        cursor.execute(
            f"SELECT product_id, product_string, name, description "
            f"FROM product WHERE product_string IN ({placeholders})",
            tuple(part_numbers),
        )
        rows = cursor.fetchall()
        return {r['product_string']: r for r in rows} if rows else {}

    def bulk_upsert_products_on(self, cursor, products: list, current_time,
                                company_id=None) -> None:
        """Create products a pick list named that the catalogue does not have.

        `products` is a list of {'part', 'name', 'hsn', 'price'}.

        Unlike bulk_insert_products(), this carries hsn_code and price through. A
        pick list prints both, and dropping them would leave an auto-created product
        emptier than the document that created it. Existing rows are left alone —
        the catalogue is the authority for a part it already knows.
        """
        if not products:
            return
        rows = [
            (p['part'], p.get('name') or p['part'], p.get('name') or p['part'],
             p.get('hsn') or None, p.get('price') or None, company_id,
             current_time, current_time)
            for p in products
        ]
        cursor.executemany(
            """INSERT IGNORE INTO product
                 (product_string, name, description, hsn_code, price, company_id,
                  created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )

    def replace_order_products_on(self, cursor, potential_order_id: int, rows: list) -> int:
        """Wipe and re-insert one order's lines on the caller's cursor.

        Replace rather than merge, matching the behaviour the product upload already
        has: the document being imported is the whole truth about that order's lines.
        Note the consequence — a pick-list upload and a product upload aimed at the
        same order overwrite each other, last one wins.
        """
        pf_sql, pf_params = self._pf('potential_order_product')
        cursor.execute(
            f"DELETE FROM potential_order_product "
            f"WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,),
        )
        if not rows:
            return 0
        cursor.executemany(
            """INSERT INTO potential_order_product
                 (potential_order_id, product_id, quantity, quantity_packed,
                  quantity_remaining, mrp, total_price, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )
        return cursor.rowcount

    def bulk_delete_order_products(self, potential_order_ids: list) -> None:
        """
        DELETE all potential_order_product rows for the given potential_order_ids.
        Partition-aware. Used in replace-mode upload (wipe then re-insert).
        """
        if not potential_order_ids:
            return
        pf_sql, pf_params = self._pf('potential_order_product')
        placeholders = ','.join(['%s'] * len(potential_order_ids))
        with self._db.get_cursor() as cursor:
            cursor.execute(
                f"DELETE FROM potential_order_product "
                f"WHERE {pf_sql} AND potential_order_id IN ({placeholders})",
                pf_params + tuple(potential_order_ids)
            )

    def bulk_insert_order_products(self, rows: list) -> int:
        """
        INSERT potential_order_product rows in one executemany call.

        Args:
            rows: list of tuples —
                  (potential_order_id, product_id, quantity, quantity_packed,
                   quantity_remaining, mrp, total_price, created_at, updated_at)

        Returns:
            Number of rows inserted.
        """
        if not rows:
            return 0
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT INTO potential_order_product
                   (potential_order_id, product_id, quantity, quantity_packed,
                    quantity_remaining, mrp, total_price, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                rows
            )
            return cursor.rowcount
