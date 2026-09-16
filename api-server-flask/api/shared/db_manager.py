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

# The company this deployment serves. One backend instance ⇄ one company ⇄ one
# schema (see docs/schema-per-company.md). Names the tenant for the few code
# paths that used to dispatch by matching the company row's name (product packs,
# DMS builders). Defaults to this build's company.
COMPANY_KEY = (os.getenv('COMPANY_KEY') or 'cadila').strip().lower()

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
        self._verify_schema()

    def _verify_schema(self):
        """Log the schema this instance is bound to, and refuse an empty one.

        One deployment serves one company; a misconfigured instance connecting to
        the wrong (or no) schema would silently read and write another company's
        data. This surfaces the binding at boot so that can't pass unnoticed.
        """
        want = self.config['database']
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DATABASE() AS db")
                    have = (cur.fetchone() or {}).get('db')
        except Exception as e:
            logger.warning("Could not verify DB schema at startup", extra={'error': str(e)})
            return
        if not have:
            raise RuntimeError("No database selected — set DB_SCHEMA (or DB_NAME).")
        if have != want:
            logger.error("DB schema mismatch: configured %s, connected to %s", want, have)
        logger.info("DB ready: schema=%s company=%s", have, COMPANY_KEY)

    def _get_db_config(self):
        """Get database configuration from environment variables.

        Per-company schema routing: one deployment serves one company, and its
        schema (database) is chosen here at boot. `DB_SCHEMA` is the canonical
        selector; `DB_NAME` is accepted as the legacy alias. Everything else —
        host, credentials — is shared across the per-company deployments on the
        one MySQL server. All SQL in this codebase is schema-implicit, so binding
        the schema in the connection is the whole of the routing.
        """
        return {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', '3306')),
            'user': os.getenv('DB_USERNAME', 'root'),
            'password': os.getenv('DB_PASS', 'root-pw'),
            'database': os.getenv('DB_SCHEMA') or os.getenv('DB_NAME', 'warehouse_management'),
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
            except Exception:
                # The rollback's OWN failure must never replace the error that caused it.
                # When a query trips PyMySQL's 60s read_timeout the connection is already
                # dead, so ROLLBACK raises InterfaceError(0, '') — and re-raising that
                # threw away the real OperationalError(2013, 'Lost connection to MySQL
                # server during query'), the only thing that says what went wrong. A slow
                # query and a broken one became indistinguishable in the log.
                # The dead connection is still discarded, by get_connection's handler.
                try:
                    conn.rollback()
                except Exception:
                    logger.warning(
                        "rollback failed after a query error — connection is broken; "
                        "reporting the original error", exc_info=True)
                raise
            finally:
                # close() on a dead connection raises too, and an exception from a finally
                # block replaces the in-flight one just as effectively as the rollback did.
                try:
                    cursor.close()
                except Exception:
                    pass

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
    # Idempotency claims for retryable writes. shared/idempotency.py reads and
    # writes this table on every guarded endpoint but nothing ever created it, so
    # POST /api/v1/orders raised 1146 "table doesn't exist" before a single line of
    # order logic ran — and because the app queues first and retries, the order sat
    # on the phone reporting "waiting for a connection" forever.
    #
    # idem_key is the PRIMARY KEY on purpose: it is what makes two simultaneous
    # retries safe, since exactly one INSERT can win and the loser is handled as an
    # in-flight duplicate. `response` holds the original reply so a retry whose
    # answer was lost replays instead of creating a second order.
    idempotency_keys_sql = """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        idem_key     VARCHAR(100) NOT NULL,
        user_id      INT          NOT NULL,
        endpoint     VARCHAR(100) NOT NULL,
        state        VARCHAR(20)  NOT NULL DEFAULT 'in_progress',
        status_code  INT          NULL,
        response     LONGTEXT     NULL,
        created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME     NULL,
        PRIMARY KEY (idem_key),
        INDEX idx_idem_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """

    tables = [
        idempotency_keys_sql,
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
    import api.modules.inventory.ingestion.schema      # noqa: F401
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
    _migrate_company_id()
    _migrate_dealer_visits_columns()
    _migrate_transferin_id_varchar()
    _migrate_fc_entity_stock_company_uq()
    _migrate_order_product_batch_columns()
    _migrate_dms_quantity_column()
    _migrate_temp_inventory_uploaded_index()
    # Packaging / pricing model: the tables come from the schema registry, these carry
    # the column and the reference data the registry cannot.
    _migrate_product_gst_percent()
    seed_default_uoms()
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
      sales_executive_id sales/field_sales — how a sale is attributed
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
      nickname        set by the Product Nickname admin tab; read by the catalog SKU list
                      and printed on supply-sheet PDFs
      litres_per_unit volume of one selling unit, for targets set in litres

    These are declared in migration_v2_api.sql, which cannot be applied wholesale to a
    freshly-created schema (it carries ALTERs written against production's older lineage).
    Without them the catalog read and the corresponding admin uploads fail with
    'Unknown column'.

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
    ('dealer_visits',                   'dealer_id',          'idx_dv_company'),
    ('upload_batches',                  'warehouse_id',       'idx_ub_company'),
    ('dealer_location_submissions',     'dealer_id',          'idx_dls_company'),
]


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
        # The per-unit rate an order line was priced at, mirroring
        # submitted_order_products.net_rate. Distinct from `mrp`: MRP is the printed
        # maximum, net_rate is what this line is actually billed at.
        ('net_rate',           'DECIMAL(12,4) NULL', None),
        ('sku_code',           'VARCHAR(100) NULL', None),
        ('product_name',       'VARCHAR(255) NULL', None),
        ('uom',                'VARCHAR(20) NULL',  None),
        ('quantity_fulfilled', 'INT NULL',          None),
        ('item_status',        "VARCHAR(30) NOT NULL DEFAULT 'pending'", None),
    ],
    'submitted_orders': [
        # Location provenance. service_v1.create_order writes all three on every
        # order — _location_columns() builds them — but the columns were never
        # added, so the INSERT died with 1054 "Unknown column 'location_source'"
        # and no order raised from the app could be saved at all.
        #
        # They are what separates a live GPS fix from a cached one or a mocked
        # one, which is the whole point of auditing an order against where it was
        # raised. Nullable: an order queued by an older build carries no meta, and
        # that is missing information rather than a broken order.
        #
        # source is VARCHAR(16) to match _location_columns' own str(source)[:16].
        ('location_source',    'VARCHAR(16) NULL', None),
        ('location_age_s',     'INT NULL',         None),
        ('location_is_mocked', 'TINYINT(1) NULL',  None),
    ],
    'submitted_order_products': [
        # The rate the rep actually agreed with the dealer, per PRICED unit — the
        # same unit `quantity` is in, so the line is worth net_rate x quantity.
        #
        # Nullable because it is genuinely absent on most lines: every order from
        # the standard flow is captured without a price at all, and those are not
        # broken orders. NULL means "nobody quoted a rate", which a zero would
        # misreport as "quoted free".
        #
        # DECIMAL, not FLOAT: this is money and it gets multiplied by a quantity.
        # 4dp because a rate per strip runs to fractions of a paisa on the cost
        # side (2.9363), and rounding it at capture would make the line total
        # disagree with what the rep was shown.
        ('net_rate', 'DECIMAL(12,4) NULL', None),
        # What the rep actually ORDERED, before it was converted to the priced unit:
        # e.g. 2 CASE (order_quantity 2, order_uom 'CASE') that becomes `quantity`
        # strips. The order-detail / DMS read selects both, so a schema without them
        # fails with 1054 "Unknown column 'order_quantity'". Nullable: a line from the
        # standard flow is captured directly in the priced unit and has no pack level.
        ('order_quantity', 'DECIMAL(18,4) NULL', None),
        ('order_uom',      'VARCHAR(16) NULL',   None),
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


# Columns that create-vs-migrate left in two different shapes: the CREATE TABLE path and
# the ADD COLUMN path disagreed, so a database built fresh and one grown by migration ended
# up differing. Each entry pins ONE canonical definition, as (type, nullable, default)
# exactly as information_schema reports it once correct, plus the DDL that gets it there.
# Where the two shapes differed, the stricter one wins.
_CONVERGE_COLUMNS = [
    ('dealer', 'activated_on',
     ('datetime', 'YES', 'CURRENT_TIMESTAMP'), 'DATETIME NULL DEFAULT CURRENT_TIMESTAMP'),
    ('potential_order_product', 'item_status',
     ('varchar(30)', 'NO', 'pending'), "VARCHAR(30) NOT NULL DEFAULT 'pending'"),
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


def _migrate_order_product_batch_columns():
    """Add batch_id to the order line tables (idempotent).

    Pharma stock is tracked to a batch, and the outbound side has to record WHICH batch
    went to which customer — that is what a recall or an expiry return is answered from.
    The order line tables carried product and quantity only, so the batch was being
    dropped at the last step of an otherwise batch-tracked chain.

    Only the ID. The batch number and expiry live in `sku_batch.batch_params`, populated
    when inventory ingestion receives the stock; copying them here would be a second copy
    free to drift from the first.

    Nullable and empty for existing rows: Hero's flow does not populate them, and nothing
    reads them unless they are set.

    The registry only issues CREATE TABLE IF NOT EXISTS, so a DDL change never reaches a
    database that already has the table — this is what carries it.
    """
    for table in ('potential_order_product', 'order_product'):
        try:
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.TABLES
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
                continue
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                          AND COLUMN_NAME = 'batch_id'""", (table,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD COLUMN `batch_id` BIGINT UNSIGNED NULL",
                    fetch=False)
                logger.info("%s: added column batch_id", table)
            if not mysql_manager.execute_query(
                    """SELECT 1 FROM information_schema.STATISTICS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                          AND INDEX_NAME = 'idx_batch'""", (table,)):
                mysql_manager.execute_query(
                    f"ALTER TABLE `{table}` ADD INDEX idx_batch (batch_id)", fetch=False)
                logger.info("%s: indexed batch_id", table)

            # Denormalised copies briefly added alongside batch_id; sku_batch is the one
            # source for these, so they are removed where they exist.
            for stale in ('batch_number', 'expiry_date'):
                if mysql_manager.execute_query(
                        """SELECT 1 FROM information_schema.COLUMNS
                            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                              AND COLUMN_NAME = %s""", (table, stale)):
                    mysql_manager.execute_query(
                        f"ALTER TABLE `{table}` DROP COLUMN `{stale}`", fetch=False)
                    logger.info("%s: dropped redundant column %s", table, stale)
        except Exception:
            logger.exception("batch column migration failed for %s", table)


def _migrate_fc_entity_stock_company_uq():
    """Widen fc_entity_stock's unique key onto company_id (idempotent).

    The key was (planogram_id, location_id, bin_id, entity_id, entity_type, batch_id) —
    the grain stock accumulates at via ON DUPLICATE KEY UPDATE. But a warehouse holds
    stock for several companies at once (see modules/inventory/service.py), so two tenants
    with the same SKU and batch in the same bin land on ONE row and pool their quantities,
    with no error to show for it.

    This is the same shape as part_groups.uq_period_part, fixed above: a key written at a
    narrower grain than the thing it protects. Adding a column to a unique key only ever
    relaxes it, so every row the old key accepted is still accepted — this cannot fail on
    existing data. Requires company_id to exist, which _migrate_company_id adds.
    """
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fc_entity_stock'
                      AND COLUMN_NAME = 'company_id'"""):
            return   # tenant column has not landed here yet — nothing to widen onto
        if mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fc_entity_stock'
                      AND INDEX_NAME = 'planogram_id_new' AND COLUMN_NAME = 'company_id'"""):
            return   # already widened
        if mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fc_entity_stock'
                      AND INDEX_NAME = 'planogram_id_new'"""):
            mysql_manager.execute_query(
                "ALTER TABLE fc_entity_stock DROP INDEX planogram_id_new", fetch=False)
        mysql_manager.execute_query(
            """ALTER TABLE fc_entity_stock ADD UNIQUE KEY planogram_id_new
               (planogram_id, location_id, bin_id, entity_id, entity_type, batch_id,
                company_id)""", fetch=False)
        logger.info("fc_entity_stock.planogram_id_new widened onto company_id")
    except Exception:
        logger.exception("fc_entity_stock unique key migration failed")


def _migrate_transferin_id_varchar():
    """Widen transferin_info.transferin_id from BIGINT to VARCHAR (idempotent).

    It holds the supplier's invoice number, which is alphanumeric ('P000005'). As an
    integer it could only keep the digits, and the series prefix is meaningful: a receipt
    and a note can reduce to the same number ('P000002' vs 'PD00002').

    The registry only issues CREATE TABLE IF NOT EXISTS, so a DDL change never reaches a
    database that already has the table — this is what carries it. Widening an integer to
    a string cannot lose data: every existing value re-reads as its own digits.
    """
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transferin_info'"""):
            return
        rows = mysql_manager.execute_query(
            """SELECT DATA_TYPE FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transferin_info'
                  AND COLUMN_NAME = 'transferin_id'""")
        if not rows or rows[0]['DATA_TYPE'].lower() == 'varchar':
            return
        mysql_manager.execute_query(
            "ALTER TABLE transferin_info MODIFY COLUMN transferin_id VARCHAR(64) NOT NULL",
            fetch=False)
        logger.info("transferin_info.transferin_id widened to VARCHAR(64)")
    except Exception:
        logger.exception("transferin_id migration failed")


def _migrate_product_gst_percent():
    """Add product.gst_percent (idempotent).

    A core column, not an attribute: every company selling in India has a GST rate, and
    it sits beside hsn_code which already determines it. Kept on the product rather than
    on the price because the rate is a property of what the thing IS, not of what a
    given price list charges for it.
    """
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'product'
                     AND COLUMN_NAME = 'gst_percent'"""):
            # No positional AFTER: hsn_code is added by _migrate_v2_api_columns, which
            # runs after this, so a fresh schema has no hsn_code to sit beside yet. Column
            # order is cosmetic and not something convergence checks, so this is dropped.
            mysql_manager.execute_query(
                "ALTER TABLE product ADD COLUMN gst_percent DECIMAL(5,2) NULL", fetch=False)
            logger.info("product: added column gst_percent")
    except Exception:
        logger.exception("product: migration failed for column gst_percent")


# The unit names the packaging ladder is built from. Seeded rather than hard-coded so an
# admin can add one (TUBE, AMPOULE, JAR) without a code change.
_DEFAULT_UOMS = (
    ('PCS',    'Pieces',  'count'),
    ('UNIT',   'Unit',    'count'),
    ('TAB',    'Tablet',  'count'),
    ('STRIP',  'Strip',   'count'),
    ('BOX',    'Box',     'count'),
    ('CASE',   'Case',    'count'),
    ('BOTTLE', 'Bottle',  'count'),
    ('VIAL',   'Vial',    'count'),
    ('TUBE',   'Tube',    'count'),
    ('SACHET', 'Sachet',  'count'),
)


def seed_default_uoms():
    """Insert the standard unit codes if absent (idempotent, never overwrites)."""
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uom'"""):
            return
        existing = {r['uom_code'] for r in (
            mysql_manager.execute_query("SELECT uom_code FROM uom") or [])}
        missing = [u for u in _DEFAULT_UOMS if u[0] not in existing]
        if not missing:
            return
        with mysql_manager.get_cursor() as cursor:
            cursor.executemany(
                "INSERT INTO uom (uom_code, name, uom_type) VALUES (%s, %s, %s)", missing)
        logger.info("uom: seeded %d unit codes", len(missing))
    except Exception:
        logger.exception("uom: seeding failed")


def _migrate_temp_inventory_uploaded_index():
    """Add temp_inventory.idx_temp_inv_uploaded (uploaded_at) — idempotent.

    The DMS screen reads MAX(uploaded_at) on every load to decide whether stock is fresh
    enough to download against. Unindexed that is a full scan of the whole stock table
    (tens of thousands of parts) on a query that runs constantly.
    """
    table = 'temp_inventory'
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""", (table,)):
            return  # table not created yet; the registry DDL carries the index
        if mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                     AND INDEX_NAME = 'idx_temp_inv_uploaded'""", (table,)):
            return
        mysql_manager.execute_query(
            f"ALTER TABLE {table} ADD INDEX idx_temp_inv_uploaded (uploaded_at)",
            fetch=False)
        logger.info("%s: added idx_temp_inv_uploaded", table)
    except Exception:
        logger.exception("%s: migration failed for idx_temp_inv_uploaded", table)


def _migrate_dms_quantity_column():
    """Add submitted_order_products.dms_quantity (idempotent).

    Holds what the DMS file actually requested after stock allocation, so a re-download
    replays the same numbers instead of allocating a second time against already-reduced
    stock. The registry only issues CREATE TABLE IF NOT EXISTS, so this is what carries
    the column to a database that already has the table.
    """
    try:
        if not mysql_manager.execute_query(
                """SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE()
                     AND TABLE_NAME = 'submitted_order_products'
                     AND COLUMN_NAME = 'dms_quantity'"""):
            mysql_manager.execute_query(
                "ALTER TABLE submitted_order_products "
                "ADD COLUMN dms_quantity INT NULL AFTER mrp", fetch=False)
            logger.info("submitted_order_products: added column dms_quantity")
    except Exception:
        logger.exception(
            "submitted_order_products: migration failed for column dms_quantity")


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

    # A supplier invoice that IS the order (Cadila's GST invoice arrives as order_type
    # INVOICE) closes it: there is no pick/pack step, so the invoice upload deducts the
    # stock and completes the order. NOT EXISTS rather than INSERT IGNORE, so this does not
    # depend on a unique key the table may not carry — it must never add a second row.
    try:
        mysql_manager.execute_query(
            "INSERT INTO invoice_processing_config (config_key, config_value, description) "
            "SELECT 'complete_on_invoice_type', 'INVOICE', "
            "'INVOICE orders close on invoice upload: stock is deducted from the invoiced "
            "batches and the order moves straight to Completed.' "
            "FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM invoice_processing_config "
            "WHERE config_key = 'complete_on_invoice_type' AND config_value = 'INVOICE')",
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


# The single-screen roles, named once here because several places must agree on each
# string: this seed, the server-side scope check in shared/auth.py, and the React
# launcher / sidebar / AuthGuard. A typo in any of them silently grants full access.
_PART_CONVERTOR_ROLE_NAME = 'part_convertor'
_DMS_OPERATOR_ROLE_NAME = 'dms_operator'


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
        # Back-office transcription only: reads a paper order's photo and uploads the
        # part-convertor sheet that turns it into order lines. The name matters — the UI
        # (launcher tile, sidebar, AuthGuard) and the server-side scope check in
        # shared/auth.py all key on exactly 'part_convertor'.
        #
        # No order states and no uploads: `uploads` here governs the Upload Orders /
        # Invoices / Products screens, which this role must not see. The part-convertor
        # sheet is not one of those uploads — it goes through the Submitted Orders screen
        # and is allowed by the scope check, not by this flag.
        #
        # all_warehouses because the work is central: whoever transcribes photos handles
        # whatever arrives, and scoping them to assigned warehouses would silently hide
        # orders they are meant to process.
        {
            'name': _PART_CONVERTOR_ROLE_NAME,
            'description': 'Submitted Orders only. Reads order photos and uploads '
                           'part-convertor sheets. No other tabs or sections.',
            'all_warehouses': True,
            'order_states': [],
            'uploads': [],
        },
        # The other half of the DMS pipeline: uploads stock, allocates it into DMS files
        # and downloads them, raises phone/WhatsApp orders, and rejects what is wrong.
        # Confined to the Download DMS Input screen — it never sees Submitted Orders, so
        # transcription and dispatch stay separate people.
        #
        # `uploads: []` again governs only the Upload Orders / Invoices / Products screens.
        # This role's two uploads (stock and the manual order's parts sheet) both belong to
        # the DMS screen and are permitted by the scope check in shared/auth.py.
        {
            'name': _DMS_OPERATOR_ROLE_NAME,
            'description': 'Download DMS Input only. Uploads inventory, downloads DMS '
                           'files, raises manual orders. No other tabs or sections.',
            'all_warehouses': True,
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