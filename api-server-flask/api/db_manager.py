"""
MySQL Database Connection Manager — with partition-aware query support.

Partitioning strategy
─────────────────────
Tables that grow with daily orders are partitioned by RANGE COLUMNS on their
date column (usually `created_at`).  MySQL prunes partitions automatically
when the query WHERE clause includes the partition column.

The helper  `partition_filter(table, alias)` returns a `(sql_fragment, params)`
tuple that callers inject into WHERE clauses to guarantee partition pruning for
every query on a partitioned table.

Tables partitioned      │ Partition column
────────────────────────┼────────────────
potential_order         │ created_at
potential_order_product │ created_at
invoice                 │ created_at
order_state_history     │ changed_at
order                   │ created_at
order_product           │ created_at
order_box               │ created_at
box_product             │ created_at
upload_batches          │ uploaded_at
jwt_token_blocklist     │ created_at

Tables NOT partitioned  (constants / slow-growing reference data)
────────────────────────
warehouse, company, dealer, product, box, users, roles, order_state,
transport_routes, customer_route_mappings, daily_route_manifests,
company_schema_mappings, invoice_processing_config, user_warehouse_company
"""

import os
import pymysql
import threading
from contextlib import contextmanager
from datetime import datetime, date

# Install PyMySQL as MySQLdb for compatibility
pymysql.install_as_MySQLdb()

# ─────────────────────────────────────────────────────────────────────────────
# Partition metadata
# ─────────────────────────────────────────────────────────────────────────────

PARTITION_WINDOW_MONTHS = 4   # how many past months to keep in active partitions

# Map each partitioned table to its partition column
PARTITION_COLUMN: dict = {
    'potential_order':         'created_at',
    'potential_order_product': 'created_at',
    'invoice':                 'created_at',
    'order_state_history':     'changed_at',
    'order':                   'created_at',
    'order_product':           'created_at',
    'order_box':               'created_at',
    'box_product':             'created_at',
    'upload_batches':          'uploaded_at',
    'jwt_token_blocklist':     'created_at',
}

PARTITIONED_TABLES = frozenset(PARTITION_COLUMN.keys())


def partition_window_start() -> datetime:
    """
    Returns the first moment of the calendar month that is
    PARTITION_WINDOW_MONTHS ago.

    Example (today = 2026-04-10):  returns datetime(2025, 12, 1, 0, 0, 0)
    """
    today = date.today()
    month = today.month - PARTITION_WINDOW_MONTHS
    year  = today.year
    while month <= 0:
        month += 12
        year  -= 1
    return datetime(year, month, 1, 0, 0, 0)


def partition_filter(table: str, alias: str = None) -> tuple:
    """
    Returns (sql_fragment, params_tuple) for injecting a partition-pruning
    WHERE condition into a query on a partitioned table.

    Usage
    ─────
        pf_sql, pf_params = partition_filter('potential_order', alias='po')
        query  = f"SELECT * FROM potential_order po WHERE {pf_sql} AND po.status = %s"
        result = mysql_manager.execute_query(query, pf_params + (status,))

    For non-partitioned tables the function returns ('1=1', ()) so callers can
    use it unconditionally without breaking anything.
    """
    col = PARTITION_COLUMN.get(table)
    if not col:
        return '1=1', ()
    qualified = f"{alias}.{col}" if alias else col
    return f"{qualified} >= %s", (partition_window_start(),)


def _generate_monthly_partitions(col: str, months_back: int = None) -> str:
    """
    Build the PARTITION BY RANGE COLUMNS clause for CREATE TABLE.

    Generates:
      - p_archive  : catches all data older than the window (safe bucket)
      - p_YYYY_MM  : one per month in the window + 1 extra buffer month
      - p_future   : MAXVALUE catch-all for future inserts
    """
    if months_back is None:
        months_back = PARTITION_WINDOW_MONTHS + 1   # 1 extra buffer month

    today = date.today().replace(day=1)

    # Compute archive boundary = start of (months_back) ago
    month = today.month - months_back
    year  = today.year
    while month <= 0:
        month += 12
        year  -= 1
    archive_cutoff = date(year, month, 1)

    parts = [f"  PARTITION p_archive VALUES LESS THAN ('{archive_cutoff.isoformat()}')"]

    for offset in range(months_back - 1, -2, -1):   # months_back-1 down to -1
        m = today.month - offset
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        # upper bound = first day of NEXT month
        nm = m + 1
        ny = y
        if nm > 12:
            nm = 1
            ny += 1
        name = f"p_{y:04d}_{m:02d}"
        parts.append(f"  PARTITION {name} VALUES LESS THAN ('{ny:04d}-{nm:02d}-01')")

    parts.append("  PARTITION p_future VALUES LESS THAN (MAXVALUE)")
    return f"PARTITION BY RANGE COLUMNS ({col}) (\n" + ",\n".join(parts) + "\n)"


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
                try:
                    conn.rollback()
                except Exception:
                    # Bug 42 fix: rollback failed — connection is broken.
                    # Close it and set to None so the finally block discards it
                    # instead of returning a dead connection to the pool.
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
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
                    cursor.fetchone()
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
        status VARCHAR(20) DEFAULT 'pending',
        role VARCHAR(20) DEFAULT 'viewer',
        INDEX idx_users_username (username),
        INDEX idx_users_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # JWT Token Blocklist — partitioned by created_at (grows with logins)
    _jwt_parts = _generate_monthly_partitions('created_at')
    jwt_blocklist_sql = f"""
    CREATE TABLE IF NOT EXISTS jwt_token_blocklist (
        id         INT      NOT NULL AUTO_INCREMENT,
        jwt_token  TEXT     NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id, created_at),
        INDEX idx_jwt_token_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_jwt_parts};
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
        dealer_code VARCHAR(50) NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_dealer_name (name),
        UNIQUE INDEX idx_dealer_code (dealer_code)
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

    # ── Partitioned tables ────────────────────────────────────────────────────
    # NOTE: FKs are intentionally absent on partitioned tables.
    # MySQL requires the partition key in every UNIQUE index (including PK),
    # which makes cross-table FK references impractical.
    # Referential integrity is enforced at the application layer instead.
    # ─────────────────────────────────────────────────────────────────────────

    _po_parts   = _generate_monthly_partitions('created_at')
    _osh_parts  = _generate_monthly_partitions('changed_at')

    # Potential Order — partitioned by created_at
    potential_order_sql = f"""
    CREATE TABLE IF NOT EXISTS potential_order (
        potential_order_id INT      NOT NULL AUTO_INCREMENT,
        original_order_id  VARCHAR(100) NOT NULL,
        b2b_po_number      VARCHAR(100) NULL,
        order_type         VARCHAR(20)  NULL,
        vin_number         VARCHAR(100) NULL,
        shipping_address   TEXT         NULL,
        source_created_by  VARCHAR(100) NULL,
        purchaser_sap_code VARCHAR(50)  NULL,
        purchaser_name     VARCHAR(255) NULL,
        warehouse_id       INT,
        company_id         INT,
        dealer_id          INT,
        order_date         DATETIME DEFAULT CURRENT_TIMESTAMP,
        requested_by       INT,
        status             VARCHAR(50) DEFAULT 'Open',
        box_count          INT         NOT NULL DEFAULT 1,
        invoice_submitted  TINYINT(1)  NOT NULL DEFAULT 0,
        upload_batch_id    INT NULL,
        created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (potential_order_id, created_at),
        INDEX idx_po_original_order_id (original_order_id),
        INDEX idx_po_status            (status),
        INDEX idx_po_order_date        (order_date),
        INDEX idx_po_warehouse_status  (warehouse_id, status),
        INDEX idx_po_company_status    (company_id, status),
        INDEX idx_po_invoice_submitted (invoice_submitted),
        INDEX idx_po_created_at        (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Potential Order Product — partitioned by created_at
    potential_order_product_sql = f"""
    CREATE TABLE IF NOT EXISTS potential_order_product (
        potential_order_product_id INT NOT NULL AUTO_INCREMENT,
        potential_order_id         INT,
        product_id                 INT,
        quantity                   INT NOT NULL,
        quantity_packed            INT DEFAULT 0,
        quantity_remaining         INT,
        mrp                        DECIMAL(10,2),
        total_price                DECIMAL(10,2),
        created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                 DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (potential_order_product_id, created_at),
        INDEX idx_pop_order_product (potential_order_id, product_id),
        INDEX idx_pop_created_at    (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Order — partitioned by created_at
    order_sql = f"""
    CREATE TABLE IF NOT EXISTS `order` (
        order_id           INT      NOT NULL AUTO_INCREMENT,
        potential_order_id INT,
        order_number       VARCHAR(255) NOT NULL,
        dispatched_date    DATETIME,
        delivery_date      DATETIME,
        status             VARCHAR(50) DEFAULT 'In Transit',
        box_count          INT NOT NULL DEFAULT 1,
        created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (order_id, created_at),
        INDEX idx_order_number     (order_number),
        INDEX idx_order_status     (status),
        INDEX idx_order_po_id      (potential_order_id),
        INDEX idx_order_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Order State History — partitioned by changed_at
    order_state_history_sql = f"""
    CREATE TABLE IF NOT EXISTS order_state_history (
        order_state_history_id INT      NOT NULL AUTO_INCREMENT,
        potential_order_id     INT,
        state_id               INT,
        changed_by             INT,
        changed_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (order_state_history_id, changed_at),
        INDEX idx_osh_order_state (potential_order_id, state_id),
        INDEX idx_osh_changed_at  (changed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_osh_parts};
    """

    # Order Box — partitioned by created_at
    order_box_sql = f"""
    CREATE TABLE IF NOT EXISTS order_box (
        box_id     INT      NOT NULL AUTO_INCREMENT,
        order_id   INT,
        name       VARCHAR(255) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (box_id, created_at),
        INDEX idx_order_box_order      (order_id),
        INDEX idx_order_box_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Order Product — partitioned by created_at
    order_product_sql = f"""
    CREATE TABLE IF NOT EXISTS order_product (
        order_product_id INT      NOT NULL AUTO_INCREMENT,
        order_id         INT,
        product_id       INT,
        quantity         INT NOT NULL,
        mrp              DECIMAL(10,2),
        total_price      DECIMAL(10,2),
        created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (order_product_id, created_at),
        INDEX idx_order_product_composite (order_id, product_id),
        INDEX idx_order_product_created   (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Box Product — partitioned by created_at
    box_product_sql = f"""
    CREATE TABLE IF NOT EXISTS box_product (
        box_product_id     INT      NOT NULL AUTO_INCREMENT,
        box_id             INT,
        product_id         INT,
        quantity           INT NOT NULL,
        potential_order_id INT,
        created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (box_product_id, created_at),
        INDEX idx_box_product_composite (box_id, product_id),
        INDEX idx_box_product_order     (potential_order_id),
        INDEX idx_box_product_created   (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_po_parts};
    """

    # Invoice — partitioned by created_at
    _inv_parts = _generate_monthly_partitions('created_at')
    invoice_sql = f"""
    CREATE TABLE IF NOT EXISTS invoice (
        invoice_id                   INT          NOT NULL AUTO_INCREMENT,
        potential_order_id           INT,
        warehouse_id                 INT,
        company_id                   INT,
        dealer_id                    INT NULL,
        invoice_number               VARCHAR(255) NOT NULL,
        original_order_id            VARCHAR(255) NOT NULL,
        invoice_date                 DATETIME,
        invoice_type                 VARCHAR(50),
        cancellation_date            DATETIME,
        total_invoice_amount         DECIMAL(12,2),
        invoice_header_type          VARCHAR(50),
        order_date                   DATETIME NULL,
        b2b_purchase_order_number    VARCHAR(100),
        b2b_order_type               VARCHAR(50),
        account_tin                  VARCHAR(50),
        cash_customer_name           VARCHAR(255),
        contact_first_name           VARCHAR(100),
        contact_last_name            VARCHAR(100),
        customer_category            VARCHAR(100),
        round_off_amount             DECIMAL(10,2),
        invoice_round_off_amount     DECIMAL(10,2),
        short_amount                 DECIMAL(10,2),
        realized_amount              DECIMAL(10,2),
        hmcgl_card_no                VARCHAR(100),
        campaign                     VARCHAR(100),
        packaging_forwarding_charges DECIMAL(10,2),
        tax_on_pf                    DECIMAL(10,2),
        type_of_tax_pf               VARCHAR(50),
        irn_number                   VARCHAR(100),
        irn_status                   VARCHAR(50),
        ack_number                   VARCHAR(100),
        ack_date                     DATETIME,
        credit_note_number           VARCHAR(100),
        irn_cancel                   VARCHAR(100),
        irn_status_cancel            VARCHAR(50),
        ack_number_cancel            VARCHAR(100),
        ack_date_cancel              DATETIME,
        uploaded_by                  INT,
        upload_batch_id              VARCHAR(100),
        created_at                   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (invoice_id, created_at),
        INDEX idx_invoice_number         (invoice_number),
        INDEX idx_invoice_original_order (original_order_id),
        INDEX idx_invoice_batch          (upload_batch_id),
        INDEX idx_invoice_date           (invoice_date),
        INDEX idx_invoice_composite      (warehouse_id, company_id, invoice_date),
        INDEX idx_invoice_created_at     (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_inv_parts};
    """

    # User-Warehouse-Company access table (paired access)
    user_warehouse_company_sql = """
    CREATE TABLE IF NOT EXISTS user_warehouse_company (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        warehouse_id INT NOT NULL,
        company_id INT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_user_wh_co (user_id, warehouse_id, company_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (warehouse_id) REFERENCES warehouse(warehouse_id),
        FOREIGN KEY (company_id) REFERENCES company(company_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Dynamic roles table
    roles_sql = """
    CREATE TABLE IF NOT EXISTS roles (
        role_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL UNIQUE,
        description TEXT,
        all_warehouses BOOLEAN DEFAULT FALSE,
        eway_bill_admin BOOLEAN DEFAULT FALSE,
        eway_bill_filling BOOLEAN DEFAULT FALSE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Order state permissions per role
    role_order_states_sql = """
    CREATE TABLE IF NOT EXISTS role_order_states (
        id INT AUTO_INCREMENT PRIMARY KEY,
        role_id INT NOT NULL,
        state_name VARCHAR(50) NOT NULL,
        UNIQUE KEY unique_role_state (role_id, state_name),
        FOREIGN KEY (role_id) REFERENCES roles(role_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Upload permissions per role
    role_uploads_sql = """
    CREATE TABLE IF NOT EXISTS role_uploads (
        id INT AUTO_INCREMENT PRIMARY KEY,
        role_id INT NOT NULL,
        upload_type VARCHAR(50) NOT NULL,
        UNIQUE KEY unique_role_upload (role_id, upload_type),
        FOREIGN KEY (role_id) REFERENCES roles(role_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Upload Batches — partitioned by uploaded_at
    _ub_parts = _generate_monthly_partitions('uploaded_at')
    upload_batches_sql = f"""
    CREATE TABLE IF NOT EXISTS upload_batches (
        id           INT          NOT NULL AUTO_INCREMENT,
        upload_type  VARCHAR(20)  NOT NULL,
        filename     VARCHAR(255),
        warehouse_id INT,
        company_id   INT,
        uploaded_by  INT,
        uploaded_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        record_count INT DEFAULT 0,
        status       VARCHAR(20) DEFAULT 'active',
        reverted_by  INT NULL,
        reverted_at  DATETIME NULL,
        PRIMARY KEY (id, uploaded_at),
        INDEX idx_upload_batches_type    (upload_type),
        INDEX idx_upload_batches_status  (status),
        INDEX idx_upload_batches_date    (uploaded_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    {_ub_parts};
    """

    # E-way bill automation tables
    transport_routes_sql = """
    CREATE TABLE IF NOT EXISTS transport_routes (
        route_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    customer_route_mappings_sql = """
    CREATE TABLE IF NOT EXISTS customer_route_mappings (
        mapping_id INT AUTO_INCREMENT PRIMARY KEY,
        dealer_id INT NOT NULL UNIQUE,
        route_id INT,
        distance INT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (dealer_id) REFERENCES dealer(dealer_id) ON DELETE CASCADE,
        FOREIGN KEY (route_id) REFERENCES transport_routes(route_id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    daily_route_manifests_sql = """
    CREATE TABLE IF NOT EXISTS daily_route_manifests (
        manifest_id INT AUTO_INCREMENT PRIMARY KEY,
        route_id INT NOT NULL,
        vehicle_number VARCHAR(50) NOT NULL,
        manifest_date DATE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY unique_route_date (route_id, manifest_date),
        FOREIGN KEY (route_id) REFERENCES transport_routes(route_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    company_schema_mappings_sql = """
    CREATE TABLE IF NOT EXISTS company_schema_mappings (
        mapping_id INT AUTO_INCREMENT PRIMARY KEY,
        company_id INT NOT NULL UNIQUE,
        invoice_no_col VARCHAR(100),
        customer_code_col VARCHAR(100),
        customer_name_col VARCHAR(100),
        irn_col VARCHAR(100),
        amount_col VARCHAR(100),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (company_id) REFERENCES company(company_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Generic key-value config table for invoice processing rules.
    # config_key 'bypass_order_type': order types that skip the Packed prerequisite.
    invoice_processing_config_sql = """
    CREATE TABLE IF NOT EXISTS invoice_processing_config (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        config_key   VARCHAR(50)  NOT NULL COMMENT 'Rule category, e.g. bypass_order_type',
        config_value VARCHAR(100) NOT NULL COMMENT 'Rule value, e.g. ZGOI',
        description  TEXT         NULL,
        is_active    TINYINT(1)   NOT NULL DEFAULT 1,
        created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE INDEX idx_config_key_value (config_key, config_value),
        INDEX        idx_config_key_active (config_key, is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    # Execute all table creation queries
    tables = [
        users_sql, jwt_blocklist_sql, warehouse_sql, company_sql,
        dealer_sql, box_sql, product_sql, order_state_sql,
        potential_order_sql, potential_order_product_sql, order_sql,
        order_state_history_sql, order_box_sql, order_product_sql,
        box_product_sql, invoice_sql, user_warehouse_company_sql,
        roles_sql, role_order_states_sql, role_uploads_sql, upload_batches_sql,
        transport_routes_sql, customer_route_mappings_sql, daily_route_manifests_sql,
        company_schema_mappings_sql, invoice_processing_config_sql,
    ]

    for table_sql in tables:
        mysql_manager.execute_query(table_sql, fetch=False)

    # Migrate existing tables
    _migrate_users_table()
    _migrate_potential_order_table()
    _migrate_box_count()
    _drop_city_tables()

    # Insert default order states
    insert_default_states()

    # Seed default roles into DB
    seed_default_roles()


def _migrate_users_table():
    """Add status and role columns to existing users table if missing"""
    try:
        mysql_manager.execute_query(
            "ALTER TABLE users ADD COLUMN status VARCHAR(20) DEFAULT 'pending'",
            fetch=False
        )
    except Exception:
        pass  # Column already exists

    try:
        mysql_manager.execute_query(
            "ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'viewer'",
            fetch=False
        )
    except Exception:
        pass  # Column already exists


def _drop_city_tables():
    """Drop legacy city-based tables — replaced by direct customer-route mappings."""
    for table in ('customer_city_mappings', 'route_cities'):
        try:
            mysql_manager.execute_query(f"DROP TABLE IF EXISTS {table}", fetch=False)
        except Exception:
            pass


def _migrate_box_count():
    """Add box_count column to potential_order and order tables if missing."""
    migrations = [
        "ALTER TABLE potential_order ADD COLUMN box_count INT NOT NULL DEFAULT 1 AFTER status",
        "ALTER TABLE `order` ADD COLUMN box_count INT NOT NULL DEFAULT 1 AFTER status",
    ]
    for sql in migrations:
        try:
            mysql_manager.execute_query(sql, fetch=False)
        except Exception:
            pass  # Column already exists


def _migrate_potential_order_table():
    """Add columns to potential_order if missing (idempotent)."""
    migrations = [
        "ALTER TABLE potential_order ADD COLUMN upload_batch_id INT NULL",
        "ALTER TABLE potential_order ADD COLUMN invoice_submitted TINYINT(1) NOT NULL DEFAULT 0",
        "ALTER TABLE potential_order ADD INDEX idx_po_invoice_submitted (invoice_submitted)",
    ]
    for sql in migrations:
        try:
            mysql_manager.execute_query(sql, fetch=False)
        except Exception:
            pass  # Column / index already exists

    # Seed invoice_processing_config bypass types if table exists but is empty
    try:
        mysql_manager.execute_query(
            "INSERT IGNORE INTO invoice_processing_config (config_key, config_value, description) "
            "VALUES ('bypass_order_type', 'ZGOI', "
            "'ZGOI orders bypass the Packed prerequisite — invoice upload moves them directly to Invoiced.')",
            fetch=False
        )
    except Exception:
        pass


def insert_default_states():
    """Insert default order states"""
    states = [
        ('Open', 'Order is open and ready for processing'),
        ('Picking', 'Order is being picked from inventory'),
        ('Packed', 'Order items are packed'),
        ('Invoiced', 'Order invoiced and ready for dispatch'),
        ('Dispatch Ready', 'Invoices uploaded, order ready for physical dispatch'),
        ('Completed', 'Order has been fully dispatched from warehouse'),
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


ALL_ORDER_STATES = ['Open', 'Picking', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed']
ALL_UPLOAD_TYPES = ['orders', 'invoices']


def seed_default_roles():
    """Seed default roles into DB if they don't exist yet."""
    defaults = [
        {
            'name': 'admin',
            'description': 'Full access to everything. All warehouses.',
            'all_warehouses': True,
            'eway_bill_admin': True,
            'eway_bill_filling': True,
            'order_states': ALL_ORDER_STATES,
            'uploads': ALL_UPLOAD_TYPES,
        },
        {
            'name': 'manager',
            'description': 'All order states and uploads. Assigned warehouses only.',
            'all_warehouses': False,
            'order_states': ALL_ORDER_STATES,
            'uploads': ALL_UPLOAD_TYPES,
        },
        {
            'name': 'warehouse_staff',
            'description': 'Open/Picking/Packed states. Order uploads only.',
            'all_warehouses': False,
            'order_states': ['Open', 'Picking', 'Packed'],
            'uploads': ['orders'],
        },
        {
            'name': 'dispatcher',
            'description': 'Invoiced/Dispatch Ready/Completed states. Invoice uploads only.',
            'all_warehouses': False,
            'order_states': ['Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed'],
            'uploads': ['invoices'],
        },
        {
            'name': 'viewer',
            'description': 'Open orders only. No uploads.',
            'all_warehouses': False,
            'order_states': ['Open'],
            'uploads': [],
        },
    ]

    for role in defaults:
        # Insert role if not exists
        existing = mysql_manager.execute_query(
            "SELECT role_id FROM roles WHERE name = %s", (role['name'],)
        )
        if existing:
            continue  # already seeded, don't overwrite admin customisations

        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                "INSERT INTO roles (name, description, all_warehouses, eway_bill_admin, eway_bill_filling) VALUES (%s, %s, %s, %s, %s)",
                (role['name'], role['description'], role['all_warehouses'], role.get('eway_bill_admin', False), role.get('eway_bill_filling', False))
            )
            role_id = cursor.lastrowid

        for state in role['order_states']:
            mysql_manager.execute_query(
                "INSERT IGNORE INTO role_order_states (role_id, state_name) VALUES (%s, %s)",
                (role_id, state), fetch=False
            )
        for upload in role['uploads']:
            mysql_manager.execute_query(
                "INSERT IGNORE INTO role_uploads (role_id, upload_type) VALUES (%s, %s)",
                (role_id, upload), fetch=False
            )