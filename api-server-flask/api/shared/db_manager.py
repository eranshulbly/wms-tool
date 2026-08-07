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

import logging
import os
import pymysql
import threading
from contextlib import contextmanager
from datetime import datetime, date

logger = logging.getLogger(__name__)

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
                    logger.warning("Error creating pool connection", extra={'error': str(e)})

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
        logger.info("Connecting to MySQL database...")

        # Test database connection
        try:
            with mysql_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1 as test')
                    cursor.fetchone()
                logger.info("MySQL database connection successful")
        except Exception as conn_error:
            logger.critical("MySQL connection failed", exc_info=True)
            raise conn_error

        logger.info("Creating database tables...")
        create_all_tables()
        logger.info("MySQL database tables created successfully")

    except Exception as e:
        logger.critical("MySQL Database Exception during initialization", exc_info=True)
        raise e


def create_all_tables():
    """Create all required tables"""

    # Users table
    users_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        -- `name` is the person's display name, NOT a credential. Email is the only
        -- login, on the web app and the order app alike, which is why it is NOT NULL
        -- and UNIQUE while name is neither.
        name VARCHAR(32) NOT NULL,
        email VARCHAR(64) NOT NULL UNIQUE,
        password TEXT,
        jwt_auth_active BOOLEAN DEFAULT FALSE,
        date_joined DATETIME DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'pending',
        role VARCHAR(20) DEFAULT 'viewer',
        INDEX idx_users_name (name),
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
        company_id INT NULL,
        sales_executive_id INT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_dealer_name (name),
        INDEX idx_dealer_company (company_id),
        INDEX idx_dealer_sales_exec (sales_executive_id),
        UNIQUE INDEX idx_dealer_code (dealer_code)
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
        supply_sheet BOOLEAN DEFAULT FALSE,
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
        dealer_sql, product_sql, order_state_sql,
        potential_order_sql, potential_order_product_sql, order_sql,
        order_state_history_sql, order_product_sql,
        invoice_sql, user_warehouse_company_sql,
        roles_sql, role_order_states_sql, role_uploads_sql, upload_batches_sql,
        transport_routes_sql, customer_route_mappings_sql, daily_route_manifests_sql,
        company_schema_mappings_sql, invoice_processing_config_sql,
    ]

    for table_sql in tables:
        mysql_manager.execute_query(table_sql, fetch=False)

    # Create tables owned by newer modules via the schema registry. Import each
    # module's schema so its register_table() calls fire, then create them.
    import api.modules.platform.catalog.schema      # noqa: F401
    import api.modules.fulfillment.order.schema        # noqa: F401
    import api.modules.inventory.schema    # noqa: F401
    import api.modules.fulfillment.assignment.schema   # noqa: F401
    import api.modules.sales.schema                    # noqa: F401
    import api.modules.platform.user_auth.schema       # noqa: F401
    import api.modules.logistics.supply_sheet.schema   # noqa: F401
    from api.shared import schema_registry

    # RENAMES RUN BEFORE THE DDL, NOT WITH THE OTHER MIGRATIONS.
    #
    # The registry only issues CREATE TABLE IF NOT EXISTS. A rename registered under the
    # NEW name therefore creates an empty table on the next boot, and a rename migration
    # running afterwards finds both names present, has no safe way to tell which holds the
    # truth, and leaves the data stranded in the old one while the app writes to the new.
    # Renaming first means the DDL below finds the table already there and does nothing.
    _migrate_dealer_target_rename()

    for _t in schema_registry.registered_tables():
        mysql_manager.execute_query(_t.ddl, fetch=False)

    # Seed the location master. These ids are semantic constants referenced by the
    # inventory flows (see modules/inventory/schema.py Location), so they are inserted
    # with explicit ids and never renumbered.
    from api.modules.inventory.schema import LOCATION_SEED
    for _id, _type, _pick, _bulk, _desc in LOCATION_SEED:
        mysql_manager.execute_query(
            """INSERT IGNORE INTO planogram_locations
                 (id, location_type, is_picking_enabled, is_bulk_location, location_description)
               VALUES (%s, %s, %s, %s, %s)""",
            (_id, _type, _pick, _bulk, _desc),
            fetch=False,
        )

    # Migrate existing tables
    _migrate_users_table()
    _migrate_potential_order_table()
    _migrate_box_count()
    _drop_city_tables()
    _migrate_roles_table()
    _migrate_dealer_columns()
    _migrate_product_columns()
    _migrate_invoice_columns()
    # _migrate_dealer_target_rename() is NOT called here — it runs before the registry
    # DDL above, because CREATE TABLE IF NOT EXISTS would otherwise create the new name
    # first and strand the old table's rows. Every target migration below locates the
    # table as `dealer_target` and depends on that having already happened.
    _migrate_company_id()
    _migrate_target_grain()
    # After _migrate_target_grain: that one creates the table's category-level shape on an
    # old database, and product_id is added relative to category_id.
    _migrate_dt_product_id()
    # After _migrate_dt_product_id: both rebuild uq_dt_grain, and this one must have
    # the last word on it — it widens the key onto target_level and target_type, which
    # product_id's version of the key knows nothing about.
    _migrate_target_type()
    _migrate_dealer_visits_columns()
    _migrate_busy_sales_gst()
    _migrate_part_groups_period()
    # After both _migrate_company_id (adds company_id) and _migrate_part_groups_period
    # (renames period -> time_period): the widened key names both of those columns.
    _migrate_part_groups_company_uq()
    # Runs last: it only adds columns, and several of the migrations above assume the
    # base tables already exist in their pre-v2 shape.
    _migrate_v2_api_columns()
    # Strictly last: it MODIFYs columns the migrations above are responsible for adding,
    # so it has to see the schema in its final shape.
    _migrate_schema_convergence()

    # Insert default order states
    insert_default_states()

    # Seed default roles into DB
    seed_default_roles()

    # Seed the base product categories
    seed_default_categories()


def _migrate_users_table():
    """Bring an existing users table up to the current shape (idempotent).

    Besides status/role, this renames `username` -> `name`. The column never held a
    credential — email is the login for both apps — and calling it username invited
    exactly the confusion of trying to sign in with it. Email also becomes NOT NULL,
    since a user without one could never log in at all.
    """
    try:
        has_username = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'
                 AND COLUMN_NAME = 'username'""")
        if has_username:
            mysql_manager.execute_query(
                "ALTER TABLE users CHANGE COLUMN username name VARCHAR(32) NOT NULL",
                fetch=False)
            logger.info("users: renamed column username -> name")
    except Exception:
        logger.exception("users: could not rename username -> name")

    try:
        # Only tighten email once every row has one — an ALTER against NULLs would fail
        # and, worse, a silent skip would leave a user who can never sign in.
        nulls = mysql_manager.execute_query(
            "SELECT COUNT(*) AS n FROM users WHERE email IS NULL OR email = ''")
        if nulls and not nulls[0]['n']:
            mysql_manager.execute_query(
                "ALTER TABLE users MODIFY COLUMN email VARCHAR(64) NOT NULL", fetch=False)
        elif nulls:
            logger.warning("users: %s row(s) have no email; leaving the column nullable "
                           "— those accounts cannot log in", nulls[0]['n'])
    except Exception:
        logger.exception("users: could not make email NOT NULL")

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


def _migrate_dealer_columns():
    """Add the dealer columns the feature modules expect (idempotent).

    The schema registry only issues CREATE TABLE IF NOT EXISTS, so a change to the dealer
    DDL never reaches a database that already has the table. Each column below is read by
    live code and its absence is a hard 'Unknown column' failure, not a degraded feature:

      company_id         sales/uploads — _dealer_map() scopes dealers to Hero
      sales_executive_id sales/field_sales, sales/target_tracker — how a sale is attributed
      town               logistics/supply_sheet — printed on the supply sheet
      latitude/longitude platform/user_auth — set when a location submission is approved

    `town` also lives in migration_supply_sheet.sql as a bare ADD COLUMN, which throws on a
    second run; this is the idempotent equivalent. Checks information_schema rather than
    swallowing exceptions, so a genuine ALTER failure is logged rather than hidden.
    """
    wanted = [
        ('company_id',         'INT NULL',           'idx_dealer_company'),
        ('sales_executive_id', 'INT NULL',           'idx_dealer_sales_exec'),
        ('town',               'VARCHAR(100) NULL',  None),
        ('latitude',           'DECIMAL(10,7) NULL', None),
        ('longitude',          'DECIMAL(10,7) NULL', None),
    ]
    for column, ddl, index_name in wanted:
        try:
            has_col = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dealer'
                     AND COLUMN_NAME = %s""", (column,))
            if not has_col:
                mysql_manager.execute_query(
                    f"ALTER TABLE dealer ADD COLUMN `{column}` {ddl}", fetch=False)
                logger.info("dealer: added column %s", column)

            if not index_name:
                continue  # filtered rarely / low cardinality — not worth an index

            has_idx = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dealer'
                     AND INDEX_NAME = %s""", (index_name,))
            if not has_idx:
                mysql_manager.execute_query(
                    f"ALTER TABLE dealer ADD INDEX `{index_name}` (`{column}`)", fetch=False)
                logger.info("dealer: added index %s", index_name)
        except Exception:
            logger.exception("dealer: migration failed for column %s", column)


def _migrate_product_columns():
    """Add the product columns the admin uploads write (idempotent).

      category_id     set by the Product Category upload (Order Uploads -> Product Categories)
      nickname        set by the Product Nickname admin tab; printed on supply sheet PDFs
      litres_per_unit volume of one selling unit, for targets set in litres

    The first two are declared in migration_v2_api.sql, which cannot be applied wholesale
    to a freshly-created schema (it carries ALTERs written against production's older
    lineage). Without them the corresponding admin upload fails with 'Unknown column'.

    litres_per_unit exists because Oil targets are set in LITRES while Busy bills oil in
    Pcs. — every row of the feed carries unit 'Pcs.', and the product master has no volume
    of its own. The product upload parses it out of the product name ("… 900 ML", "… ML900")
    and stores it here, so the analytics join is a multiplication rather than a regex over
    every sales row. NULL means "not known" and a litres target simply cannot count that
    product; 0 means "known to have no volume" (wax, sponges, cloths sitting in the Oil
    category). Those are different facts and the column keeps them apart.
    """
    wanted = [
        ('category_id',     'INT NULL',            'idx_product_category'),
        ('nickname',        'VARCHAR(200) NULL',   None),
        ('litres_per_unit', 'DECIMAL(10,4) NULL',  None),
    ]
    for column, ddl, index_name in wanted:
        try:
            has_col = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'product'
                     AND COLUMN_NAME = %s""", (column,))
            if not has_col:
                mysql_manager.execute_query(
                    f"ALTER TABLE product ADD COLUMN `{column}` {ddl}", fetch=False)
                logger.info("product: added column %s", column)

            if not index_name:
                continue

            has_idx = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'product'
                     AND INDEX_NAME = %s""", (index_name,))
            if not has_idx:
                mysql_manager.execute_query(
                    f"ALTER TABLE product ADD INDEX `{index_name}` (`{column}`)", fetch=False)
                logger.info("product: added index %s", index_name)
        except Exception:
            logger.exception("product: migration failed for column %s", column)


# (table, column to place company_id after, index name). This manifest — not the individual
# CREATE TABLE statements — is the authority for which tables carry the tenant column.
# create_all_tables() runs CREATE TABLE IF NOT EXISTS first and this immediately after, so a
# freshly-built database and an existing one converge on the same shape.
#
# NOT listed on purpose:
#   * physical topology (fc_planogram/floor/aisle/rack/shelf/bin) and rack templates — a bin
#     is company-agnostic; it holds whatever is stacked into it. The *stock row* carries the
#     company, not the shelf.
#   * shared lookups (planogram_locations, stacking_group, transferin_type, order_state,
#     understack_reason, roles, permissions) — global reference data.
#   * warehouse — many-to-many with company via user_warehouse_company; a single company_id
#     column there would be wrong.
_COMPANY_ID_TABLES = [
    # inventory: inbound, stock and the movement engine
    ('transferin_info',                 'planogram_id',       'idx_company_id'),
    ('fc_entity_stock',                 'planogram_id',       'idx_company_id'),
    ('fc_entity_stock_ledger',          'planogram_id',       'idx_company_id'),
    ('fc_entity_recommendation',        'planogram_id',       'idx_company_id'),
    ('entity_movement_request',         'planogram_id',       'idx_company_id'),
    ('entity_movement_details',         'request_id',         'idx_company_id'),
    ('entity_movement_recommendation',  'request_detail_id',  'idx_company_id'),
    # catalog
    ('sku_batch',                       'sku_id',             'idx_company_id'),
    ('product',                         'product_id',         'idx_product_company'),
    # order lifecycle — `order` had none while potential_order and invoice both did
    ('order',                           'potential_order_id', 'idx_order_company'),
    ('order_product',                   'order_id',           'idx_order_product_company'),
    ('potential_order_product',         'potential_order_id', 'idx_pop_company'),
    ('order_state_history',             'potential_order_id', 'idx_osh_company'),
    ('submitted_order_products',        'submitted_order_id', 'idx_sop_company'),
    ('submitted_order_attachments',     'submitted_order_id', 'idx_soa_company'),
    ('submitted_order_status_history',  'submitted_order_id', 'idx_sosh_company'),
    # sales feeds (busy_sales_data declares its own composite index in the DDL)
    ('dealer_visits',                   'dealer_id',          'idx_dv_company'),
    ('upload_batches',                  'warehouse_id',       'idx_ub_company'),
    ('part_groups',                     'part_number',        'idx_pg_company'),
    # dealer_money_target is no longer registered and is dropped on migrated databases.
    # Its entry stays because every migration here is guarded on the table existing (a
    # no-op once it is gone) and because _migrate_target_type's import SELECTs
    # mt.company_id — on a legacy database this is what guarantees the column is there
    # to read.
    ('dealer_money_target',             'dealer_id',          'idx_dmt_company'),
    ('dealer_target',                   'dealer_id',          'idx_dt_company'),
    ('dealer_location_submissions',     'dealer_id',          'idx_dls_company'),
]


def _migrate_dealer_target_rename():
    """dealer_part_group_target -> dealer_target, with its indexes (idempotent).

    The old name described the table's first job — part-group quantity targets — and
    stopped being true once it also carried category- and scheme-level targets in rupees.

    This has to run BEFORE every other migration that touches the table. All of them
    locate it by name in information_schema and return early when it is absent, so a
    database renamed after they ran would look fully migrated to them while a database
    renamed before they ran gets migrated normally. Ordering it first is what makes the
    two cases the same case.

    Renaming the INDEXES too is not cosmetic: _migrate_dt_product_id and
    _migrate_target_type both find, drop and re-add the unique key BY NAME. If the table
    arrived carrying uq_dpgt_grain while they looked for uq_dt_grain, they would not find
    it, would not drop it, and would add a SECOND unique key over almost the same columns
    — leaving the table with two keys and no obvious sign of which one rejected a row.

    A database that already has dealer_target (fresh install — the registry DDL creates it
    directly) does nothing here.
    """
    try:
        has_new = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dealer_target'""")
        has_old = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE()
                 AND TABLE_NAME = 'dealer_part_group_target'""")
        if has_old and not has_new:
            mysql_manager.execute_query(
                "RENAME TABLE dealer_part_group_target TO dealer_target", fetch=False)
            logger.info("renamed dealer_part_group_target -> dealer_target")
        elif has_old and has_new:
            # Both present: the rename already happened and something re-created the old
            # name, or a half-finished manual migration. Refuse to guess which holds the
            # truth — merging them wrongly would double or drop targets.
            logger.error(
                "both dealer_target and dealer_part_group_target exist. dealer_target is "
                "the live table; the old one is being ignored. Drop it once you have "
                "confirmed it holds nothing you need.")

        if not (has_old or has_new):
            return

        for old, new in (('uq_dpgt_grain', 'uq_dt_grain'),
                         ('idx_dpgt_category', 'idx_dt_category'),
                         ('idx_dpgt_product', 'idx_dt_product'),
                         ('idx_dpgt_level', 'idx_dt_level'),
                         ('idx_dpgt_company', 'idx_dt_company')):
            present = mysql_manager.execute_query(
                """SELECT INDEX_NAME FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dealer_target'
                     AND INDEX_NAME IN (%s, %s)""", (old, new))
            names = {r['INDEX_NAME'] for r in (present or [])}
            if old in names and new not in names:
                mysql_manager.execute_query(
                    f"ALTER TABLE dealer_target RENAME INDEX `{old}` TO `{new}`",
                    fetch=False)
                logger.info("dealer_target: renamed index %s -> %s", old, new)
            elif old in names and new in names:
                # Both exist — the duplicate-key case the docstring warns about, from a
                # database migrated by an earlier build. The old one is redundant.
                mysql_manager.execute_query(
                    f"ALTER TABLE dealer_target DROP INDEX `{old}`", fetch=False)
                logger.info("dealer_target: dropped superseded index %s", old)
    except Exception:
        logger.exception("dealer_target: rename migration failed")


def _migrate_dt_product_id():
    """Add dealer_target.product_id and widen uq_dt_grain onto it (idempotent).

    product_id is a target set against ONE product instead of a part group. Nothing writes
    it yet, so every existing target carries the 0 sentinel meaning "no single product".

    It is NOT NULL DEFAULT 0 rather than nullable, for exactly the reason _migrate_target_grain
    made `scheme` NOT NULL DEFAULT '': the column is part of the unique key, and MySQL treats
    every NULL in a UNIQUE index as distinct. A nullable product_id sitting in uq_dt_grain
    would make every row unique on sight and quietly retire the key — which exists to stop a
    malformed file double-loading a period and inflating every target it feeds.

    The key has to carry product_id before per-product targets can be written at all: two of
    them for the same dealer and category would share a blank part_group and scheme, so the
    old key would reject the second as a duplicate of the first.
    """
    table = 'dealer_target'
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
            return  # fresh install — the registry DDL already has the new shape

        col = mysql_manager.execute_query(
            """SELECT IS_NULLABLE FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND COLUMN_NAME = 'product_id'""", (table,))
        if not col:
            mysql_manager.execute_query(
                f"ALTER TABLE {table} "
                "ADD COLUMN product_id INT NOT NULL DEFAULT 0 AFTER category_id", fetch=False)
            mysql_manager.execute_query(
                f"ALTER TABLE {table} ADD INDEX idx_dt_product (product_id)", fetch=False)
            logger.info("%s: added column product_id", table)
        elif col[0]['IS_NULLABLE'] == 'YES':
            # Carried the nullable first cut of this column — settle the NULLs on the
            # sentinel before the key starts depending on the value being present.
            mysql_manager.execute_query(
                f"UPDATE {table} SET product_id = 0 WHERE product_id IS NULL", fetch=False)
            mysql_manager.execute_query(
                f"ALTER TABLE {table} MODIFY product_id INT NOT NULL DEFAULT 0", fetch=False)
            logger.info("%s: product_id is now NOT NULL DEFAULT 0", table)

        # Rebuild the unique key only if it isn't already keyed on product_id. Dropping and
        # re-adding is safe in either order here: 0 is constant across every existing row,
        # so the widened key is exactly as strict as the one it replaces and cannot fail on
        # duplicates that the old key already permitted.
        keyed = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND INDEX_NAME = 'uq_dt_grain' AND COLUMN_NAME = 'product_id'""", (table,))
        if not keyed:
            if mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND INDEX_NAME = 'uq_dt_grain'""", (table,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE {table} DROP INDEX uq_dt_grain", fetch=False)
            mysql_manager.execute_query(
                f"ALTER TABLE {table} ADD UNIQUE KEY uq_dt_grain "
                "(dealer_id, category_id, product_id, scheme, part_group, target_period)",
                fetch=False)
            logger.info("%s: widened uq_dt_grain onto product_id", table)
    except Exception:
        logger.exception("%s: migration failed for product_id", table)


def _migrate_target_type():
    """Unify every dealer target into dealer_target (idempotent).

    Before this, a target's meaning came from WHICH TABLE it sat in: rupees in
    dealer_money_target, units in dealer_target. That worked only while rupee
    targets existed at category grain alone. Scheme targets (Basket 1, Basket 2) are set
    in rupees, and dealer_money_target has no scheme column to put them in — so the
    discriminator has to move out of the table name and into the row.

    Three things happen here, once, on an existing database:

      1. target_level / target_type / target_uom / target_value are added.

      2. target_level is BACKFILLED from what the old rows leave blank — part_group set
         means part-group level, scheme-only means scheme level, neither means category.
         That inference is correct for the historical rows because the only loader that
         ever wrote them filled exactly one of those columns. It is not correct in
         general, which is why the column is stored from here on rather than re-derived:
         _load_part_groups writes `part_group = group or scheme`, so a basket that is not
         broken into groups produces rows whose scheme and part_group are the same text.

      3. dealer_money_target is COPIED IN as category-level value targets. Its grain
         (dealer, category, period) is a strict subset of this table's, so nothing is
         lost. The copy is guarded on target_level having been absent — i.e. it runs on
         the single boot that introduces the column — and is INSERT IGNORE besides, so a
         partially-completed run cannot double the rupee targets on the next one.

    dealer_money_target itself is never dropped here. Doing so would make this migration
    one-way, and would mean a migration destroying the only copy of a table it had just
    finished reading — one bug in the import above and the data is gone with it. It is no
    longer registered in sales/schema.py, so it is not recreated where it has already been
    dropped; where it still exists it simply stops being read, and an operator drops it by
    hand once the import has been confirmed.

    target_type joins uq_dt_grain because a dealer may legitimately carry both a unit
    and a rupee target on the same scheme. target_level joins it because a category-level
    and a scheme-level row can otherwise collide: an unbroken basket's scheme-level target
    and a part-group target on the group of the same name agree on every other key column.
    """
    table = 'dealer_target'

    def _has_column(col):
        return bool(mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND COLUMN_NAME = %s""", (table, col)))

    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
            return  # fresh install — the registry DDL already has the new shape

        # Whether THIS boot is the one introducing the level column decides whether the
        # backfill and the money-target import run. Read before anything is added.
        first_run = not _has_column('target_level')

        for column, ddl, after in (
                ('target_level', "VARCHAR(20) NOT NULL DEFAULT 'part_group'", 'scheme'),
                ('target_type',  "VARCHAR(10) NOT NULL DEFAULT 'qty'",        'target_level'),
                ('target_uom',   "VARCHAR(20) NOT NULL DEFAULT ''",           'target_type'),
                ('target_value', "DECIMAL(16,4) NOT NULL DEFAULT 0",          'target_qty')):
            if not _has_column(column):
                anchor = f" AFTER `{after}`" if _has_column(after) else ""
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}{anchor}", fetch=False)
                logger.info("%s: added column %s", table, column)

        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND INDEX_NAME = 'idx_dt_level'""", (table,)):
            mysql_manager.execute_query(
                f"ALTER TABLE `{table}` ADD INDEX idx_dt_level (target_level)", fetch=False)

        if first_run:
            # Every pre-existing row is a quantity target; only its level is in doubt.
            mysql_manager.execute_query(
                f"""UPDATE `{table}`
                       SET target_level = CASE
                               WHEN COALESCE(part_group, '') <> '' THEN 'part_group'
                               WHEN COALESCE(scheme, '')     <> '' THEN 'scheme'
                               ELSE 'category' END,
                           target_type  = 'qty'""", fetch=False)
            logger.info("%s: backfilled target_level for existing quantity targets", table)

        # Rebuild the unique key onto the two new discriminators. Safe in either order:
        # every existing row now carries a level derived from columns the old key already
        # covered and the single type 'qty', so the widened key is no looser on the data
        # that exists than the one it replaces.
        #
        # This MUST happen before the money-target import below. A category-level quantity
        # target has a blank scheme and a blank part_group — exactly the sentinels a
        # category-level rupee target carries — so under the OLD key the two are the same
        # row. The INSERT IGNORE would skip the rupee target as a duplicate and it would
        # vanish, silently, with the count reporting success.
        keyed = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND INDEX_NAME = 'uq_dt_grain' AND COLUMN_NAME = 'target_type'""", (table,))
        if not keyed:
            if mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND INDEX_NAME = 'uq_dt_grain'""", (table,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` DROP INDEX uq_dt_grain", fetch=False)
            mysql_manager.execute_query(
                f"ALTER TABLE `{table}` ADD UNIQUE KEY uq_dt_grain "
                "(dealer_id, category_id, target_level, product_id, scheme, part_group, "
                " target_type, target_period)", fetch=False)
            logger.info("%s: widened uq_dt_grain onto target_level + target_type", table)

        if first_run and mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'dealer_money_target'"""):
            before = (mysql_manager.execute_query(
                f"SELECT COUNT(*) AS n FROM `{table}`") or [{'n': 0}])[0]['n']
            mysql_manager.execute_query(
                f"""INSERT IGNORE INTO `{table}`
                      (dealer_id, category_id, product_id, part_group, scheme,
                       target_level, target_type, target_uom, target_qty, target_value,
                       target_period, company_id, created_at, updated_at)
                    SELECT mt.dealer_id, mt.category_id, 0, '', '',
                           'category', 'value', '', 0, mt.value_target,
                           mt.target_period, mt.company_id, NOW(), NOW()
                      FROM dealer_money_target mt
                     WHERE mt.category_id IS NOT NULL""", fetch=False)
            after = (mysql_manager.execute_query(
                f"SELECT COUNT(*) AS n FROM `{table}`") or [{'n': 0}])[0]['n']
            source = (mysql_manager.execute_query(
                "SELECT COUNT(*) AS n FROM dealer_money_target "
                "WHERE category_id IS NOT NULL") or [{'n': 0}])[0]['n']
            logger.info("%s: imported %s of %s rupee target(s) from dealer_money_target",
                        table, after - before, source)
            if after - before != source:
                # IGNORE swallowed something. The old table is still there and still
                # holds the truth, so this is recoverable — but only if someone knows.
                logger.error(
                    "%s: %s rupee target(s) from dealer_money_target were NOT imported "
                    "(duplicate key or bad dealer/category). dealer_money_target is "
                    "unchanged; reconcile it before relying on rupee targets.",
                    table, source - (after - before))
    except Exception:
        logger.exception("%s: migration failed for target level/type", table)


def _migrate_invoice_columns():
    """Add invoice columns the read path selects but the upload path never writes.

    `invoice_status` is declared in the Invoice model's field list and in the API response
    model, and the statistics/batch-detail queries SELECT it — but it is absent from
    repository._INVOICE_COLUMNS (the insert path) and from the table itself, so every one of
    those queries died with "Unknown column" and the endpoint silently returned zeros via
    its except block. Added nullable so the reads are valid; uploads simply leave it NULL.
    """
    try:
        has_col = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'invoice'
                 AND COLUMN_NAME = 'invoice_status'""")
        if not has_col:
            mysql_manager.execute_query(
                "ALTER TABLE invoice ADD COLUMN `invoice_status` VARCHAR(50) NULL",
                fetch=False)
            logger.info("invoice: added column invoice_status")
    except Exception:
        logger.exception("invoice: migration failed for invoice_status")


# Columns that existed only in migration_v2_api.sql — a file an operator had to run by
# hand. Nothing at boot applied it, so a fresh install came up missing all of these and
# the /api/v1 (mobile) endpoints failed against their own schema: catalog reads
# product.uom/barcode/is_active, orders read the potential_order location + approval
# fields, and the dealer endpoints read dealer.phone/email/gstin. Listing them here makes
# the boot path self-sufficient — the .sql file stays for historical deployments, but a
# clone-and-run no longer depends on remembering it.
#   table -> [(column, ddl, index_name|None)]
_V2_API_COLUMNS = {
    'product': [
        ('uom',       'VARCHAR(20) NULL',                 None),
        ('size',      'VARCHAR(100) NULL',                None),
        ('weight',    'DECIMAL(10,3) NULL',               None),
        ('barcode',   'VARCHAR(100) NULL',                None),
        ('hsn_code',  'VARCHAR(20) NULL',                 None),
        ('is_active', 'TINYINT(1) NOT NULL DEFAULT 1',    None),
        # Added with the Hero parts category mapping: the supplier's own grouping
        # (HHML Parts, HDX Parts, …) sitting one level under category_id.
        ('subcategory', 'VARCHAR(100) NULL', 'idx_product_subcategory'),
    ],
    'warehouse': [
        ('code',      'VARCHAR(20) NULL',              None),
        ('is_active', 'TINYINT(1) NOT NULL DEFAULT 1', None),
    ],
    'company': [
        ('order_capture_mode', "VARCHAR(20) NOT NULL DEFAULT 'itemised'", None),
    ],
    'dealer': [
        ('dealer_code',  'VARCHAR(50) NULL',  None),
        ('email',        'VARCHAR(255) NULL', None),
        ('phone',        'VARCHAR(32) NULL',  None),
        ('gstin',        'VARCHAR(20) NULL',  None),
        ('address',      'TEXT NULL',         None),
        ('status',       "VARCHAR(20) NOT NULL DEFAULT 'active'", None),
        ('activated_on', 'DATETIME NULL DEFAULT CURRENT_TIMESTAMP', None),
    ],
    'potential_order': [
        ('submitted_at',            'DATETIME NULL',      None),
        ('approved_at',             'DATETIME NULL',      None),
        ('approved_by',             'INT NULL',           None),
        ('rejection_reason',        'VARCHAR(255) NULL',  None),
        ('expected_delivery_date',  'DATE NULL',          None),
        ('notes',                   'TEXT NULL',          None),
        ('latitude',                'DECIMAL(10,7) NULL', None),
        ('longitude',               'DECIMAL(10,7) NULL', None),
        ('location_accuracy_m',     'FLOAT NULL',         None),
        ('location_captured_at',    'DATETIME NULL',      None),
    ],
    'potential_order_product': [
        ('sku_code',           'VARCHAR(100) NULL', None),
        ('product_name',       'VARCHAR(255) NULL', None),
        ('uom',                'VARCHAR(20) NULL',  None),
        ('quantity_fulfilled', 'INT NULL',          None),
        ('item_status',        "VARCHAR(30) NOT NULL DEFAULT 'pending'", None),
    ],
}


# Unique keys from the same file. These are not cosmetic: uq_product_string is what stops
# a re-upload creating a second row for a part (and, under the utf8mb4_unicode_ci
# collation, what makes '…000S' and '…000s' the same part). Added after the columns they
# cover. A duplicate already in the table makes the ALTER fail — logged, not hidden,
# because the right fix is to dedupe the data, not to skip the constraint.
_V2_API_UNIQUE_KEYS = [
    ('product',   'uq_product_string',  '(product_string)'),
    ('product',   'uq_product_barcode', '(barcode)'),
    ('warehouse', 'uq_warehouse_code',  '(code)'),
]


def _migrate_v2_api_columns():
    """Bring the v2/mobile-API columns in, for fresh and existing databases alike.

    Idempotent: checks information_schema rather than swallowing ALTER errors, so a
    genuine failure is logged instead of hidden. Every column is nullable (or defaulted)
    because existing rows predate it and there is no safe backfill.
    """
    for table, wanted in _V2_API_COLUMNS.items():
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
            continue
        for column, ddl, index_name in wanted:
            try:
                if not mysql_manager.execute_query(
                        """SELECT 1 FROM information_schema.COLUMNS
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                             AND COLUMN_NAME = %s""", (table, column)):
                    mysql_manager.execute_query(
                        f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}", fetch=False)
                    logger.info("%s: added column %s", table, column)
                if index_name and not mysql_manager.execute_query(
                        """SELECT 1 FROM information_schema.STATISTICS
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                             AND INDEX_NAME = %s""", (table, index_name)):
                    mysql_manager.execute_query(
                        f"ALTER TABLE `{table}` ADD INDEX `{index_name}` (`{column}`)",
                        fetch=False)
                    logger.info("%s: added index %s", table, index_name)
            except Exception:
                logger.exception("%s: migration failed for column %s", table, column)

    for table, key, cols in _V2_API_UNIQUE_KEYS:
        try:
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.TABLES
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
                continue
            if mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND INDEX_NAME = %s""", (table, key)):
                continue
            mysql_manager.execute_query(
                f"ALTER TABLE `{table}` ADD UNIQUE KEY `{key}` {cols}", fetch=False)
            logger.info("%s: added unique key %s", table, key)
        except Exception:
            logger.exception("%s: could not add unique key %s (duplicate rows?)", table, key)


def _migrate_busy_sales_gst():
    """Add the generated GST columns to busy_sales_data (idempotent).

    GST is a flat 18% of the line amount. Generated columns rather than loader-written
    values, so they can never drift from `amount`; STORED because analytics SUMs them
    over the whole feed. Existing rows are back-filled by the ALTER itself.
    """
    wanted = [
        ('gst',             'DECIMAL(16,4) AS (ROUND(amount * 0.18, 4)) STORED'),
        ('amount_with_gst', 'DECIMAL(16,4) AS (ROUND(amount * 1.18, 4)) STORED'),
    ]
    for column, ddl in wanted:
        try:
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'busy_sales_data'
                         AND COLUMN_NAME = %s""", (column,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE busy_sales_data ADD COLUMN `{column}` {ddl}", fetch=False)
                logger.info("busy_sales_data: added generated column %s", column)
        except Exception:
            logger.exception("busy_sales_data: migration failed for column %s", column)


# Columns that create-vs-migrate left in two different shapes: the CREATE TABLE path and
# the ADD COLUMN path disagreed, so a database built fresh and one grown by migration ended
# up differing. Each entry pins ONE canonical definition, as (type, nullable, default)
# exactly as information_schema reports it once correct, plus the DDL that gets it there.
# Where the two shapes differed, the stricter one wins.
_CONVERGE_COLUMNS = [
    # Read straight back to the mobile client by user_auth/router_v1.py — a NULL here
    # surfaces as `null` in the API response instead of the mode the app expects.
    ('company', 'order_capture_mode',
     ('varchar(20)', 'NO', 'itemised'), "VARCHAR(20) NOT NULL DEFAULT 'itemised'"),
    ('dealer', 'activated_on',
     ('datetime', 'YES', 'CURRENT_TIMESTAMP'), 'DATETIME NULL DEFAULT CURRENT_TIMESTAMP'),
    ('potential_order_product', 'item_status',
     ('varchar(30)', 'NO', 'pending'), "VARCHAR(30) NOT NULL DEFAULT 'pending'"),
    # These two matter most: category_id is part of uq_dmt_grain / uq_dt_grain, and
    # MySQL counts every NULL in a unique index as distinct. Left nullable, the key stops
    # blocking the duplicate loads it exists to block — on one database but not the other.
    # dealer_money_target stays listed for the legacy case only: its import filters on
    # `category_id IS NOT NULL`, so the column has to exist before the copy can run.
    ('dealer_money_target', 'category_id', ('int', 'NO', None), 'INT NOT NULL'),
    ('dealer_target', 'category_id', ('int', 'NO', None), 'INT NOT NULL'),
]


# Indexes whose NAME diverged rather than whose definition did: an older lineage created
# one name, the CREATE TABLE another, over identical columns. Renaming keeps a migrated
# database byte-identical to a fresh one without rebuilding the index.
#   (table, legacy name, canonical name)
_CONVERGE_INDEXES = [
    ('users', 'idx_users_username', 'idx_users_name'),
]


def _migrate_schema_convergence():
    """Pin the columns where a fresh build and a migrated build disagreed (idempotent).

    Runs last, after every ADD COLUMN migration, so the columns it MODIFYs already exist.
    Each column is checked against its canonical shape first, so a database already in the
    right shape issues no ALTER at all and this costs one information_schema read per boot.

    Tightening to NOT NULL is skipped, loudly, if the column still holds NULLs. Filling
    them would mean inventing a category_id, and a wrong id is worse than a delayed
    migration — the fix is to correct the data, then reboot.
    """
    for table, column, want, ddl in _CONVERGE_COLUMNS:
        try:
            row = mysql_manager.execute_query(
                """SELECT COLUMN_TYPE t, IS_NULLABLE n, COLUMN_DEFAULT d
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = %s""", (table, column))
            if not row:
                continue  # table or column absent on this deployment — nothing to pin
            if (row[0]['t'], row[0]['n'], row[0]['d']) == want:
                continue  # already canonical

            if want[1] == 'NO':
                nulls = mysql_manager.execute_query(
                    f"SELECT COUNT(*) c FROM `{table}` WHERE `{column}` IS NULL")
                if nulls and nulls[0]['c']:
                    logger.warning(
                        "%s.%s: %s row(s) still NULL — leaving nullable. Fix the data, "
                        "then restart to apply.", table, column, nulls[0]['c'])
                    continue

            mysql_manager.execute_query(
                f"ALTER TABLE `{table}` MODIFY `{column}` {ddl}", fetch=False)
            logger.info("%s.%s: pinned to %s", table, column, ddl)
        except Exception:
            logger.exception("%s.%s: convergence migration failed", table, column)

    for table, legacy, canonical in _CONVERGE_INDEXES:
        try:
            def _has(name):
                return mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND INDEX_NAME = %s""", (table, name))

            if not _has(legacy):
                continue                      # already canonical, or table absent
            if _has(canonical):
                # Both present: the canonical one covers it, so the legacy name is a
                # duplicate index costing writes for nothing.
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` DROP INDEX `{legacy}`", fetch=False)
                logger.info("%s: dropped duplicate index %s", table, legacy)
            else:
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` RENAME INDEX `{legacy}` TO `{canonical}`",
                    fetch=False)
                logger.info("%s: renamed index %s -> %s", table, legacy, canonical)
        except Exception:
            logger.exception("%s.%s: index convergence failed", table, legacy)


def _migrate_part_groups_period():
    """part_groups: drop `month`, rename `period` -> `time_period` (idempotent).

    `month` held the period's name ('July') alongside `period` = 2026-07-01, so it was
    pure duplication of a value the date already carries and nothing read it back.

    The rename is a plain RENAME COLUMN: MySQL rewrites uq_period_part and idx_period to
    point at the new name by itself, so the index *names* are deliberately left as they
    are — that keeps a migrated database byte-identical to what the registry DDL builds
    on a fresh install.
    """
    table = 'part_groups'

    def _column(name):
        return mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND COLUMN_NAME = %s""", (table, name))

    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
            return  # fresh install — the registry DDL already has the new shape

        if _column('month'):
            mysql_manager.execute_query(
                f"ALTER TABLE {table} DROP COLUMN `month`", fetch=False)
            logger.info("%s: dropped column month", table)

        # Guard on both names so a half-applied run, or a re-run, is a no-op.
        if _column('period') and not _column('time_period'):
            mysql_manager.execute_query(
                f"ALTER TABLE {table} RENAME COLUMN `period` TO `time_period`", fetch=False)
            logger.info("%s: renamed column period -> time_period", table)
    except Exception:
        logger.exception("%s: period/month migration failed", table)


def _migrate_part_groups_company_uq():
    """Widen uq_period_part onto company_id (idempotent).

    The key was (time_period, part_number) while the upload clears a period with
    `DELETE FROM part_groups WHERE time_period=%s AND company_id=%s`. Those two grains
    disagree, and the gap is reachable: a company loading a period it has never loaded
    before still collides with *another* company's rows for the same period and part, and
    its own scoped delete cannot clear them because they are not its rows. The operator
    sees "Duplicate entry '<period>-<part>' for key 'part_groups.uq_period_part'" on a
    period they have never uploaded. Keying on company_id puts the constraint at the same
    grain the loader replaces at.

    Rows predating the tenant column keep company_id NULL, and MySQL treats every NULL in a
    unique index as distinct — so those legacy rows fall out of this key. They are equally
    invisible to the company-scoped delete, so leaving them unconstrained is consistent
    with how the loader already treats them; they want a one-off cleanup, not a key.
    """
    table = 'part_groups'
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = 'company_id'""", (table,)):
            return  # _migrate_company_id has not landed here — nothing to widen onto

        keyed = mysql_manager.execute_query(
            """SELECT 1 FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                 AND INDEX_NAME = 'uq_period_part' AND COLUMN_NAME = 'company_id'""",
            (table,))
        if keyed:
            return

        if mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND INDEX_NAME = 'uq_period_part'""", (table,)):
            mysql_manager.execute_query(
                f"ALTER TABLE {table} DROP INDEX uq_period_part", fetch=False)
        # Adding a column to a unique key only ever relaxes it, so every row the old key
        # accepted is still accepted and this cannot fail on existing data.
        mysql_manager.execute_query(
            f"ALTER TABLE {table} ADD UNIQUE KEY uq_period_part "
            "(company_id, time_period, part_number)", fetch=False)
        logger.info("%s: widened uq_period_part onto company_id", table)
    except Exception:
        logger.exception("%s: migration failed for uq_period_part", table)


def _migrate_dealer_visits_columns():
    """Add the free-text visit note (idempotent).

    The registry only issues CREATE TABLE IF NOT EXISTS, so a DDL change never reaches a
    database that already has the table — this is what carries it to existing installs.
    """
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dealer_visits'
                     AND COLUMN_NAME = 'notes'"""):
            mysql_manager.execute_query(
                "ALTER TABLE dealer_visits ADD COLUMN notes TEXT NULL AFTER status",
                fetch=False)
            logger.info("dealer_visits: added column notes")
    except Exception:
        logger.exception("dealer_visits: migration failed for column notes")


def _migrate_target_grain():
    """Move the two target tables onto the category-level grain (idempotent).

    Money targets are set per (category, dealer, period) and quantity targets per
    (category, scheme, part_group, dealer, period). The tables predate the category
    dimension, so an existing database still carries the old dealer-level unique keys —
    and those actively block the new grain: uq_dealer_period allows a dealer only ONE
    money target per month, whatever its category. They have to go before the new keys
    can do their job (the upload replaces per category and relies on the key to stop a
    re-upload doubling a target instead of updating it).

    scheme becomes NOT NULL DEFAULT '' because it is part of the replacement key, and
    MySQL treats every NULL in a UNIQUE index as distinct — a NULL scheme would slip
    past the key on every upload.
    """
    # dealer_money_target appears here only for a database old enough to still have it —
    # the entry is a no-op everywhere else, and _migrate_target_type reads the table once
    # before it is dropped by hand.
    tables = {
        'dealer_money_target': {
            'drop_keys': ['uq_dealer_period'],
            'unique': ('uq_dmt_grain', '(dealer_id, category_id, target_period)'),
            'cat_index': 'idx_dmt_category',
        },
        'dealer_target': {
            'drop_keys': ['uq_dealer_group_period'],
            'unique': ('uq_dt_grain',
                       '(dealer_id, category_id, scheme, part_group, target_period)'),
            'cat_index': 'idx_dt_category',
        },
    }
    for table, spec in tables.items():
        try:
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.TABLES
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
                continue  # fresh install — the registry DDL already has the new shape

            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND COLUMN_NAME = 'category_id'""", (table,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD COLUMN category_id INT NULL AFTER dealer_id",
                    fetch=False)
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD INDEX {spec['cat_index']} (category_id)",
                    fetch=False)
                logger.info("%s: added column category_id", table)

            if table == 'dealer_target':
                mysql_manager.execute_query(
                    "UPDATE dealer_target SET scheme = '' WHERE scheme IS NULL",
                    fetch=False)
                mysql_manager.execute_query(
                    "ALTER TABLE dealer_target "
                    "MODIFY scheme VARCHAR(150) NOT NULL DEFAULT ''", fetch=False)

            for old in spec['drop_keys']:
                if mysql_manager.execute_query(
                        """SELECT 1 FROM information_schema.STATISTICS
                           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                             AND INDEX_NAME = %s""", (table, old)):
                    mysql_manager.execute_query(
                        f"ALTER TABLE `{table}` DROP INDEX `{old}`", fetch=False)
                    logger.info("%s: dropped stale unique key %s", table, old)

            name, cols = spec['unique']
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND INDEX_NAME = %s""", (table, name)):
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD UNIQUE KEY `{name}` {cols}", fetch=False)
                logger.info("%s: added unique key %s", table, name)
        except Exception:
            logger.exception("%s: target-grain migration failed", table)


def _migrate_company_id():
    """Add the company_id tenant column everywhere it belongs (idempotent).

    The schema registry only issues CREATE TABLE IF NOT EXISTS, so a DDL change never
    reaches a database that already has the table. This walks _COMPANY_ID_TABLES and ALTERs
    in anything missing, which is what makes the manifest above authoritative for both fresh
    and existing databases.

    Nullable by design: existing rows predate the column and there is no single safe
    backfill (company derives from product for stock rows, from the parent order for order
    children, from dealer for the sales feeds). Checks information_schema rather than
    swallowing exceptions — a silent failure here means company-scoped queries quietly
    under- or over-return, which is a data-leak class of bug, not a cosmetic one.
    """
    for table, after_col, index_name in _COMPANY_ID_TABLES:
        try:
            exists = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,))
            if not exists:
                continue  # feature not deployed here yet

            has_col = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND COLUMN_NAME = 'company_id'""", (table,))
            if not has_col:
                has_anchor = mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.COLUMNS
                       WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                         AND COLUMN_NAME = %s""", (table, after_col))
                after = f" AFTER `{after_col}`" if has_anchor else ""
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD COLUMN `company_id` INT NULL{after}",
                    fetch=False)
                logger.info("company_id: added to %s", table)

            has_idx = mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND INDEX_NAME = %s""", (table, index_name))
            if not has_idx:
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD INDEX `{index_name}` (`company_id`)",
                    fetch=False)
                logger.info("company_id: indexed %s.%s", table, index_name)
        except Exception:
            logger.exception("company_id: migration failed for %s", table)


# The starting category set. Seeded by name with INSERT IGNORE, so renaming or adding
# categories through the app is never undone by a restart.
DEFAULT_CATEGORIES = ['Oil', 'Battery', 'Tyre', 'Accessories', 'Pro Parts']


def seed_default_categories():
    """Seed the base product categories if they aren't present yet."""
    for name in DEFAULT_CATEGORIES:
        try:
            mysql_manager.execute_query(
                "INSERT IGNORE INTO categories (name, is_active) VALUES (%s, 1)",
                (name,), fetch=False)
        except Exception:
            logger.exception("categories: failed to seed %s", name)


def _migrate_roles_table():
    """Add new boolean columns to existing roles table if missing (idempotent)."""
    migrations = [
        "ALTER TABLE roles ADD COLUMN supply_sheet BOOLEAN DEFAULT FALSE",
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
            logger.warning("Error inserting state", extra={'state_name': state_name, 'error': str(e)})


ALL_ORDER_STATES = ['Open', 'Picking', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed']
ALL_UPLOAD_TYPES = ['orders', 'invoices', 'products']


def seed_default_roles():
    """Seed default roles into DB if they don't exist yet."""
    defaults = [
        {
            'name': 'admin',
            'description': 'Full access to everything. All warehouses.',
            'all_warehouses': True,
            'eway_bill_admin': True,
            'eway_bill_filling': True,
            'supply_sheet': True,
            'order_states': ALL_ORDER_STATES,
            'uploads': ALL_UPLOAD_TYPES,
        },
        {
            'name': 'manager',
            'description': 'All order states and uploads. Assigned warehouses only.',
            'all_warehouses': False,
            'supply_sheet': True,
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
        # Sales-Executive Analytics attributes every sale through
        # dealer.sales_executive_id -> users.id, and filters on users.role =
        # 'sales_executive'. Without this role the executive breakdown is always empty.
        {
            'name': 'sales_executive',
            'description': 'Field sales. Own dealers analytics only. No order states or uploads.',
            'all_warehouses': False,
            'order_states': [],
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
                "INSERT INTO roles (name, description, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet) VALUES (%s, %s, %s, %s, %s, %s)",
                (role['name'], role['description'], role['all_warehouses'], role.get('eway_bill_admin', False), role.get('eway_bill_filling', False), role.get('supply_sheet', False))
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