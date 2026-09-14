# -*- encoding: utf-8 -*-
"""order module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter
from api.permissions import company_filter_sql


class OrderState(MySQLModel):
    """Order State model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state_id = kwargs.get('state_id')
        self.state_name = kwargs.get('state_name')
        self.description = kwargs.get('description')

    def save(self):
        """Save order state"""
        if self.state_id:
            mysql_manager.execute_query(
                "UPDATE order_state SET state_name=%s, description=%s WHERE state_id=%s",
                (self.state_name, self.description, self.state_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO order_state (state_name, description) VALUES (%s, %s)",
                    (self.state_name, self.description)
                )
                self.state_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, state_id):
        """Get order state by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM order_state WHERE state_id = %s", (state_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_name(cls, state_name):
        """Find order state by name"""
        result = mysql_manager.execute_query(
            "SELECT * FROM order_state WHERE state_name = %s", (state_name,)
        )
        if result:
            return cls(**result[0])
        return None


class PotentialOrder(MySQLModel):
    """Potential Order model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.potential_order_id = kwargs.get('potential_order_id')
        self.original_order_id = kwargs.get('original_order_id')
        self.b2b_po_number = kwargs.get('b2b_po_number')
        self.order_type = kwargs.get('order_type')
        self.vin_number = kwargs.get('vin_number')
        self.shipping_address = kwargs.get('shipping_address')
        self.source_created_by = kwargs.get('source_created_by')
        self.purchaser_sap_code = kwargs.get('purchaser_sap_code')
        self.purchaser_name = kwargs.get('purchaser_name')
        self.warehouse_id = kwargs.get('warehouse_id')
        self.company_id = kwargs.get('company_id')
        self.dealer_id = kwargs.get('dealer_id')
        self.order_date = kwargs.get('order_date')
        self.requested_by = kwargs.get('requested_by')
        self.status = kwargs.get('status', 'Open')
        self.box_count = kwargs.get('box_count', 1)
        self.invoice_submitted = bool(kwargs.get('invoice_submitted', False))
        self.upload_batch_id = kwargs.get('upload_batch_id')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save potential order"""
        if self.potential_order_id:
            mysql_manager.execute_query(
                """UPDATE potential_order SET original_order_id=%s, b2b_po_number=%s,
                   order_type=%s, vin_number=%s, shipping_address=%s,
                   source_created_by=%s, purchaser_sap_code=%s, purchaser_name=%s,
                   warehouse_id=%s, company_id=%s, dealer_id=%s, order_date=%s,
                   requested_by=%s, status=%s, box_count=%s, invoice_submitted=%s, updated_at=%s
                   WHERE potential_order_id=%s""",
                (self.original_order_id, self.b2b_po_number,
                 self.order_type, self.vin_number, self.shipping_address,
                 self.source_created_by, self.purchaser_sap_code, self.purchaser_name,
                 self.warehouse_id, self.company_id, self.dealer_id, self.order_date,
                 self.requested_by, self.status, self.box_count, int(self.invoice_submitted),
                 datetime.utcnow(), self.potential_order_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO potential_order (original_order_id, b2b_po_number,
                       order_type, vin_number, shipping_address, source_created_by,
                       purchaser_sap_code, purchaser_name, warehouse_id, company_id,
                       dealer_id, order_date, requested_by, status, box_count, upload_batch_id,
                       created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.original_order_id, self.b2b_po_number,
                     self.order_type, self.vin_number, self.shipping_address,
                     self.source_created_by, self.purchaser_sap_code, self.purchaser_name,
                     self.warehouse_id, self.company_id, self.dealer_id, self.order_date,
                     self.requested_by, self.status, self.box_count, self.upload_batch_id,
                     datetime.utcnow(), datetime.utcnow())
                )
                self.potential_order_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, potential_order_id):
        """Get potential order by ID"""
        pf_sql, pf_params = partition_filter('potential_order')
        result = mysql_manager.execute_query(
            f"SELECT * FROM potential_order WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def count_by_status(cls, status, warehouse_id=None, company_ids=None):
        """Count orders by status with optional filters.

        `company_ids` is the caller's resolved tenant scope (see
        permissions.resolve_company_scope) — a list, or None for an all_warehouses role.
        It is NOT a raw request parameter: an empty list means "no companies" and matches
        nothing, which is the safe direction for a tenant filter.
        """
        pf_sql, pf_params = partition_filter('potential_order')
        cf_sql, cf_params = company_filter_sql(company_ids)
        query = (f"SELECT COUNT(*) as count FROM potential_order "
                 f"WHERE {pf_sql} AND {cf_sql} AND status = %s")
        params = list(pf_params) + list(cf_params) + [status]

        if warehouse_id:
            query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        result = mysql_manager.execute_query(query, params)
        return result[0]['count'] if result else 0

    @classmethod
    def find_by_filters(cls, status=None, warehouse_id=None, company_ids=None, limit=1000, offset=0, sort_by='created_at'):
        """Find orders by filters — scoped to the active 4-month partition window.

        `company_ids` is the caller's resolved tenant scope, not a request parameter.
        """
        pf_sql, pf_params = partition_filter('potential_order', alias='po')
        cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
        query = f"""
        SELECT po.*, d.name as dealer_name, u.name as assigned_username
        FROM potential_order po
        LEFT JOIN dealer d ON po.dealer_id = d.dealer_id
        LEFT JOIN users u ON po.requested_by = u.id
        WHERE {pf_sql} AND {cf_sql}
        """
        params = list(pf_params) + list(cf_params)

        if status:
            query += " AND po.status = %s"
            params.append(status)

        if warehouse_id:
            query += " AND po.warehouse_id = %s"
            params.append(warehouse_id)

        sort_col = 'updated_at' if sort_by == 'updated_at' else 'created_at'
        query += f" ORDER BY po.{sort_col} DESC LIMIT %s OFFSET %s"
        params.append(limit)
        params.append(offset)

        results = mysql_manager.execute_query(query, params)
        return results

    @classmethod
    def count_by_filters(cls, status=None, warehouse_id=None, company_ids=None):
        """Count orders matching filters — used for pagination total.

        `company_ids` is the caller's resolved tenant scope, not a request parameter.
        """
        pf_sql, pf_params = partition_filter('potential_order', alias='po')
        cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
        query = f"SELECT COUNT(*) as cnt FROM potential_order po WHERE {pf_sql} AND {cf_sql}"
        params = list(pf_params) + list(cf_params)

        if status:
            query += " AND po.status = %s"
            params.append(status)

        if warehouse_id:
            query += " AND po.warehouse_id = %s"
            params.append(warehouse_id)

        result = mysql_manager.execute_query(query, params)
        return result[0]['cnt'] if result else 0

    @classmethod
    def find_by_original_order_id(cls, original_order_id, warehouse_id=None, company_id=None):  # noqa: ARG003
        """Find potential order by original order ID within the active window.

        Searches by original_order_id only — the ID already encodes the warehouse
        (e.g. '30305-02-PSAO-0426-200'), so strict warehouse/company FK filtering
        caused legitimate orders to be missed. warehouse_id/company_id are kept
        for backwards-compatibility but are intentionally unused.
        """
        pf_sql, pf_params = partition_filter('potential_order')
        result = mysql_manager.execute_query(
            f"SELECT * FROM potential_order WHERE {pf_sql} AND original_order_id = %s",
            pf_params + (original_order_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_bulk_by_original_order_ids(cls, order_ids):
        """Fetch multiple PotentialOrders in a single IN query (active window only).

        Args:
            order_ids: list of original_order_id strings

        Returns:
            dict mapping original_order_id → PotentialOrder instance
        """
        if not order_ids:
            return {}
        pf_sql, pf_params = partition_filter('potential_order')
        placeholders = ','.join(['%s'] * len(order_ids))
        results = mysql_manager.execute_query(
            f"SELECT * FROM potential_order WHERE {pf_sql} AND original_order_id IN ({placeholders})",
            pf_params + tuple(order_ids)
        )
        return {r['original_order_id']: cls(**r) for r in results} if results else {}


class PotentialOrderProduct(MySQLModel):
    """Potential Order Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.potential_order_product_id = kwargs.get('potential_order_product_id')
        self.potential_order_id = kwargs.get('potential_order_id')
        self.product_id = kwargs.get('product_id')
        self.quantity = kwargs.get('quantity')
        self.quantity_packed = kwargs.get('quantity_packed', 0)
        self.quantity_remaining = kwargs.get('quantity_remaining')
        self.mrp = kwargs.get('mrp')
        self.total_price = kwargs.get('total_price')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save potential order product"""
        if self.potential_order_product_id:
            mysql_manager.execute_query(
                """UPDATE potential_order_product SET potential_order_id=%s, 
                   product_id=%s, quantity=%s, quantity_packed=%s, quantity_remaining=%s,
                   mrp=%s, total_price=%s, updated_at=%s 
                   WHERE potential_order_product_id=%s""",
                (self.potential_order_id, self.product_id, self.quantity,
                 self.quantity_packed, self.quantity_remaining, self.mrp,
                 self.total_price, datetime.utcnow(), self.potential_order_product_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO potential_order_product (potential_order_id, product_id, 
                       quantity, quantity_packed, quantity_remaining, mrp, total_price,
                       created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.potential_order_id, self.product_id, self.quantity,
                     self.quantity_packed, self.quantity_remaining, self.mrp,
                     self.total_price, datetime.utcnow(), datetime.utcnow())
                )
                self.potential_order_product_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, potential_order_product_id):
        """Get potential order product by ID"""
        pf_sql, pf_params = partition_filter('potential_order_product')
        result = mysql_manager.execute_query(
            f"SELECT * FROM potential_order_product WHERE {pf_sql} AND potential_order_product_id = %s",
            pf_params + (potential_order_product_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_order_and_product(cls, potential_order_id, product_id):
        """Find by order and product"""
        pf_sql, pf_params = partition_filter('potential_order_product')
        result = mysql_manager.execute_query(
            f"""SELECT * FROM potential_order_product
               WHERE {pf_sql} AND potential_order_id = %s AND product_id = %s""",
            pf_params + (potential_order_id, product_id)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_products_for_order(cls, potential_order_id):
        """Get all products for an order with product details"""
        pf_sql, pf_params = partition_filter('potential_order_product', alias='pop')
        results = mysql_manager.execute_query(
            # p.price is aliased because the LINE now carries its own money columns
            # (unit_price, net_selling_price, ...) picked up by pop.*, and an unaliased
            # p.price would land on the same 'price' key and quietly win. The catalogue
            # figure is only a fallback for old orders that were stored without one.
            f"""SELECT pop.*, p.product_string, p.name, p.description,
                       p.price AS catalog_price
               FROM potential_order_product pop
               JOIN product p ON pop.product_id = p.product_id
               WHERE {pf_sql} AND pop.potential_order_id = %s""",
            pf_params + (potential_order_id,)
        )
        return results

    @classmethod
    def count_by_order(cls, potential_order_id):
        """Count products in an order"""
        pf_sql, pf_params = partition_filter('potential_order_product')
        result = mysql_manager.execute_query(
            f"SELECT COUNT(*) as count FROM potential_order_product WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        return result[0]['count'] if result else 0

    @classmethod
    def update_packed_quantity(cls, potential_order_id, product_id, quantity_packed):
        """Update packed quantity for a specific product"""
        pf_sql, pf_params = partition_filter('potential_order_product')
        mysql_manager.execute_query(
            f"""UPDATE potential_order_product
               SET quantity_packed = %s, updated_at = %s
               WHERE {pf_sql} AND potential_order_id = %s AND product_id = %s""",
            (quantity_packed, datetime.utcnow()) + pf_params + (potential_order_id, product_id),
            fetch=False
        )


class Order(MySQLModel):
    """Final Order model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.order_id = kwargs.get('order_id')
        self.potential_order_id = kwargs.get('potential_order_id')
        self.order_number = kwargs.get('order_number')
        self.dispatched_date = kwargs.get('dispatched_date')
        self.delivery_date = kwargs.get('delivery_date')
        self.status = kwargs.get('status', 'In Transit')
        self.box_count = kwargs.get('box_count', 1)
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save order"""
        if self.order_id:
            mysql_manager.execute_query(
                """UPDATE `order` SET potential_order_id=%s, order_number=%s,
                   dispatched_date=%s, delivery_date=%s, status=%s, box_count=%s, updated_at=%s
                   WHERE order_id=%s""",
                (self.potential_order_id, self.order_number, self.dispatched_date,
                 self.delivery_date, self.status, self.box_count, datetime.utcnow(), self.order_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO `order` (potential_order_id, order_number,
                       dispatched_date, delivery_date, status, box_count, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.potential_order_id, self.order_number, self.dispatched_date,
                     self.delivery_date, self.status, self.box_count, datetime.utcnow(), datetime.utcnow())
                )
                self.order_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, order_id):
        """Get order by ID"""
        pf_sql, pf_params = partition_filter('order')
        result = mysql_manager.execute_query(
            f"SELECT * FROM `order` WHERE {pf_sql} AND order_id = %s",
            pf_params + (order_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_potential_order_id(cls, potential_order_id):
        """Find order by potential order ID"""
        pf_sql, pf_params = partition_filter('order')
        result = mysql_manager.execute_query(
            f"SELECT * FROM `order` WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,)
        )
        if result:
            return cls(**result[0])
        return None


class OrderStateHistory(MySQLModel):
    """Order State History model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.order_state_history_id = kwargs.get('order_state_history_id')
        self.potential_order_id = kwargs.get('potential_order_id')
        self.state_id = kwargs.get('state_id')
        self.changed_by = kwargs.get('changed_by')
        self.changed_at = kwargs.get('changed_at')

    def save(self):
        """Save order state history"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO order_state_history (potential_order_id, state_id, 
                   changed_by, changed_at) VALUES (%s, %s, %s, %s)""",
                (self.potential_order_id, self.state_id, self.changed_by,
                 self.changed_at or datetime.utcnow())
            )
            self.order_state_history_id = cursor.lastrowid

    @classmethod
    def get_history_for_order(cls, potential_order_id):
        """Get state history for an order (active window only)"""
        pf_sql, pf_params = partition_filter('order_state_history', alias='osh')
        results = mysql_manager.execute_query(
            f"""SELECT osh.*, os.state_name
               FROM order_state_history osh
               JOIN order_state os ON osh.state_id = os.state_id
               WHERE {pf_sql} AND osh.potential_order_id = %s
               ORDER BY osh.changed_at""",
            pf_params + (potential_order_id,)
        )
        return results


class OrderProduct(MySQLModel):
    """Order Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.order_product_id = kwargs.get('order_product_id')
        self.order_id = kwargs.get('order_id')
        self.product_id = kwargs.get('product_id')
        self.quantity = kwargs.get('quantity')
        self.mrp = kwargs.get('mrp')
        self.total_price = kwargs.get('total_price')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save order product"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO order_product (order_id, product_id, quantity, mrp, 
                   total_price, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (self.order_id, self.product_id, self.quantity, self.mrp,
                 self.total_price, datetime.utcnow(), datetime.utcnow())
            )
            self.order_product_id = cursor.lastrowid

