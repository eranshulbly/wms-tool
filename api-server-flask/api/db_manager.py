"""
MySQL Database Connection Manager
"""

import os
import pymysql
import threading
from contextlib import contextmanager

# Install PyMySQL as MySQLdb for compatibility
pymysql.install_as_MySQLdb()


class MySQLManager:
    """MySQL Connection Manager with connection pooling"""

    def __init__(self):
        self.pool = []
        self.pool_size = int(os.getenv('DB_POOL_SIZE', '10'))
        self.max_overflow = int(os.getenv('DB_MAX_OVERFLOW', '20'))
        self.pool_lock = threading.Lock()
        self.config = self._get_db_config()
        self._initialize_pool()

    def _get_db_config(self):
        """Get database configuration from environment variables"""
        return {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', '3306')),
            'user': os.getenv('DB_USERNAME', 'root'),
            'password': os.getenv('DB_PASS', 'root-pw'),
            'database': os.getenv('DB_NAME', 'warehouse_management'),
            'charset': os.getenv('MYSQL_CHARSET', 'utf8mb4'),
            'autocommit': False,
            'cursorclass': pymysql.cursors.DictCursor,
            'connect_timeout': 60,
            'read_timeout': 60,
            'write_timeout': 60
        }

    def _initialize_pool(self):
        """Initialize connection pool"""
        with self.pool_lock:
            for _ in range(self.pool_size):
                try:
                    conn = self._create_connection()
                    self.pool.append(conn)
                except Exception as e:
                    print(f"Error creating connection: {e}")

    def _create_connection(self):
        """Create a new MySQL connection"""
        return pymysql.connect(**self.config)

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool"""
        conn = None
        try:
            with self.pool_lock:
                if self.pool:
                    conn = self.pool.pop()
                else:
                    conn = self._create_connection()

            # Test connection
            conn.ping(reconnect=True)
            yield conn

        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                with self.pool_lock:
                    if len(self.pool) < self.pool_size:
                        self.pool.append(conn)
                    else:
                        conn.close()

    @contextmanager
    def get_cursor(self, commit=True):
        """Get a cursor with automatic connection management"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                cursor.close()

    def execute_query(self, query, params=None, fetch=True):
        """Execute a query and return results"""
        with self.get_cursor() as cursor:
            cursor.execute(query, params or ())
            if fetch:
                return cursor.fetchall()
            return cursor.rowcount

    def execute_many(self, query, params_list):
        """Execute many queries with different parameters"""
        with self.get_cursor() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount

    def get_last_insert_id(self, cursor):
        """Get last inserted ID"""
        return cursor.lastrowid


# Global MySQL manager instance
mysql_manager = MySQLManager()


class MySQLModel:
    """Base class for MySQL models"""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def create_table_sql(cls):
        """Override in subclasses to define table creation SQL"""
        raise NotImplementedError("Subclasses must implement create_table_sql")

    @classmethod
    def create_table(cls):
        """Create table if not exists"""
        sql = cls.create_table_sql()
        mysql_manager.execute_query(sql, fetch=False)

    def to_dict(self):
        """Convert model to dictionary"""
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


# Initialize database function
def initialize_database():
    """Initialize database tables with MySQL"""
    try:
        print("🔄 Attempting to connect to MySQL database...")

        # Test database connection
        try:
            with mysql_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1 as test')
                    result = cursor.fetchone()
                print("✅ MySQL database connection successful!")
        except Exception as conn_error:
            print(f"❌ MySQL connection failed: {str(conn_error)}")
            raise conn_error

        print("🔄 Creating database tables...")
        create_all_tables()
        print("✅ MySQL database tables created successfully!")

    except Exception as e:
        print(f'❌ Error: MySQL Database Exception: {str(e)}')
        raise e


def create_all_tables():
    """Create all required tables"""

    # Users table
    users_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(32) NOT NULL,
        email VARCHAR(64) UNIQUE,
        password TEXT,
        jwt_auth_active BOOLEAN DEFAULT FALSE,
        date_joined DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_users_username (username),
        INDEX idx_users_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # JWT Token Blocklist table
    jwt_blocklist_sql = """
    CREATE TABLE IF NOT EXISTS jwt_token_blocklist (
        id INT AUTO_INCREMENT PRIMARY KEY,
        jwt_token TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_jwt_token_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Warehouse table
    warehouse_sql = """
    CREATE TABLE IF NOT EXISTS warehouse (
        warehouse_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        location VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_warehouse_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Company table
    company_sql = """
    CREATE TABLE IF NOT EXISTS company (
        company_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_company_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Dealer table
    dealer_sql = """
    CREATE TABLE IF NOT EXISTS dealer (
        dealer_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_dealer_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Box table
    box_sql = """
    CREATE TABLE IF NOT EXISTS box (
        box_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_box_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Product table
    product_sql = """
    CREATE TABLE IF NOT EXISTS product (
        product_id INT AUTO_INCREMENT PRIMARY KEY,
        product_string VARCHAR(100),
        name VARCHAR(255) NOT NULL,
        description TEXT,
        price DECIMAL(10,2),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_product_string (product_string),
        INDEX idx_product_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order State table
    order_state_sql = """
    CREATE TABLE IF NOT EXISTS order_state (
        state_id INT AUTO_INCREMENT PRIMARY KEY,
        state_name VARCHAR(50) NOT NULL UNIQUE,
        description TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Potential Order table
    potential_order_sql = """
    CREATE TABLE IF NOT EXISTS potential_order (
        potential_order_id INT AUTO_INCREMENT PRIMARY KEY,
        original_order_id VARCHAR(100) NOT NULL,
        warehouse_id INT,
        company_id INT,
        dealer_id INT,
        order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        requested_by INT,
        status VARCHAR(50) DEFAULT 'Open',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_potential_order_status (status),
        INDEX idx_potential_order_date (order_date),
        INDEX idx_potential_order_composite (warehouse_id, company_id, status),
        FOREIGN KEY (warehouse_id) REFERENCES warehouse(warehouse_id),
        FOREIGN KEY (company_id) REFERENCES company(company_id),
        FOREIGN KEY (dealer_id) REFERENCES dealer(dealer_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Potential Order Product table
    potential_order_product_sql = """
    CREATE TABLE IF NOT EXISTS potential_order_product (
        potential_order_product_id INT AUTO_INCREMENT PRIMARY KEY,
        potential_order_id INT,
        product_id INT,
        quantity INT NOT NULL,
        quantity_packed INT DEFAULT 0,
        quantity_remaining INT,
        mrp DECIMAL(10,2),
        total_price DECIMAL(10,2),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_pop_order_product (potential_order_id, product_id),
        FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id),
        FOREIGN KEY (product_id) REFERENCES product(product_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order table
    order_sql = """
    CREATE TABLE IF NOT EXISTS `order` (
        order_id INT AUTO_INCREMENT PRIMARY KEY,
        potential_order_id INT,
        order_number VARCHAR(255) NOT NULL,
        dispatched_date DATETIME,
        delivery_date DATETIME,
        status VARCHAR(50) DEFAULT 'In Transit',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_order_number (order_number),
        INDEX idx_order_status (status),
        FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order State History table
    order_state_history_sql = """
    CREATE TABLE IF NOT EXISTS order_state_history (
        order_state_history_id INT AUTO_INCREMENT PRIMARY KEY,
        potential_order_id INT,
        state_id INT,
        changed_by INT,
        changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_osh_order_state (potential_order_id, state_id),
        INDEX idx_osh_changed_at (changed_at),
        FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id),
        FOREIGN KEY (state_id) REFERENCES order_state(state_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order Box table
    order_box_sql = """
    CREATE TABLE IF NOT EXISTS order_box (
        box_id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT,
        name VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_order_box_order (order_id),
        FOREIGN KEY (order_id) REFERENCES `order`(order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order Product table
    order_product_sql = """
    CREATE TABLE IF NOT EXISTS order_product (
        order_product_id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT,
        product_id INT,
        quantity INT NOT NULL,
        mrp DECIMAL(10,2),
        total_price DECIMAL(10,2),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_order_product_composite (order_id, product_id),
        FOREIGN KEY (order_id) REFERENCES `order`(order_id),
        FOREIGN KEY (product_id) REFERENCES product(product_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Box Product table
    box_product_sql = """
    CREATE TABLE IF NOT EXISTS box_product (
        box_product_id INT AUTO_INCREMENT PRIMARY KEY,
        box_id INT,
        product_id INT,
        quantity INT NOT NULL,
        potential_order_id INT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_box_product_composite (box_id, product_id),
        INDEX idx_box_product_order (potential_order_id),
        FOREIGN KEY (box_id) REFERENCES box(box_id),
        FOREIGN KEY (product_id) REFERENCES product(product_id),
        FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Invoice table
    invoice_sql = """
    CREATE TABLE IF NOT EXISTS invoice (
        invoice_id INT AUTO_INCREMENT PRIMARY KEY,
        potential_order_id INT,
        warehouse_id INT,
        company_id INT,
        invoice_number VARCHAR(255) NOT NULL,
        dealer_code VARCHAR(100),
        original_order_id VARCHAR(255) NOT NULL,
        customer_name VARCHAR(500),
        customer_code VARCHAR(100),
        customer_category VARCHAR(100),
        invoice_date DATETIME,
        invoice_status VARCHAR(50),
        invoice_type VARCHAR(50),
        invoice_format VARCHAR(50),
        part_no VARCHAR(255),
        part_name VARCHAR(500),
        uom VARCHAR(50),
        hsn_number VARCHAR(100),
        product_type VARCHAR(100),
        product_category VARCHAR(100),
        quantity INT,
        unit_price DECIMAL(10,2),
        line_item_discount_percent DECIMAL(5,2),
        line_item_discount DECIMAL(10,2),
        net_selling_price DECIMAL(10,2),
        assessable_value DECIMAL(10,2),
        vat_amount DECIMAL(10,2),
        cgst_percent DECIMAL(5,2),
        cgst_amount DECIMAL(10,2),
        sgst_percent DECIMAL(5,2),
        sgst_amount DECIMAL(10,2),
        utgst_percent DECIMAL(5,2),
        utgst_amount DECIMAL(10,2),
        igst_percent DECIMAL(5,2),
        igst_amount DECIMAL(10,2),
        cess_percent DECIMAL(5,2),
        cess_amount DECIMAL(10,2),
        additional_tax_amt DECIMAL(10,2),
        additional_tax_amt2 DECIMAL(10,2),
        additional_tax_amt3 DECIMAL(10,2),
        additional_tax_amt4 DECIMAL(10,2),
        additional_tax_amt5 DECIMAL(10,2),
        freight_amount DECIMAL(10,2),
        packaging_charges DECIMAL(10,2),
        frt_pkg_cgst_percent DECIMAL(5,2),
        frt_pkg_cgst_amount DECIMAL(10,2),
        frt_pkg_sgst_percent DECIMAL(5,2),
        frt_pkg_sgst_amount DECIMAL(10,2),
        frt_pkg_igst_percent DECIMAL(5,2),
        frt_pkg_igst_amount DECIMAL(10,2),
        frt_pkg_cess_percent DECIMAL(5,2),
        frt_pkg_cess_amount DECIMAL(10,2),
        total_invoice_amount DECIMAL(12,2),
        additional_discount_percent DECIMAL(5,2),
        cash_discount_percent DECIMAL(5,2),
        credit_days INT,
        location_code VARCHAR(50),
        state VARCHAR(100),
        state_code VARCHAR(10),
        gstin VARCHAR(50),
        record_updated_dt DATETIME,
        login VARCHAR(100),
        voucher VARCHAR(100),
        type_field VARCHAR(100),
        parent VARCHAR(100),
        sale_return_date DATETIME,
        narration TEXT,
        cancellation_date DATETIME,
        executive_name VARCHAR(255),
        uploaded_by INT,
        upload_batch_id VARCHAR(100),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_invoice_number (invoice_number),
        INDEX idx_invoice_original_order (original_order_id),
        INDEX idx_invoice_batch (upload_batch_id),
        INDEX idx_invoice_date (invoice_date),
        INDEX idx_invoice_composite (warehouse_id, company_id, invoice_date),
        FOREIGN KEY (potential_order_id) REFERENCES potential_order(potential_order_id),
        FOREIGN KEY (warehouse_id) REFERENCES warehouse(warehouse_id),
        FOREIGN KEY (company_id) REFERENCES company(company_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Execute all table creation queries
    tables = [
        users_sql, jwt_blocklist_sql, warehouse_sql, company_sql,
        dealer_sql, box_sql, product_sql, order_state_sql,
        potential_order_sql, potential_order_product_sql, order_sql,
        order_state_history_sql, order_box_sql, order_product_sql,
        box_product_sql, invoice_sql
    ]

    for table_sql in tables:
        mysql_manager.execute_query(table_sql, fetch=False)

    # Insert default order states
    insert_default_states()


def insert_default_states():
    """Insert default order states"""
    states = [
        ('Open', 'Order is open and ready for processing'),
        ('Picking', 'Order is being picked from inventory'),
        ('Packing', 'Order items are being packed'),
        ('Dispatch Ready', 'Order is ready for dispatch'),
        ('Completed', 'Order has been fully processed and dispatched'),
        ('Partially Completed', 'Order has been partially completed with remaining items')
    ]

    for state_name, description in states:
        try:
            mysql_manager.execute_query(
                "INSERT IGNORE INTO order_state (state_name, description) VALUES (%s, %s)",
                (state_name, description),
                fetch=False
            )
        except Exception as e:
            print(f"Error inserting state {state_name}: {e}")