# -*- encoding: utf-8 -*-
"""
ProductRepository — all SQL for the product upload pipeline.

Covers the product table and potential_order_product linking table.
"""

from ..core.logging import get_logger
from .base_repository import BaseRepository

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

    def bulk_insert_products(self, new_products: dict, current_time) -> None:
        """
        INSERT IGNORE new products (product_string, name, description) into the product table.

        Args:
            new_products: dict mapping part_no → description
            current_time: datetime to use for created_at / updated_at
        """
        rows = [
            (part_no, description, description, current_time, current_time)
            for part_no, description in new_products.items()
        ]
        with self._db.get_cursor() as cursor:
            cursor.executemany(
                """INSERT IGNORE INTO product
                   (product_string, name, description, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                rows
            )

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
