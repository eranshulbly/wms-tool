# -*- encoding: utf-8 -*-
"""inventory module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class Warehouse(MySQLModel):
    """Warehouse model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.warehouse_id = kwargs.get('warehouse_id')
        self.name = kwargs.get('name')
        self.location = kwargs.get('location')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save warehouse"""
        if self.warehouse_id:
            mysql_manager.execute_query(
                """UPDATE warehouse SET name=%s, location=%s, updated_at=%s 
                   WHERE warehouse_id=%s""",
                (self.name, self.location, datetime.utcnow(), self.warehouse_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO warehouse (name, location, created_at, updated_at) 
                       VALUES (%s, %s, %s, %s)""",
                    (self.name, self.location, datetime.utcnow(), datetime.utcnow())
                )
                self.warehouse_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, warehouse_id):
        """Get warehouse by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM warehouse WHERE warehouse_id = %s", (warehouse_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_all(cls):
        """Get all warehouses"""
        results = mysql_manager.execute_query("SELECT * FROM warehouse")
        return [cls(**row) for row in results]

