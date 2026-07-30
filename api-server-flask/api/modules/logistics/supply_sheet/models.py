# -*- encoding: utf-8 -*-
"""supply_sheet module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class SupplySheetCounter(MySQLModel):
    """Per-warehouse auto-incrementing supply sheet counter.

    Each call to next_for_warehouse() atomically increments the counter and
    returns the new value formatted as 'SS-{counter:03d}'.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.counter_id   = kwargs.get('counter_id')
        self.warehouse_id = kwargs.get('warehouse_id')
        self.counter      = kwargs.get('counter', 0)

    @classmethod
    def next_for_warehouse(cls, warehouse_id: int) -> str:
        """Atomically increment and return the next supply sheet number.

        Returns a string like 'SS-001'.
        """
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO supply_sheet_counter (warehouse_id, counter)
                   VALUES (%s, 1)
                   ON DUPLICATE KEY UPDATE counter = counter + 1""",
                (warehouse_id,)
            )
            cursor.execute(
                "SELECT counter FROM supply_sheet_counter WHERE warehouse_id = %s",
                (warehouse_id,)
            )
            row = cursor.fetchone()
        value = row['counter'] if row else 1
        return f"SS-{value:03d}"

