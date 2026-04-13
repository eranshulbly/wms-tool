# -*- encoding: utf-8 -*-
"""
MySQL Models - Direct MySQL implementation replacing SQLAlchemy
"""

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .db_manager import mysql_manager, MySQLModel, partition_filter


class Users(MySQLModel):
    """User model with direct MySQL queries"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.username = kwargs.get('username')
        self.email = kwargs.get('email')
        self.password = kwargs.get('password')
        self.jwt_auth_active = kwargs.get('jwt_auth_active', False)
        self.date_joined = kwargs.get('date_joined')
        self.status = kwargs.get('status', 'pending')   # pending | active | blocked
        self.role = kwargs.get('role', 'viewer')         # admin | manager | warehouse_staff | dispatcher | viewer

    def save(self):
        """Save user to database"""
        if self.id:
            mysql_manager.execute_query(
                """UPDATE users SET username=%s, email=%s, password=%s,
                   jwt_auth_active=%s, status=%s, role=%s WHERE id=%s""",
                (self.username, self.email, self.password,
                 self.jwt_auth_active, self.status, self.role, self.id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO users (username, email, password, jwt_auth_active,
                       date_joined, status, role)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (self.username, self.email, self.password, self.jwt_auth_active,
                     self.date_joined or datetime.utcnow(), self.status, self.role)
                )
                self.id = cursor.lastrowid

    def set_password(self, password):
        """Hash and set password"""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password, password)

    def update_email(self, new_email):
        """Update email"""
        self.email = new_email

    def update_username(self, new_username):
        """Update username"""
        self.username = new_username

    def check_jwt_auth_active(self):
        """Check if JWT auth is active"""
        return self.jwt_auth_active

    def set_jwt_auth_active(self, set_status):
        """Set JWT auth status"""
        self.jwt_auth_active = set_status

    @classmethod
    def get_by_id(cls, user_id):
        """Get user by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE id = %s", (user_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_by_email(cls, email):
        """Get user by email"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE email = %s", (email,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_by_username(cls, username):
        """Get user by username"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE username = %s", (username,)
        )
        if result:
            return cls(**result[0])
        return None

    def toJSON(self):
        """Convert to JSON"""
        return {
            '_id': self.id,
            'username': self.username,
            'email': self.email
        }


class JWTTokenBlocklist(MySQLModel):
    """JWT Token Blocklist model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.jwt_token = kwargs.get('jwt_token')
        self.created_at = kwargs.get('created_at')

    def save(self):
        """Save blocked token"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                "INSERT INTO jwt_token_blocklist (jwt_token, created_at) VALUES (%s, %s)",
                (self.jwt_token, self.created_at or datetime.utcnow())
            )
            self.id = cursor.lastrowid


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


class Company(MySQLModel):
    """Company model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.company_id = kwargs.get('company_id')
        self.name = kwargs.get('name')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save company"""
        if self.company_id:
            mysql_manager.execute_query(
                "UPDATE company SET name=%s, updated_at=%s WHERE company_id=%s",
                (self.name, datetime.utcnow(), self.company_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO company (name, created_at, updated_at) VALUES (%s, %s, %s)",
                    (self.name, datetime.utcnow(), datetime.utcnow())
                )
                self.company_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, company_id):
        """Get company by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM company WHERE company_id = %s", (company_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_all(cls):
        """Get all companies"""
        results = mysql_manager.execute_query("SELECT * FROM company")
        return [cls(**row) for row in results]


class Dealer(MySQLModel):
    """Dealer model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dealer_id = kwargs.get('dealer_id')
        self.name = kwargs.get('name')
        self.dealer_code = kwargs.get('dealer_code')
        self.town = kwargs.get('town')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save dealer"""
        if self.dealer_id:
            mysql_manager.execute_query(
                "UPDATE dealer SET name=%s, dealer_code=%s, town=%s, updated_at=%s WHERE dealer_id=%s",
                (self.name, self.dealer_code, self.town, datetime.utcnow(), self.dealer_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO dealer (name, dealer_code, town, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
                    (self.name, self.dealer_code, self.town, datetime.utcnow(), datetime.utcnow())
                )
                self.dealer_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, dealer_id):
        """Get dealer by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE dealer_id = %s", (dealer_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_name(cls, name):
        """Find dealer by name (case insensitive)"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE LOWER(name) = LOWER(%s)", (name,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_code(cls, dealer_code):
        """Find dealer by eway bill dealer code"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE dealer_code = %s", (dealer_code,)
        )
        if result:
            return cls(**result[0])
        return None


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


class Product(MySQLModel):
    """Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.product_id = kwargs.get('product_id')
        self.product_string = kwargs.get('product_string')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.nickname = kwargs.get('nickname')
        self.price = kwargs.get('price')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save product"""
        if self.product_id:
            mysql_manager.execute_query(
                """UPDATE product SET product_string=%s, name=%s, description=%s,
                   nickname=%s, price=%s, updated_at=%s WHERE product_id=%s""",
                (self.product_string, self.name, self.description, self.nickname,
                 self.price, datetime.utcnow(), self.product_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO product (product_string, name, description, nickname,
                       price, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (self.product_string, self.name, self.description, self.nickname,
                     self.price, datetime.utcnow(), datetime.utcnow())
                )
                self.product_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, product_id):
        """Get product by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM product WHERE product_id = %s", (product_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_product_string(cls, product_string):
        """Find product by product string (case insensitive)"""
        result = mysql_manager.execute_query(
            "SELECT * FROM product WHERE LOWER(product_string) = LOWER(%s)",
            (product_string,)
        )
        if result:
            return cls(**result[0])
        return None


class Box(MySQLModel):
    """Box model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.box_id = kwargs.get('box_id')
        self.name = kwargs.get('name')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save box"""
        if self.box_id:
            mysql_manager.execute_query(
                "UPDATE box SET name=%s, updated_at=%s WHERE box_id=%s",
                (self.name, datetime.utcnow(), self.box_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO box (name, created_at, updated_at) VALUES (%s, %s, %s)",
                    (self.name, datetime.utcnow(), datetime.utcnow())
                )
                self.box_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, box_id):
        """Get box by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM box WHERE box_id = %s", (box_id,)
        )
        if result:
            return cls(**result[0])
        return None


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
    def count_by_status(cls, status, warehouse_id=None, company_id=None):
        """Count orders by status with optional filters"""
        pf_sql, pf_params = partition_filter('potential_order')
        query = f"SELECT COUNT(*) as count FROM potential_order WHERE {pf_sql} AND status = %s"
        params = list(pf_params) + [status]

        if warehouse_id:
            query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            query += " AND company_id = %s"
            params.append(company_id)

        result = mysql_manager.execute_query(query, params)
        return result[0]['count'] if result else 0

    @classmethod
    def find_by_filters(cls, status=None, warehouse_id=None, company_id=None, limit=1000, offset=0, sort_by='created_at'):
        """Find orders by filters — scoped to the active 4-month partition window."""
        pf_sql, pf_params = partition_filter('potential_order', alias='po')
        query = f"""
        SELECT po.*, d.name as dealer_name, u.username as assigned_username
        FROM potential_order po
        LEFT JOIN dealer d ON po.dealer_id = d.dealer_id
        LEFT JOIN users u ON po.requested_by = u.id
        WHERE {pf_sql}
        """
        params = list(pf_params)

        if status:
            query += " AND po.status = %s"
            params.append(status)

        if warehouse_id:
            query += " AND po.warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            query += " AND po.company_id = %s"
            params.append(company_id)

        sort_col = 'updated_at' if sort_by == 'updated_at' else 'created_at'
        query += f" ORDER BY po.{sort_col} DESC LIMIT %s OFFSET %s"
        params.append(limit)
        params.append(offset)

        results = mysql_manager.execute_query(query, params)
        return results

    @classmethod
    def count_by_filters(cls, status=None, warehouse_id=None, company_id=None):
        """Count orders matching filters — used for pagination total."""
        pf_sql, pf_params = partition_filter('potential_order', alias='po')
        query = f"SELECT COUNT(*) as cnt FROM potential_order po WHERE {pf_sql}"
        params = list(pf_params)

        if status:
            query += " AND po.status = %s"
            params.append(status)

        if warehouse_id:
            query += " AND po.warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            query += " AND po.company_id = %s"
            params.append(company_id)

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
            f"""SELECT pop.*, p.product_string, p.name, p.description, p.price
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


class OrderBox(MySQLModel):
    """Order Box model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.box_id = kwargs.get('box_id')
        self.order_id = kwargs.get('order_id')
        self.name = kwargs.get('name')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save order box"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO order_box (order_id, name, created_at, updated_at) 
                   VALUES (%s, %s, %s, %s)""",
                (self.order_id, self.name, datetime.utcnow(), datetime.utcnow())
            )
            self.box_id = cursor.lastrowid


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


class BoxProduct(MySQLModel):
    """Box Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.box_product_id = kwargs.get('box_product_id')
        self.box_id = kwargs.get('box_id')
        self.product_id = kwargs.get('product_id')
        self.quantity = kwargs.get('quantity')
        self.potential_order_id = kwargs.get('potential_order_id')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save box product"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO box_product (box_id, product_id, quantity, 
                   potential_order_id, created_at, updated_at) 
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (self.box_id, self.product_id, self.quantity, self.potential_order_id,
                 datetime.utcnow(), datetime.utcnow())
            )
            self.box_product_id = cursor.lastrowid

    @classmethod
    def get_for_order(cls, potential_order_id):
        """Get box products for an order"""
        pf_sql, pf_params = partition_filter('box_product', alias='bp')
        results = mysql_manager.execute_query(
            f"""SELECT bp.*, b.name as box_name
               FROM box_product bp
               JOIN box b ON bp.box_id = b.box_id
               WHERE {pf_sql} AND bp.potential_order_id = %s""",
            pf_params + (potential_order_id,)
        )
        return results

    @classmethod
    def delete_for_order(cls, potential_order_id):
        """Delete box products for an order"""
        pf_sql, pf_params = partition_filter('box_product')
        mysql_manager.execute_query(
            f"DELETE FROM box_product WHERE {pf_sql} AND potential_order_id = %s",
            pf_params + (potential_order_id,),
            fetch=False
        )


class Invoice(MySQLModel):
    """Invoice model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set all invoice fields from kwargs
        for field in ['invoice_id', 'potential_order_id', 'warehouse_id', 'company_id',
                      'dealer_id', 'invoice_number', 'original_order_id', 'order_date',
                      'account_tin', 'cash_customer_name', 'contact_first_name',
                      'contact_last_name', 'customer_category', 'invoice_date', 'invoice_status',
                      'invoice_type', 'invoice_format', 'part_no', 'part_name', 'uom',
                      'hsn_number', 'product_type', 'product_category', 'quantity',
                      'unit_price', 'line_item_discount_percent', 'line_item_discount',
                      'net_selling_price', 'assessable_value', 'vat_amount', 'cgst_percent',
                      'cgst_amount', 'sgst_percent', 'sgst_amount', 'utgst_percent',
                      'utgst_amount', 'igst_percent', 'igst_amount', 'cess_percent',
                      'cess_amount', 'additional_tax_amt', 'additional_tax_amt2',
                      'additional_tax_amt3', 'additional_tax_amt4', 'additional_tax_amt5',
                      'freight_amount', 'packaging_charges', 'frt_pkg_cgst_percent',
                      'frt_pkg_cgst_amount', 'frt_pkg_sgst_percent', 'frt_pkg_sgst_amount',
                      'frt_pkg_igst_percent', 'frt_pkg_igst_amount', 'frt_pkg_cess_percent',
                      'frt_pkg_cess_amount', 'total_invoice_amount', 'additional_discount_percent',
                      'cash_discount_percent', 'credit_days', 'state', 'state_code', 'gstin',
                      'record_updated_dt', 'login', 'voucher', 'type_field', 'parent',
                      'sale_return_date', 'narration', 'cancellation_date', 'executive_name',
                      'round_off_amount', 'invoice_round_off_amount', 'short_amount',
                      'realized_amount', 'hmcgl_card_no', 'campaign',
                      'b2b_purchase_order_number', 'b2b_order_type', 'invoice_header_type',
                      'packaging_forwarding_charges', 'tax_on_pf', 'type_of_tax_pf',
                      'irn_number', 'irn_status', 'ack_number', 'ack_date',
                      'credit_note_number', 'irn_cancel', 'irn_status_cancel',
                      'ack_number_cancel', 'ack_date_cancel',
                      'uploaded_by', 'upload_batch_id', 'created_at', 'updated_at']:
            setattr(self, field, kwargs.get(field))

    def save(self):
        """Save invoice"""
        # This is a complex insert - using a dictionary approach
        fields = [k for k in self.__dict__.keys() if not k.startswith('_') and getattr(self, k) is not None]
        values = [getattr(self, field) for field in fields]
        placeholders = ', '.join(['%s'] * len(fields))
        field_names = ', '.join(fields)

        with mysql_manager.get_cursor() as cursor:
            sql = f"INSERT INTO invoice ({field_names}) VALUES ({placeholders})"
            cursor.execute(sql, values)
            self.invoice_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, invoice_id):
        """Get invoice by ID"""
        pf_sql, pf_params = partition_filter('invoice')
        result = mysql_manager.execute_query(
            f"SELECT * FROM invoice WHERE {pf_sql} AND invoice_id = %s",
            pf_params + (invoice_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_statistics(cls, warehouse_id=None, company_id=None, batch_id=None):
        """Get invoice statistics (active window only)"""
        pf_sql, pf_params = partition_filter('invoice')
        base_query = f"SELECT COUNT(*) as total_invoices FROM invoice WHERE {pf_sql}"
        params = list(pf_params)

        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            base_query += " AND company_id = %s"
            params.append(company_id)

        if batch_id:
            base_query += " AND upload_batch_id = %s"
            params.append(batch_id)

        total_result = mysql_manager.execute_query(base_query, params)
        total_invoices = total_result[0]['total_invoices'] if total_result else 0

        # Get unique orders
        unique_query = base_query.replace("COUNT(*)", "COUNT(DISTINCT potential_order_id)")
        unique_result = mysql_manager.execute_query(unique_query, params)
        unique_orders = unique_result[0]['COUNT(DISTINCT potential_order_id)'] if unique_result else 0

        # Get total amount
        amount_query = base_query.replace("COUNT(*)", "SUM(total_invoice_amount)")
        amount_result = mysql_manager.execute_query(amount_query, params)
        total_amount = amount_result[0]['SUM(total_invoice_amount)'] if amount_result else 0

        return {
            'total_invoices': total_invoices,
            'unique_orders': unique_orders,
            'total_amount': float(total_amount or 0)
        }


class InvoiceProcessingConfig(MySQLModel):
    """
    Generic key-value configuration for invoice processing rules.

    Current keys:
      bypass_order_type — order_type values whose orders skip the Packed
                          prerequisite and go directly to Invoiced on invoice
                          upload (e.g. 'ZGOI').
    """

    # Simple in-process cache: {config_key -> [value, ...]}
    _cache: dict = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.config_key = kwargs.get('config_key')
        self.config_value = kwargs.get('config_value')
        self.description = kwargs.get('description')
        self.is_active = bool(kwargs.get('is_active', True))

    @classmethod
    def get_values(cls, config_key: str) -> list:
        """Return all active config_values for a given config_key.

        Results are cached in-process for the lifetime of the worker.
        Call invalidate_cache() if values are mutated at runtime.
        """
        if config_key not in cls._cache:
            rows = mysql_manager.execute_query(
                "SELECT config_value FROM invoice_processing_config "
                "WHERE config_key = %s AND is_active = 1",
                (config_key,)
            )
            cls._cache[config_key] = [r['config_value'] for r in rows] if rows else []
        return cls._cache[config_key]

    @classmethod
    def get_bypass_order_types(cls) -> set:
        """Return the set of order_type values that bypass the Packed prerequisite."""
        return set(cls.get_values('bypass_order_type'))

    @classmethod
    def invalidate_cache(cls, config_key: str = None):
        """Clear cached values (call after mutating config rows)."""
        if config_key:
            cls._cache.pop(config_key, None)
        else:
            cls._cache.clear()


class UserWarehouseCompany(MySQLModel):
    """Maps users to allowed warehouse+company pairs"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.warehouse_id = kwargs.get('warehouse_id')
        self.company_id = kwargs.get('company_id')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT IGNORE INTO user_warehouse_company (user_id, warehouse_id, company_id)
                   VALUES (%s, %s, %s)""",
                (self.user_id, self.warehouse_id, self.company_id)
            )
            self.id = cursor.lastrowid

    @classmethod
    def get_for_user(cls, user_id):
        """Return list of {warehouse_id, company_id} pairs for a user"""
        return mysql_manager.execute_query(
            """SELECT uwc.warehouse_id, uwc.company_id,
                      w.name as warehouse_name, c.name as company_name
               FROM user_warehouse_company uwc
               JOIN warehouse w ON uwc.warehouse_id = w.warehouse_id
               JOIN company c ON uwc.company_id = c.company_id
               WHERE uwc.user_id = %s""",
            (user_id,)
        )

    @classmethod
    def delete_for_user(cls, user_id):
        mysql_manager.execute_query(
            "DELETE FROM user_warehouse_company WHERE user_id = %s",
            (user_id,), fetch=False
        )

    @classmethod
    def user_can_access(cls, user_id, warehouse_id, company_id):
        """Check if user has access to a specific warehouse+company pair"""
        result = mysql_manager.execute_query(
            """SELECT id FROM user_warehouse_company
               WHERE user_id=%s AND warehouse_id=%s AND company_id=%s""",
            (user_id, warehouse_id, company_id)
        )
        return bool(result)


# E-Way Bill Automation Models

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
