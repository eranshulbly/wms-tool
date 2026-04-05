# -*- encoding: utf-8 -*-
"""
MySQL Models - Direct MySQL implementation replacing SQLAlchemy
"""

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .db_manager import mysql_manager, MySQLModel


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
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save dealer"""
        if self.dealer_id:
            mysql_manager.execute_query(
                "UPDATE dealer SET name=%s, updated_at=%s WHERE dealer_id=%s",
                (self.name, datetime.utcnow(), self.dealer_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO dealer (name, created_at, updated_at) VALUES (%s, %s, %s)",
                    (self.name, datetime.utcnow(), datetime.utcnow())
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


class Product(MySQLModel):
    """Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.product_id = kwargs.get('product_id')
        self.product_string = kwargs.get('product_string')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.price = kwargs.get('price')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save product"""
        if self.product_id:
            mysql_manager.execute_query(
                """UPDATE product SET product_string=%s, name=%s, description=%s, 
                   price=%s, updated_at=%s WHERE product_id=%s""",
                (self.product_string, self.name, self.description, self.price,
                 datetime.utcnow(), self.product_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO product (product_string, name, description, price, 
                       created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (self.product_string, self.name, self.description, self.price,
                     datetime.utcnow(), datetime.utcnow())
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
        self.warehouse_id = kwargs.get('warehouse_id')
        self.company_id = kwargs.get('company_id')
        self.dealer_id = kwargs.get('dealer_id')
        self.order_date = kwargs.get('order_date')
        self.requested_by = kwargs.get('requested_by')
        self.status = kwargs.get('status', 'Open')
        self.upload_batch_id = kwargs.get('upload_batch_id')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save potential order"""
        if self.potential_order_id:
            mysql_manager.execute_query(
                """UPDATE potential_order SET original_order_id=%s, warehouse_id=%s,
                   company_id=%s, dealer_id=%s, order_date=%s, requested_by=%s,
                   status=%s, updated_at=%s WHERE potential_order_id=%s""",
                (self.original_order_id, self.warehouse_id, self.company_id,
                 self.dealer_id, self.order_date, self.requested_by, self.status,
                 datetime.utcnow(), self.potential_order_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO potential_order (original_order_id, warehouse_id,
                       company_id, dealer_id, order_date, requested_by, status,
                       upload_batch_id, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.original_order_id, self.warehouse_id, self.company_id,
                     self.dealer_id, self.order_date, self.requested_by, self.status,
                     self.upload_batch_id, datetime.utcnow(), datetime.utcnow())
                )
                self.potential_order_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, potential_order_id):
        """Get potential order by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM potential_order WHERE potential_order_id = %s",
            (potential_order_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def count_by_status(cls, status, warehouse_id=None, company_id=None):
        """Count orders by status with optional filters"""
        query = "SELECT COUNT(*) as count FROM potential_order WHERE status = %s"
        params = [status]

        if warehouse_id:
            query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            query += " AND company_id = %s"
            params.append(company_id)

        result = mysql_manager.execute_query(query, params)
        return result[0]['count'] if result else 0

    @classmethod
    def find_by_filters(cls, status=None, warehouse_id=None, company_id=None, limit=100):
        """Find orders by filters"""
        query = """
        SELECT po.*, d.name as dealer_name 
        FROM potential_order po 
        LEFT JOIN dealer d ON po.dealer_id = d.dealer_id 
        WHERE 1=1
        """
        params = []

        if status:
            query += " AND po.status = %s"
            params.append(status)

        if warehouse_id:
            query += " AND po.warehouse_id = %s"
            params.append(warehouse_id)

        if company_id:
            query += " AND po.company_id = %s"
            params.append(company_id)

        query += " ORDER BY po.created_at DESC LIMIT %s"
        params.append(limit)

        results = mysql_manager.execute_query(query, params)
        return results

    @classmethod
    def find_by_original_order_id(cls, original_order_id, warehouse_id, company_id):
        """Find potential order by original order ID"""
        result = mysql_manager.execute_query(
            """SELECT * FROM potential_order 
               WHERE original_order_id = %s AND warehouse_id = %s AND company_id = %s""",
            (original_order_id, warehouse_id, company_id)
        )
        if result:
            return cls(**result[0])
        return None


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
        result = mysql_manager.execute_query(
            "SELECT * FROM potential_order_product WHERE potential_order_product_id = %s",
            (potential_order_product_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_order_and_product(cls, potential_order_id, product_id):
        """Find by order and product"""
        result = mysql_manager.execute_query(
            """SELECT * FROM potential_order_product 
               WHERE potential_order_id = %s AND product_id = %s""",
            (potential_order_id, product_id)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_products_for_order(cls, potential_order_id):
        """Get all products for an order with product details"""
        results = mysql_manager.execute_query(
            """SELECT pop.*, p.product_string, p.name, p.description, p.price 
               FROM potential_order_product pop
               JOIN product p ON pop.product_id = p.product_id
               WHERE pop.potential_order_id = %s""",
            (potential_order_id,)
        )
        return results

    @classmethod
    def count_by_order(cls, potential_order_id):
        """Count products in an order"""
        result = mysql_manager.execute_query(
            "SELECT COUNT(*) as count FROM potential_order_product WHERE potential_order_id = %s",
            (potential_order_id,)
        )
        return result[0]['count'] if result else 0

    @classmethod
    def update_packed_quantity(cls, potential_order_id, product_id, quantity_packed):
        """Update packed quantity for a specific product"""
        mysql_manager.execute_query(
            """UPDATE potential_order_product 
               SET quantity_packed = %s, updated_at = %s 
               WHERE potential_order_id = %s AND product_id = %s""",
            (quantity_packed, datetime.utcnow(), potential_order_id, product_id),
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
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save order"""
        if self.order_id:
            mysql_manager.execute_query(
                """UPDATE `order` SET potential_order_id=%s, order_number=%s, 
                   dispatched_date=%s, delivery_date=%s, status=%s, updated_at=%s 
                   WHERE order_id=%s""",
                (self.potential_order_id, self.order_number, self.dispatched_date,
                 self.delivery_date, self.status, datetime.utcnow(), self.order_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO `order` (potential_order_id, order_number, 
                       dispatched_date, delivery_date, status, created_at, updated_at) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (self.potential_order_id, self.order_number, self.dispatched_date,
                     self.delivery_date, self.status, datetime.utcnow(), datetime.utcnow())
                )
                self.order_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, order_id):
        """Get order by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM `order` WHERE order_id = %s", (order_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_potential_order_id(cls, potential_order_id):
        """Find order by potential order ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM `order` WHERE potential_order_id = %s", (potential_order_id,)
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
        """Get state history for an order"""
        results = mysql_manager.execute_query(
            """SELECT osh.*, os.state_name 
               FROM order_state_history osh
               JOIN order_state os ON osh.state_id = os.state_id
               WHERE osh.potential_order_id = %s
               ORDER BY osh.changed_at""",
            (potential_order_id,)
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
        results = mysql_manager.execute_query(
            """SELECT bp.*, b.name as box_name 
               FROM box_product bp
               JOIN box b ON bp.box_id = b.box_id
               WHERE bp.potential_order_id = %s""",
            (potential_order_id,)
        )
        return results

    @classmethod
    def delete_for_order(cls, potential_order_id):
        """Delete box products for an order"""
        mysql_manager.execute_query(
            "DELETE FROM box_product WHERE potential_order_id = %s",
            (potential_order_id,),
            fetch=False
        )


class Invoice(MySQLModel):
    """Invoice model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set all invoice fields from kwargs
        for field in ['invoice_id', 'potential_order_id', 'warehouse_id', 'company_id',
                      'invoice_number', 'dealer_code', 'original_order_id', 'customer_name',
                      'customer_code', 'customer_category', 'invoice_date', 'invoice_status',
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
                      'cash_discount_percent', 'credit_days', 'location_code', 'state',
                      'state_code', 'gstin', 'record_updated_dt', 'login', 'voucher',
                      'type_field', 'parent', 'sale_return_date', 'narration',
                      'cancellation_date', 'executive_name', 'uploaded_by', 'upload_batch_id',
                      'created_at', 'updated_at']:
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
        result = mysql_manager.execute_query(
            "SELECT * FROM invoice WHERE invoice_id = %s", (invoice_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_statistics(cls, warehouse_id=None, company_id=None, batch_id=None):
        """Get invoice statistics"""
        base_query = "SELECT COUNT(*) as total_invoices FROM invoice WHERE 1=1"
        params = []

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
            cities = mysql_manager.execute_query(
                "SELECT city_name FROM route_cities WHERE route_id = %s ORDER BY city_name",
                (r.route_id,)
            )
            r._cities = [c['city_name'] for c in (cities or [])]
            result.append(r)
        return result

    def to_dict(self):
        return {
            'route_id': self.route_id,
            'name': self.name,
            'description': self.description,
            'cities': getattr(self, '_cities', [])
        }


class RouteCity(MySQLModel):
    """City belonging to a transport route"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.city_id = kwargs.get('city_id')
        self.route_id = kwargs.get('route_id')
        self.city_name = kwargs.get('city_name')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT IGNORE INTO route_cities (route_id, city_name) VALUES (%s, %s)""",
                (self.route_id, self.city_name)
            )
            self.city_id = cursor.lastrowid

    def delete(self):
        mysql_manager.execute_query(
            "DELETE FROM route_cities WHERE route_id = %s AND city_name = %s",
            (self.route_id, self.city_name), fetch=False
        )

    @classmethod
    def get_for_route(cls, route_id):
        results = mysql_manager.execute_query(
            "SELECT city_name FROM route_cities WHERE route_id = %s ORDER BY city_name",
            (route_id,)
        )
        return [row['city_name'] for row in (results or [])]

    @classmethod
    def get_all_cities(cls):
        """Return list of distinct cities with their route info"""
        results = mysql_manager.execute_query(
            """SELECT rc.city_name, rc.route_id, tr.name as route_name
               FROM route_cities rc
               JOIN transport_routes tr ON rc.route_id = tr.route_id
               ORDER BY rc.city_name"""
        )
        return results or []

    @classmethod
    def find_route_by_city(cls, city_name):
        """Given a city name, return its route_id"""
        result = mysql_manager.execute_query(
            "SELECT route_id FROM route_cities WHERE city_name = %s LIMIT 1",
            (city_name,)
        )
        return result[0]['route_id'] if result else None


class CustomerCityMapping(MySQLModel):
    """Maps a customer code to a city and distance"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mapping_id = kwargs.get('mapping_id')
        self.customer_code = kwargs.get('customer_code')
        self.customer_name = kwargs.get('customer_name')
        self.city_name = kwargs.get('city_name')
        self.distance = kwargs.get('distance')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO customer_city_mappings
                   (customer_code, customer_name, city_name, distance, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                   customer_name=VALUES(customer_name), city_name=VALUES(city_name),
                   distance=VALUES(distance), updated_at=VALUES(updated_at)""",
                (self.customer_code, self.customer_name, self.city_name,
                 self.distance, datetime.utcnow(), datetime.utcnow())
            )
            if cursor.lastrowid:
                self.mapping_id = cursor.lastrowid

    @classmethod
    def get_all(cls):
        results = mysql_manager.execute_query(
            """SELECT m.*, rc.route_id,
                      COALESCE(tr.name, 'Unmapped City') as route_name
               FROM customer_city_mappings m
               LEFT JOIN route_cities rc ON m.city_name = rc.city_name
               LEFT JOIN transport_routes tr ON rc.route_id = tr.route_id
               ORDER BY m.city_name, m.customer_code"""
        )
        return results or []

    @classmethod
    def find_by_customer_code(cls, customer_code):
        result = mysql_manager.execute_query(
            "SELECT * FROM customer_city_mappings WHERE customer_code = %s",
            (customer_code,)
        )
        return cls(**result[0]) if result else None


class CustomerRouteMapping(MySQLModel):
    """Customer to Route Mapping model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mapping_id = kwargs.get('mapping_id')
        self.customer_code = kwargs.get('customer_code')
        self.customer_name = kwargs.get('customer_name')
        self.route_id = kwargs.get('route_id')
        self.distance = kwargs.get('distance')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        if self.mapping_id:
            mysql_manager.execute_query(
                """UPDATE customer_route_mappings SET customer_code=%s, customer_name=%s, 
                   route_id=%s, distance=%s, updated_at=%s WHERE mapping_id=%s""",
                (self.customer_code, self.customer_name, self.route_id, self.distance, 
                 datetime.utcnow(), self.mapping_id), fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO customer_route_mappings (customer_code, customer_name, route_id, 
                       distance, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (self.customer_code, self.customer_name, self.route_id, self.distance, 
                     datetime.utcnow(), datetime.utcnow())
                )
                self.mapping_id = cursor.lastrowid

    @classmethod
    def get_all(cls):
        results = mysql_manager.execute_query(
            """SELECT m.*, r.name as route_name 
               FROM customer_route_mappings m 
               LEFT JOIN transport_routes r ON m.route_id = r.route_id"""
        )
        return results

    @classmethod
    def find_by_customer_code(cls, customer_code):
        result = mysql_manager.execute_query(
            "SELECT * FROM customer_route_mappings WHERE customer_code = %s", (customer_code,)
        )
        return cls(**result[0]) if result else None


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
