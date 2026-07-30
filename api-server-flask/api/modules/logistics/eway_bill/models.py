# -*- encoding: utf-8 -*-
"""eway_bill module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class TransportRoute(MySQLModel):
    """Transport Route model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.route_id = kwargs.get('route_id')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        if self.route_id:
            mysql_manager.execute_query(
                "UPDATE transport_routes SET name=%s, description=%s, updated_at=%s WHERE route_id=%s",
                (self.name, self.description, datetime.utcnow(), self.route_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO transport_routes (name, description, created_at, updated_at) VALUES (%s, %s, %s, %s)",
                    (self.name, self.description, datetime.utcnow(), datetime.utcnow())
                )
                self.route_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, route_id):
        result = mysql_manager.execute_query(
            "SELECT * FROM transport_routes WHERE route_id = %s", (route_id,)
        )
        return cls(**result[0]) if result else None

    @classmethod
    def get_all(cls):
        routes = mysql_manager.execute_query("SELECT * FROM transport_routes ORDER BY route_id")
        result = []
        for row in routes:
            r = cls(**row)
            count_result = mysql_manager.execute_query(
                "SELECT COUNT(*) as cnt FROM customer_route_mappings WHERE route_id = %s",
                (r.route_id,)
            )
            r._customer_count = count_result[0]['cnt'] if count_result else 0
            result.append(r)
        return result

    def to_dict(self):
        return {
            'route_id': self.route_id,
            'name': self.name,
            'description': self.description,
            'customer_count': getattr(self, '_customer_count', 0)
        }


class CustomerRouteMapping(MySQLModel):
    """Customer to Route Mapping model — keyed by dealer_id FK"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mapping_id = kwargs.get('mapping_id')
        self.dealer_id = kwargs.get('dealer_id')
        self.route_id = kwargs.get('route_id')
        self.distance = kwargs.get('distance')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO customer_route_mappings
                   (dealer_id, route_id, distance, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                   route_id=VALUES(route_id),
                   distance=VALUES(distance), updated_at=VALUES(updated_at)""",
                (self.dealer_id, self.route_id, self.distance,
                 datetime.utcnow(), datetime.utcnow())
            )
            if cursor.lastrowid:
                self.mapping_id = cursor.lastrowid

    @classmethod
    def get_all(cls):
        results = mysql_manager.execute_query(
            """SELECT m.mapping_id, m.dealer_id, d.dealer_code as customer_code,
                      d.name as customer_name, m.route_id, m.distance,
                      r.name as route_name
               FROM customer_route_mappings m
               JOIN dealer d ON m.dealer_id = d.dealer_id
               LEFT JOIN transport_routes r ON m.route_id = r.route_id
               ORDER BY r.name, d.dealer_code"""
        )
        return results or []

    @classmethod
    def get_for_route(cls, route_id):
        results = mysql_manager.execute_query(
            """SELECT m.mapping_id, m.dealer_id, d.dealer_code as customer_code,
                      d.name as customer_name, m.distance
               FROM customer_route_mappings m
               JOIN dealer d ON m.dealer_id = d.dealer_id
               WHERE m.route_id = %s ORDER BY d.dealer_code""",
            (route_id,)
        )
        return results or []

    @classmethod
    def find_by_dealer_code(cls, dealer_code):
        """Find mapping by eway bill dealer code (joins dealer table)."""
        result = mysql_manager.execute_query(
            """SELECT m.* FROM customer_route_mappings m
               JOIN dealer d ON m.dealer_id = d.dealer_id
               WHERE d.dealer_code = %s""",
            (dealer_code,)
        )
        return cls(**result[0]) if result else None

    @classmethod
    def find_by_dealer_id(cls, dealer_id):
        result = mysql_manager.execute_query(
            "SELECT * FROM customer_route_mappings WHERE dealer_id = %s", (dealer_id,)
        )
        return cls(**result[0]) if result else None

    @classmethod
    def delete_by_dealer_code(cls, dealer_code):
        """Delete mapping by eway bill dealer code."""
        mysql_manager.execute_query(
            """DELETE crm FROM customer_route_mappings crm
               JOIN dealer d ON crm.dealer_id = d.dealer_id
               WHERE d.dealer_code = %s""",
            (dealer_code,), fetch=False
        )

    @classmethod
    def delete_by_dealer_id(cls, dealer_id):
        mysql_manager.execute_query(
            "DELETE FROM customer_route_mappings WHERE dealer_id = %s",
            (dealer_id,), fetch=False
        )


class DailyRouteManifest(MySQLModel):
    """Daily Route Manifest model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.manifest_id = kwargs.get('manifest_id')
        self.route_id = kwargs.get('route_id')
        self.vehicle_number = kwargs.get('vehicle_number')
        self.manifest_date = kwargs.get('manifest_date')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        # Handle UPSERT for unique (route_id, manifest_date)
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO daily_route_manifests (route_id, vehicle_number, manifest_date, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE vehicle_number = VALUES(vehicle_number), updated_at = VALUES(updated_at)""",
                (self.route_id, self.vehicle_number, self.manifest_date, datetime.utcnow(), datetime.utcnow())
            )
            # If inserted, lastrowid works. If updated, might be 0 but that's ok for our flow.
            if cursor.lastrowid:
                self.manifest_id = cursor.lastrowid

    @classmethod
    def get_for_date(cls, manifest_date):
        results = mysql_manager.execute_query(
            """SELECT m.*, r.name as route_name 
               FROM daily_route_manifests m 
               JOIN transport_routes r ON m.route_id = r.route_id 
               WHERE m.manifest_date = %s""",
            (manifest_date,)
        )
        return results

    @classmethod
    def get_vehicle_for_route_date(cls, route_id, manifest_date):
        result = mysql_manager.execute_query(
            "SELECT vehicle_number FROM daily_route_manifests WHERE route_id = %s AND manifest_date = %s",
            (route_id, manifest_date)
        )
        return result[0]['vehicle_number'] if result else None


class CompanySchemaMapping(MySQLModel):
    """Company Schema Mapping model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mapping_id = kwargs.get('mapping_id')
        self.company_id = kwargs.get('company_id')
        self.invoice_no_col = kwargs.get('invoice_no_col')
        self.customer_code_col = kwargs.get('customer_code_col')
        self.customer_name_col = kwargs.get('customer_name_col')
        self.irn_col = kwargs.get('irn_col')
        self.amount_col = kwargs.get('amount_col')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO company_schema_mappings 
                   (company_id, invoice_no_col, customer_code_col, customer_name_col, irn_col, amount_col, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE 
                   invoice_no_col=VALUES(invoice_no_col), customer_code_col=VALUES(customer_code_col),
                   customer_name_col=VALUES(customer_name_col), irn_col=VALUES(irn_col), 
                   amount_col=VALUES(amount_col), updated_at=VALUES(updated_at)""",
                (self.company_id, self.invoice_no_col, self.customer_code_col, self.customer_name_col, 
                 self.irn_col, self.amount_col, datetime.utcnow(), datetime.utcnow())
            )

    @classmethod
    def get_for_company(cls, company_id):
        result = mysql_manager.execute_query(
            "SELECT * FROM company_schema_mappings WHERE company_id = %s", (company_id,)
        )
        return result[0] if result else None

