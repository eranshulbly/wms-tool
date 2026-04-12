# WMS Backend — Architecture & Knowledge Reference

A complete technical reference for the Flask backend located at `api-server-flask/api/`. Read this before touching any backend code.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [Application Bootstrap](#2-application-bootstrap)
3. [Configuration Layer](#3-configuration-layer)
4. [Database Layer](#4-database-layer)
5. [Models Layer](#5-models-layer)
6. [Constants & Enums](#6-constants--enums)
7. [Core Cross-Cutting Concerns](#7-core-cross-cutting-concerns)
8. [Business Logic Layer](#8-business-logic-layer)
9. [Repositories Layer](#9-repositories-layer)
10. [Services Layer](#10-services-layer)
11. [Validation Layer](#11-validation-layer)
12. [Routes Package](#12-routes-package)
13. [Design Patterns Reference](#13-design-patterns-reference)
14. [Authentication & Authorization Flow](#14-authentication--authorization-flow)
15. [Order Lifecycle](#15-order-lifecycle)
16. [Key Function Signatures](#16-key-function-signatures)

---

## 1. Directory Structure

```
api-server-flask/api/
├── __init__.py                   # create_app() factory + utility routes
├── extensions.py                 # Module-level Flask extension singletons
├── config.py                     # Environment-specific configuration
├── db_manager.py                 # MySQL connection pool + partition helpers
├── partition_manager.py          # Monthly partition lifecycle management
├── models.py                     # Direct-SQL model classes (~1320 lines, no ORM)
├── admin.py                      # Flask-Admin interface
├── permissions.py                # RBAC: get_permissions(), can_upload(), etc.
│
├── core/                         # Framework-level cross-cutting concerns
│   ├── auth.py                   # @token_required, @active_required, @upload_permission_required
│   ├── exceptions.py             # WMSException hierarchy
│   └── logging.py                # Structured logging (JSON in prod, colored in dev)
│
├── constants/                    # All enums and string constants
│   ├── order_states.py           # OrderStatus enum
│   └── upload_types.py           # UploadType, UserRole, UserStatus enums
│
├── business/                     # Business logic — no Flask, no file I/O
│   ├── order_state_machine.py    # Single source of truth for state transition rules
│   ├── order_business.py         # Order bulk upload processing
│   ├── invoice_business.py       # Invoice upload processing (3-phase)
│   ├── product_upload_business.py# Product upload processing (3-phase)
│   ├── dealer_business.py        # Dealer lookup/create with in-memory cache
│   └── product_business.py       # Product lookup/create with in-memory cache
│
├── repositories/                 # Data access layer — all SQL lives here
│   ├── base_repository.py        # BaseRepository(mysql_manager, partition_filter)
│   ├── order_repository.py       # PotentialOrder, OrderState, OrderStateHistory queries
│   ├── invoice_repository.py     # Invoice bulk inserts and state transitions
│   ├── product_repository.py     # Product and PotentialOrderProduct queries
│   ├── user_repository.py        # Users and JWTTokenBlocklist queries
│   └── reference_repository.py  # Warehouse, Company, Dealer, Box queries
│
├── services/                     # Orchestration — file handling + transactions
│   ├── base_upload_service.py    # Template Method: abstract 8-step upload pipeline
│   ├── upload_factory.py         # UploadProcessorFactory
│   ├── order_service.py          # OrderUploadService
│   ├── invoice_service.py        # InvoiceUploadService
│   └── product_service.py        # ProductUploadService
│
├── validation/                   # Input validation (no DB calls, raises no exceptions)
│   ├── upload_validators.py      # validate_warehouse_company_access, validate_file_extension
│   └── order_validators.py       # validate_warehouse_exists, validate_company_exists
│
├── routes/                       # All HTTP route definitions
│   ├── __init__.py               # register_all_routes() + backward-compat re-exports
│   ├── auth_routes.py            # /api/users/* (Register, Login, EditUser, LogoutUser)
│   ├── order_routes.py           # /api/orders/* (8 endpoints)
│   ├── invoice_routes.py         # /api/invoices/* (6 endpoints)
│   ├── product_routes.py         # /api/products/upload
│   ├── dashboard_routes.py       # /api/warehouses, /api/companies, /api/orders (listing)
│   ├── admin_routes.py           # /api/admin/upload-batches/*
│   └── eway_bill_routes.py       # /api/eway/* (11 endpoints)
│
└── utils/
    └── upload_utils.py           # File I/O, DataFrame parsing, error Excel generation
```

**Dependency graph (leaf → root, no cycles):**

```
constants/
  └─► core/exceptions
        └─► core/auth, core/logging
              └─► models, db_manager
                    └─► repositories/
                          └─► business/
                                └─► services/
                                      └─► routes/
                                            └─► __init__.py (create_app)
```

---

## 2. Application Bootstrap

### `api/__init__.py` — Application Factory

```python
def create_app(config_override: dict = None) -> Flask:
```

Called once at startup. Execution order matters:

1. Create Flask app (`template_folder='templates'`)
2. Load environment config via `get_config()`
3. Set `SECRET_KEY` from env or fallback
4. `configure_logging(app)` — must be first, before any logger calls
5. Import `rest_api` from `extensions.py` (the canonical singleton)
6. Call `register_all_routes()` — fires all `@rest_api.route()` decorators
7. `rest_api.init_app(app)` — binds routes to Flask app
8. `CORS(app)` — enable CORS
9. `initialize_database()` — MySQL connection pool + table creation
10. `init_admin(app)` — Flask-Admin interface
11. `_register_error_handlers(app)` — `after_request` normalizer
12. `_register_utility_routes(app)` — `/health`, `/api/status`, `/api/version`

**Module-level line:**
```python
app = create_app()  # Gunicorn entry: gunicorn "api:app"
```

### Utility Routes (registered in `_register_utility_routes`)

| Endpoint | Purpose |
|---|---|
| `GET /health` | DB connectivity check; returns `{"status": "healthy"}` |
| `GET /api/status` | Warehouse/company counts + order counts by status |
| `GET /api/version` | Returns `APP_VERSION` and `APP_ENV` env vars |

### Error Response Normalization

`@app.after_request` intercepts all responses with `status >= 400` and rewrites them to:
```json
{"success": false, "msg": "..."}
```

---

## 3. Configuration Layer

### `api/config.py`

| Class | `APP_ENV` value | Key differences |
|---|---|---|
| `DevelopmentConfig` | `development` | DEBUG=True, 24h token, pool 3/5 |
| `StagingConfig` | `staging` | DEBUG=False, 4h token, pool 5/10 |
| `ProductionConfig` | `production` | DEBUG=False, 1h token, pool 10/20 |

`get_config()` reads `APP_ENV` env var and returns the appropriate class.

**Key env vars:**
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_PORT`, `DB_NAME` — MySQL connection
- `SECRET_KEY` — JWT signing key
- `APP_ENV` — selects config class
- `APP_VERSION` — returned by `/api/version`

---

## 4. Database Layer

### `api/db_manager.py` — MySQL Connection Manager

The backend uses **direct PyMySQL** with a custom connection pool. No ORM.

**Singleton:** `mysql_manager: MySQLManager` — imported everywhere.

**Three usage patterns:**

```python
# 1. Execute a query and get results
rows = mysql_manager.execute_query(sql, params)         # returns list[dict]
rowcount = mysql_manager.execute_query(sql, params, fetch=False)  # returns int

# 2. Manual cursor (for multi-step transactions)
with mysql_manager.get_cursor(commit=True) as cursor:
    cursor.execute(sql, params)
    cursor.fetchall()

# 3. Raw connection (rare, for explicit transaction control)
with mysql_manager.get_connection() as conn:
    with conn.cursor() as cursor:
        ...
    conn.commit()
```

### Partition Filter

Many tables are partitioned by month. **Every query on partitioned tables must include a partition filter** to let MySQL prune partitions.

```python
from .db_manager import partition_filter

pf_sql, pf_params = partition_filter('potential_order', alias='po')
# pf_sql  → "po.created_at >= %s"
# pf_params → (datetime(first_day_of_window),)

query = f"""
    SELECT * FROM potential_order po
    WHERE {pf_sql}
      AND po.status = %s
      AND po.warehouse_id = %s
"""
results = mysql_manager.execute_query(query, pf_params + (status, warehouse_id))
```

For non-partitioned tables, `partition_filter` returns `('1=1', ())` — safe to use unconditionally.

**Partitioned tables:**

| Table | Partition Column |
|---|---|
| `potential_order` | `created_at` |
| `potential_order_product` | `created_at` |
| `invoice` | `created_at` |
| `order_state_history` | `changed_at` |
| `order` | `created_at` |
| `order_product` | `created_at` |
| `order_box` | `created_at` |
| `box_product` | `created_at` |
| `upload_batches` | `uploaded_at` |
| `jwt_token_blocklist` | `created_at` |

**Active window:** 4 months back from today. Older data is archived to `p_archive` partition.

### `api/partition_manager.py`

Manages the monthly partition lifecycle. Call at startup and via cron:

| Method | When to call |
|---|---|
| `ensure_current_month_partition()` | App startup (idempotent) |
| `add_next_month_partition()` | 1st of each month (cron) |
| `drop_old_partitions()` | After archiving to S3 (cron) |

---

## 5. Models Layer

### `api/models.py` — Direct SQL, No ORM

Models are plain Python classes with classmethods wrapping SQL. They are **not** SQLAlchemy models.

**General pattern:**
```python
class PotentialOrder:
    def __init__(self, row: dict): ...   # accepts DB dict row

    def save(self):                       # INSERT or UPDATE based on id presence
        ...

    @classmethod
    def get_by_id(cls, order_id) -> 'PotentialOrder | None':
        rows = mysql_manager.execute_query(...)
        return cls(rows[0]) if rows else None
```

**Key models:**

| Model | Table | Notes |
|---|---|---|
| `Users` | `users` | Auth + RBAC; has `check_password()`, `set_jwt_auth_active()` |
| `JWTTokenBlocklist` | `jwt_token_blocklist` | Token revocation; partitioned |
| `Warehouse` | `warehouses` | Reference data |
| `Company` | `companies` | Reference data |
| `Dealer` | `dealers` | Lookup/create via `dealer_business` |
| `Product` | `products` | Lookup/create via `product_business` |
| `Box` | `boxes` | Reference data |
| `PotentialOrder` | `potential_order` | Primary order entity; partitioned |
| `PotentialOrderProduct` | `potential_order_product` | Order-product links; partitioned |
| `OrderState` | `order_states` | State reference (not partitioned) |
| `OrderStateHistory` | `order_state_history` | Audit trail; partitioned |
| `Order` | `order` | Final shipped order; partitioned |
| `Invoice` | `invoice` | Invoice data; partitioned |
| `TransportRoute` | `transport_routes` | E-way bill routes |
| `CustomerRouteMapping` | `customer_route_mappings` | E-way bill customer assignments |
| `DailyRouteManifest` | `daily_route_manifests` | E-way bill manifests |
| `CompanySchemaMapping` | `company_schema_mappings` | E-way bill schema config |

---

## 6. Constants & Enums

### `api/constants/order_states.py`

```python
class OrderStatus(str, Enum):
    OPEN                = 'Open'
    PICKING             = 'Picking'
    PACKED              = 'Packed'
    INVOICED            = 'Invoiced'
    DISPATCH_READY      = 'Dispatch Ready'
    COMPLETED           = 'Completed'
    PARTIALLY_COMPLETED = 'Partially Completed'
```

The `str` mixin means `OrderStatus.OPEN == 'Open'` is `True`. All existing DB comparisons and SQL params work unchanged.

```python
OrderStatus.from_frontend_slug('dispatch-ready')  # → OrderStatus.DISPATCH_READY
OrderStatus.DISPATCH_READY.to_frontend_slug()     # → 'dispatch-ready'
```

### `api/constants/upload_types.py`

```python
class UploadType(str, Enum):
    ORDERS   = 'orders'
    INVOICES = 'invoices'
    PRODUCTS = 'products'

class UserRole(str, Enum):
    ADMIN           = 'admin'
    MANAGER         = 'manager'
    WAREHOUSE_STAFF = 'warehouse_staff'
    DISPATCHER      = 'dispatcher'
    VIEWER          = 'viewer'

class UserStatus(str, Enum):
    PENDING = 'pending'
    ACTIVE  = 'active'
    BLOCKED = 'blocked'
```

**Rule:** Never write string literals like `'Open'`, `'orders'`, `'pending'` in new code. Use the enums.

---

## 7. Core Cross-Cutting Concerns

### `api/core/auth.py` — Decorators

Three composable decorators, always stacked in this order:

```python
@rest_api.route('/api/orders/upload')
class OrderUpload(Resource):
    @token_required
    @active_required
    @upload_permission_required('orders')
    def post(self, current_user):
        ...
```

| Decorator | What it checks | Failure response |
|---|---|---|
| `@token_required` | Valid non-expired, non-revoked JWT token | 400 (missing) or 401 (invalid) |
| `@active_required` | User status != 'pending' | 403 with `status='pending'` |
| `@upload_permission_required(type)` | Role has upload permission for this type | 403 |

`@token_required` injects `current_user: Users` as the second positional argument (after `self`).

### `api/core/exceptions.py` — Exception Hierarchy

```
WMSException(message, http_status, payload)
├── DatabaseException
│   ├── ConnectionException           (503)
│   └── QueryException                (500)
├── BusinessRuleException             (400)
│   ├── InvalidStateTransitionException(current, target)
│   ├── OrderNotFoundException(order_id)    (404)
│   └── DuplicateOrderException(order_id)  (409)
├── UploadException                   (400)
│   ├── UnsupportedFileFormatException(ext)
│   ├── MissingColumnsException(missing, available)
│   └── EmptyFileException()
├── AuthException                     (401)
│   ├── TokenExpiredException()
│   ├── TokenRevokedException()
│   └── InsufficientPermissionException(action)
└── ValidationException(field, message)    (400)
```

All exceptions expose `.to_dict()` → `{"success": false, "error": "ClassName", "msg": "..."}`.

Route handlers can catch all domain errors generically:
```python
except WMSException as e:
    return e.to_dict(), e.http_status
```

### `api/core/logging.py` — Structured Logging

**Always use this, never `print()`:**

```python
from ..core.logging import get_logger

logger = get_logger(__name__)    # module-level, once

logger.info("Processing order", extra={"order_id": order_id, "user": user_id})
logger.warning("Duplicate row skipped", extra={"row": row_index})
logger.error("DB write failed", exc_info=True)
```

- **Production / Staging:** JSON format (Datadog/CloudWatch compatible)
- **Development:** Human-readable colored output
- Werkzeug and urllib3 noise silenced at WARNING level

---

## 8. Business Logic Layer

### `api/business/order_state_machine.py` — State Machine (Single Source of Truth)

**Never define state transition rules anywhere else.**

```python
class OrderStateMachine:
    # Bulk CSV upload: what state → what state
    BULK_TRANSITIONS = {
        OrderStatus.OPEN:           OrderStatus.PICKING,
        OrderStatus.PICKING:        OrderStatus.PACKED,
        OrderStatus.DISPATCH_READY: OrderStatus.COMPLETED,
    }

    # Single-order endpoint: what states are reachable from each state
    SINGLE_ORDER_TRANSITIONS = {
        OrderStatus.OPEN:                [OrderStatus.PICKING],
        OrderStatus.PICKING:             [OrderStatus.PACKED, OrderStatus.OPEN],
        OrderStatus.PACKED:              [OrderStatus.PICKING],
        OrderStatus.INVOICED:            [],
        OrderStatus.DISPATCH_READY:      [],
        OrderStatus.COMPLETED:           [],
        OrderStatus.PARTIALLY_COMPLETED: [],
    }

    TERMINAL_STATES = frozenset({INVOICED, DISPATCH_READY, COMPLETED, PARTIALLY_COMPLETED})
    PRE_PACKED_STATES = frozenset({OPEN, PICKING})
```

**Query methods:**
```python
OrderStateMachine.can_bulk_transition(current, target) → bool
OrderStateMachine.can_single_transition(current, target) → bool
OrderStateMachine.required_source_for_bulk(target) → OrderStatus | None
OrderStateMachine.is_terminal(status) → bool
OrderStateMachine.is_pre_packed(status) → bool
```

### `api/business/order_business.py` — Order Upload

```python
process_order_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None)
    → {orders_processed: int, error_rows: [{order_id, name, reason}]}
```

- One row = one order
- Calls `dealer_business.get_or_create_dealer()` for each row
- Creates PotentialOrder with `status=OrderStatus.OPEN`
- Handles duplicate original_order_id as error row

### `api/business/invoice_business.py` — Invoice Upload (3-Phase)

```python
process_invoice_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None)
    → {invoices_processed: int, orders_invoiced: int, orders_flagged: int,
       error_rows: [{order_id, name, reason}]}
```

**3-Phase pattern (critical for performance):**

- **Phase 1 — Bulk DB reads (2 queries):** Pre-fetch all referenced orders in one `IN` query; fetch bypass order types.
- **Phase 2 — Pure Python (0 DB):** Classify every row as invoiceable, flaggable, duplicate, or error — all using the in-memory maps from Phase 1.
- **Phase 3 — Bulk DB writes (4 executemany calls):** INSERT invoices, UPDATE order statuses, INSERT order records, INSERT state history.

**Never write row-by-row DB calls in business logic.** See Phase pattern below.

### `api/business/product_upload_business.py` — Product Upload (3-Phase)

```python
process_product_upload_dataframe(df, company_id, user_id, upload_batch_id=None)
    → {products_processed: int, orders_updated: int, error_rows: [...]}
```

Same 3-phase pattern: bulk-fetch orders + products → classify in memory → bulk write.

### `api/business/dealer_business.py` and `product_business.py`

Both implement the same **in-memory cache + lookup-or-create** pattern:

```python
get_or_create_dealer(dealer_name, dealer_code=None) → dealer_id: int
get_or_create_product(product_string, description) → product_id: int
```

Call `clear_dealer_cache()` / `clear_product_cache()` at the start of each upload to avoid stale data between uploads.

---

## 9. Repositories Layer

Repositories are the **only place SQL is written** (except legacy code in `models.py` that hasn't been migrated yet).

### `api/repositories/base_repository.py`

```python
class BaseRepository:
    def __init__(self):
        self._db = mysql_manager
        self._pf = partition_filter   # always use this for partitioned tables
```

### Available Repositories

| Repository | Purpose |
|---|---|
| `OrderRepository` | PotentialOrder bulk lookups, state history writes |
| `InvoiceRepository` | Invoice bulk inserts, order state transitions |
| `ProductRepository` | Product lookup, bulk order-product links |
| `UserRepository` | User lookups, token blocklist |
| `ReferenceRepository` | Warehouse, Company, Dealer, Box queries |

**Singletons** are exported from `api/repositories/__init__.py`:
```python
from ..repositories import order_repo, invoice_repo, product_repo, user_repo, reference_repo
```

### Key Bulk Methods

```python
# OrderRepository
order_repo.find_bulk_by_original_ids(order_ids: list) → dict[str, PotentialOrder]
order_repo.get_or_create_state(name, description) → OrderState
order_repo.create_state_history(potential_order_id, state_id, user_id, changed_at)

# InvoiceRepository
invoice_repo.get_bypass_order_types() → set[str]
invoice_repo.bulk_insert_invoices(invoices: list) → int
invoice_repo.bulk_transition_to_invoiced(orders, dealer_backfills, state_id, user_id, ts)

# ProductRepository
product_repo.find_bulk_by_part_numbers(part_numbers: list) → dict[str, dict]
product_repo.bulk_insert_products(products: dict, ts)
product_repo.bulk_delete_order_products(potential_order_ids: list)
product_repo.bulk_insert_order_products(rows: list) → int
```

---

## 10. Services Layer

### `api/services/base_upload_service.py` — Template Method

```python
class BaseUploadService(abc.ABC):
    @property
    @abc.abstractmethod
    def upload_type(self) -> str: ...

    @property
    @abc.abstractmethod
    def required_columns(self) -> list[str]: ...

    @abc.abstractmethod
    def process_dataframe(self, df, context: dict) -> dict: ...

    def execute(self, uploaded_file, context: dict) -> tuple[dict, int]:
        """8-step pipeline (save → validate → parse → resolve cols
        → create batch → run in transaction → update batch → cleanup)"""
```

The `execute()` method handles all the boilerplate. Subclasses only implement `process_dataframe()`.

### Concrete Services

| Service | `upload_type` | `required_columns` |
|---|---|---|
| `OrderUploadService` | `'orders'` | `['Sales Order #']` |
| `InvoiceUploadService` | `'invoices'` | `['Invoice #', 'Order #']` |
| `ProductUploadService` | `'products'` | `['Order #', 'Part #', 'Part Description', 'Reserved Qty']` |

### Factory

```python
from ..services.upload_factory import UploadProcessorFactory
service = UploadProcessorFactory.get(UploadType.ORDERS)   # → OrderUploadService()
response, status = service.execute(file, context)
```

### Transaction Handling (in `execute()`)

- `process_dataframe()` runs inside an explicit transaction (`commit=False`)
- On success (`processed_count > 0`): COMMIT + update batch record count
- On failure or exception: ROLLBACK + delete batch record
- Temp file is always cleaned up in a `finally` block

### Backward-Compatible Shim Functions

Each service file exposes a module-level function for legacy route callers:
```python
# services/order_service.py
def process_order_upload(uploaded_file, warehouse_id, company_id, user_id):
    return OrderUploadService().execute(uploaded_file, {...})
```

---

## 11. Validation Layer

Validators return `(True, None)` on success or `(False, (response_dict, status_code))` on failure. They perform **no DB writes** and **raise no exceptions**.

```python
# upload_validators.py
validate_warehouse_company_access(current_user, warehouse_id, company_id)
validate_file_extension(filename, supported=('.csv', '.xls', '.xlsx'))

# order_validators.py
validate_warehouse_exists(warehouse_id)
validate_company_exists(company_id)
```

**Usage in route handlers:**
```python
ok, err = validate_warehouse_company_access(current_user, warehouse_id, company_id)
if not ok:
    return err   # err is (response_dict, status_code) — unpack directly
```

---

## 12. Routes Package

### `api/routes/__init__.py`

```python
from ..extensions import rest_api          # canonical API singleton
from ..core.auth import (
    token_required,
    active_required,
    upload_permission_required,
)

def register_all_routes():
    """Import all route modules — @rest_api.route() decorators fire on import."""
    from . import auth_routes, order_routes, invoice_routes, product_routes
    from . import dashboard_routes, admin_routes, eway_bill_routes
```

### Route File Pattern

Every route file follows the same structure:

```python
from ..extensions import rest_api
from ..core.auth import token_required, active_required, upload_permission_required
from ..models import SomeModel
from ..db_manager import mysql_manager, partition_filter
from ..services import some_service

# RestX model definitions
some_model = rest_api.model('SomeModel', {
    'field': fields.String(description='...'),
})

@rest_api.route('/api/some-endpoint')
class SomeResource(Resource):

    @rest_api.expect(some_model)
    @rest_api.doc(description='...')
    @token_required
    @active_required
    def get(self, current_user):
        ...
```

### All Registered Routes

| Module | Routes |
|---|---|
| `auth_routes` | POST `/api/users/register`, `/login`, `/edit`, `/logout` |
| `order_routes` | POST `/api/orders/upload`, `/bulk-status-update`; GET/POST `/api/orders/<id>/details`, `/status`, `/packed`, `/dispatch`, `/move-to-invoiced`, `/complete-dispatch` |
| `invoice_routes` | POST `/api/invoices/upload`; GET `/api/invoices`, `/statistics`, `/<id>`, `/download-errors`, `/supply-sheet/download` |
| `product_routes` | POST `/api/products/upload` |
| `dashboard_routes` | GET `/api/warehouses`, `/api/companies`, `/api/orders`, `/api/orders/status`, `/api/orders/recent`, `/api/orders/bulk-export`; POST `/api/orders/bulk-import` |
| `admin_routes` | GET/DELETE `/api/admin/upload-batches`, `/<id>`, `/<id>/details` |
| `eway_bill_routes` | 11 endpoints under `/api/eway/*` |

---

## 13. Design Patterns Reference

### Template Method (Upload Pipeline)

```
BaseUploadService.execute()          ← defines the skeleton (8 steps)
    ├── OrderUploadService           ← overrides process_dataframe() only
    ├── InvoiceUploadService         ← overrides process_dataframe() only
    └── ProductUploadService         ← overrides process_dataframe() only
```

Adding a new upload type = create a subclass, override 3 abstract members.

### Strategy + Factory (Upload Dispatch)

```
UploadProcessorFactory.get(UploadType.INVOICES)
    → InvoiceUploadService instance
```

Eliminates `if upload_type == 'orders': ... elif upload_type == 'invoices':...` branches.

### State Machine (Order States)

```
OrderStateMachine
    ├── BULK_TRANSITIONS           → for CSV bulk-status-update
    ├── SINGLE_ORDER_TRANSITIONS   → for per-order status update endpoint
    ├── TERMINAL_STATES            → can't upload invoice against these
    └── PRE_PACKED_STATES          → can flag invoice_submitted on these
```

### Repository Pattern (Data Access)

```
Business layer                 Repository layer              DB
order_business.py     →    order_repo.find_bulk_...()   →  MySQL
invoice_business.py   →    invoice_repo.bulk_insert..() →  MySQL
```

Business logic never writes raw SQL.

### 3-Phase Bulk Processing

```
Phase 1 — Bulk reads  (2 queries, regardless of row count)
Phase 2 — Pure Python (0 DB calls, classify all rows in memory)
Phase 3 — Bulk writes (executemany, typically 3-4 calls)
Total DB round-trips: ~5-6, regardless of file size
```

**Never write per-row DB calls in business logic.**

### Application Factory

```python
app = create_app()            # module-level for Gunicorn
app = create_app({'DB_HOST': 'test-db'})  # in tests
```

### Decorator Stack (Auth)

```python
@token_required               # always first — injects current_user
@active_required              # always second — checks user.status
@upload_permission_required   # always third — checks role.uploads
def post(self, current_user):
    ...
```

---

## 14. Authentication & Authorization Flow

### Registration

1. POST `/api/users/register` — creates user with `status='pending'`, `role='viewer'`
2. Admin approves via Flask-Admin → `status='active'`

### Login

1. POST `/api/users/login` — validate credentials, account not blocked
2. Generate JWT (HS256, `SECRET_KEY`, exp per `APP_ENV` config)
3. Call `user.set_jwt_auth_active(True)` — saves flag to DB
4. Return `{token, user: {permissions, warehouse_company_access}}`

### Token Validation (every protected endpoint)

1. Extract `Authorization: Bearer <token>` header
2. Decode JWT with `BaseConfig.SECRET_KEY`, algorithm HS256
3. Check token not in `jwt_token_blocklist` (partition-filtered)
4. Check `user.jwt_auth_active` flag — ensures logout invalidates token
5. Check `user.status != 'blocked'`
6. Inject `current_user: Users` as 2nd positional argument

### RBAC

Permissions are DB-driven, cached on Flask `g` per request:

```python
perms = get_permissions(current_user.role)
# {
#   order_states: [...],     # which states this role can see
#   uploads: [...],          # which upload types allowed
#   all_warehouses: bool,    # bypass warehouse scoping
#   eway_bill_admin: bool,
#   eway_bill_filling: bool,
# }
```

Tables: `roles`, `role_order_states`, `role_uploads`

### Warehouse/Company Scoping

Most data access is scoped to `(warehouse_id, company_id)`. Users with `all_warehouses=True` bypass this. Others must have a record in `user_warehouse_company` table.

---

## 15. Order Lifecycle

```
Upload CSV
    ↓
OPEN          ← created by order upload
    ↓ (bulk status update)
PICKING       ← warehouse picking started
    ↓ (bulk status update)
PACKED        ← picking complete, boxes assigned
    ↓ (invoice upload)
INVOICED      ← invoice linked (terminal-ish, pre-dispatch)
    ↓ (dispatch process)
DISPATCH_READY ← ready for handoff
    ↓ (complete dispatch)
COMPLETED     ← delivered
PARTIALLY_COMPLETED ← some items delivered

Back-edge: PICKING → OPEN (single-order endpoint only, not bulk)
```

State changes always write a row to `order_state_history` (audit trail).

**Invoice upload rules:**
- Order must be in `PACKED` (or bypass order type) to receive invoice
- Terminal states (`INVOICED`, `DISPATCH_READY`, `COMPLETED`, `PARTIALLY_COMPLETED`) cannot receive invoices
- Pre-packed states (`OPEN`, `PICKING`) can receive `invoice_submitted` flag for later auto-invoicing

---

## 16. Key Function Signatures

```python
# App
create_app(config_override: dict = None) -> Flask

# DB
partition_filter(table: str, alias: str = None) -> tuple[str, tuple]
mysql_manager.execute_query(sql: str, params: tuple, fetch: bool = True) -> list[dict] | int
mysql_manager.get_cursor(commit: bool = True)  # contextmanager

# Auth decorators
@token_required              # injects current_user: Users
@active_required             # requires status != 'pending'
@upload_permission_required(upload_type: str)

# Permissions
get_permissions(role_name: str) -> dict
can_upload(role_name: str, upload_type: str) -> bool
has_all_warehouse_access(role_name: str) -> bool

# State Machine
OrderStateMachine.can_bulk_transition(current: OrderStatus, target: OrderStatus) -> bool
OrderStateMachine.can_single_transition(current: OrderStatus, target: OrderStatus) -> bool
OrderStateMachine.is_terminal(status: OrderStatus) -> bool
OrderStateMachine.required_source_for_bulk(target: OrderStatus) -> OrderStatus | None

# Business
process_order_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id) -> dict
process_invoice_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id) -> dict
process_product_upload_dataframe(df, company_id, user_id, upload_batch_id) -> dict
get_or_create_dealer(dealer_name, dealer_code=None) -> int
get_or_create_product(product_string, description) -> int

# Services
BaseUploadService.execute(uploaded_file, context: dict) -> tuple[dict, int]
UploadProcessorFactory.get(upload_type) -> BaseUploadService

# Validators
validate_warehouse_company_access(current_user, warehouse_id, company_id) -> (bool, error | None)
validate_file_extension(filename, supported) -> (bool, error | None)
validate_warehouse_exists(warehouse_id) -> (bool, error | None)
validate_company_exists(company_id) -> (bool, error | None)

# Logging
get_logger(name: str) -> logging.Logger
configure_logging(app: Flask) -> None
```
