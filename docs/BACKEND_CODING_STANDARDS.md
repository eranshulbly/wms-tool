# WMS Backend — Coding Standards & Prompts

How to write new code and modify existing code in this codebase. Read `BACKEND_ARCHITECTURE.md` first for context. This document answers: **how do I actually write it?**

---

## Table of Contents

1. [Golden Rules (Never Break These)](#1-golden-rules-never-break-these)
2. [Adding a New API Endpoint](#2-adding-a-new-api-endpoint)
3. [Adding a New Upload Type](#3-adding-a-new-upload-type)
4. [Writing Business Logic](#4-writing-business-logic)
5. [Writing Repository Methods](#5-writing-repository-methods)
6. [Writing Route Handlers](#6-writing-route-handlers)
7. [Using Auth Decorators](#7-using-auth-decorators)
8. [Working with Order States](#8-working-with-order-states)
9. [Writing DB Queries](#9-writing-db-queries)
10. [Adding a New Constant or Enum Value](#10-adding-a-new-constant-or-enum-value)
11. [Error Handling Patterns](#11-error-handling-patterns)
12. [Logging Patterns](#12-logging-patterns)
13. [Common Mistakes to Avoid](#13-common-mistakes-to-avoid)
14. [Prompts for AI-Assisted Development](#14-prompts-for-ai-assisted-development)

---

## 1. Golden Rules (Never Break These)

These rules exist because of past incidents or deliberate architectural decisions. Violating any of them will introduce bugs or regressions.

### Never write per-row DB calls in business logic
**Why:** The upload pipeline processes hundreds of rows. Per-row queries = N+1 problem = timeout in production.  
**Instead:** Use the 3-phase pattern (bulk read → classify in Python → bulk write). See [Section 4](#4-writing-business-logic).

### Never define state transition rules outside `OrderStateMachine`
**Why:** Three separate dicts existed before the refactor, two of which disagreed. Any duplication will diverge.  
**Instead:** Always call `OrderStateMachine.can_bulk_transition()` / `can_single_transition()`. If you need a new transition, add it to `business/order_state_machine.py` only.

### Never write raw SQL outside repositories
**Why:** SQL is scattered across models, business logic, and routes today (legacy). New code must not add to this.  
**Instead:** Add methods to the appropriate repository in `repositories/`. Business logic calls the repository.

### Never use `print()` for logging
**Why:** `print()` doesn't appear in production log aggregators (Datadog, CloudWatch). It's gone.  
**Instead:** `logger = get_logger(__name__)` at module level, then `logger.info(...)`.

### Never use magic strings for statuses, roles, or upload types
**Why:** Typos are silent bugs. `'Dispatc Ready'` passes all linting.  
**Instead:** Use `OrderStatus.DISPATCH_READY`, `UserRole.VIEWER`, `UploadType.ORDERS`.

### Always include `partition_filter` in queries on partitioned tables
**Why:** Without it, MySQL scans all partitions — full table scan on large datasets.  
**Instead:** See [Section 9](#9-writing-db-queries) for the exact pattern.

### Never add `from .routes import ...` in any file — the flat file is deleted
**Why:** `api/routes.py` no longer exists. Python now uses the `api/routes/` package.  
**Instead:** Use `from ..extensions import rest_api` and `from ..core.auth import token_required`.

---

## 2. Adding a New API Endpoint

### Step-by-step

**Step 1 — Decide which routes file it belongs to:**

| Endpoint prefix | File |
|---|---|
| `/api/users/*` | `routes/auth_routes.py` |
| `/api/orders/*` | `routes/order_routes.py` |
| `/api/invoices/*` | `routes/invoice_routes.py` |
| `/api/products/*` | `routes/product_routes.py` |
| `/api/admin/*` | `routes/admin_routes.py` |
| `/api/eway/*` | `routes/eway_bill_routes.py` |
| `/api/warehouses`, `/api/companies`, `/api/orders` (listing) | `routes/dashboard_routes.py` |
| New domain entirely | Create `routes/new_domain_routes.py` |

**Step 2 — Define your RestX models at the top of the file:**

```python
# At the top of the relevant routes file, with other model definitions
new_request_model = rest_api.model('NewRequestModel', {
    'field_one': fields.String(required=True, description='...'),
    'field_two': fields.Integer(description='...'),
})

new_response_model = rest_api.model('NewResponseModel', {
    'success': fields.Boolean(),
    'data':    fields.String(),
    'msg':     fields.String(),
})
```

**Model naming rule:** Names must be globally unique across all route files. If the name might clash (e.g., `ErrorResponse` already exists in `order_routes.py`), prefix with the domain: `InvoiceErrorResponse`, `DashErrorResponse`.

**Step 3 — Write the Resource class:**

```python
@rest_api.route('/api/domain/action')
class NewActionResource(Resource):

    @rest_api.expect(new_request_model)
    @rest_api.marshal_with(new_response_model)
    @rest_api.doc(description='What this endpoint does')
    @token_required
    @active_required
    def post(self, current_user):
        # 1. Parse and validate inputs
        req = request.get_json()
        warehouse_id = req.get('warehouse_id')

        ok, err = validate_warehouse_exists(warehouse_id)
        if not ok:
            return err

        # 2. Call service or repository
        result = some_service.do_thing(warehouse_id, current_user.id)

        # 3. Return response
        return {'success': True, 'data': result}, 200
```

**Step 4 — If you created a new routes file**, register it in `routes/__init__.py`:

```python
def register_all_routes():
    from . import auth_routes, order_routes, invoice_routes, product_routes
    from . import dashboard_routes, admin_routes, eway_bill_routes
    from . import new_domain_routes   # ← add here
```

### Endpoint method signature

`current_user` is always the second positional argument (after `self`) when `@token_required` is used:

```python
def get(self, current_user):          # GET with token
def post(self, current_user):         # POST with token
def delete(self, current_user, id):   # DELETE with path param + token
```

Path parameters come **after** `current_user`:
```python
@rest_api.route('/api/orders/<string:order_id>/status')
class OrderStatusUpdate(Resource):
    @token_required
    def post(self, current_user, order_id):   # order_id comes from URL
        ...
```

---

## 3. Adding a New Upload Type

The factory + template method pattern makes this straightforward.

**Step 1 — Add the type to `constants/upload_types.py`:**

```python
class UploadType(str, Enum):
    ORDERS      = 'orders'
    INVOICES    = 'invoices'
    PRODUCTS    = 'products'
    MANIFESTS   = 'manifests'    # ← new type
```

**Step 2 — Create `business/manifest_business.py`:**

```python
from ..core.logging import get_logger
from ..repositories import order_repo   # or whichever repos you need

logger = get_logger(__name__)

def process_manifest_dataframe(df, warehouse_id, user_id, upload_batch_id=None) -> dict:
    # Phase 1: bulk DB reads
    ...

    # Phase 2: pure Python classification
    processed = []
    error_rows = []
    for _, row in df.iterrows():
        try:
            ...
            processed.append(...)
        except Exception as e:
            error_rows.append({'order_id': row.get('Order #', ''), 'name': '', 'reason': str(e)})

    # Phase 3: bulk DB writes
    if processed:
        ...

    logger.info("Manifest processing complete",
                extra={'processed': len(processed), 'errors': len(error_rows)})
    return {
        'manifests_processed': len(processed),
        'error_rows': error_rows,
    }
```

**Step 3 — Create `services/manifest_service.py`:**

```python
from .base_upload_service import BaseUploadService
from ..business.manifest_business import process_manifest_dataframe

class ManifestUploadService(BaseUploadService):
    upload_type = 'manifests'
    required_columns = ['Route #', 'Customer Code', 'Date']

    def process_dataframe(self, df, context: dict) -> dict:
        result = process_manifest_dataframe(
            df,
            warehouse_id=context['warehouse_id'],
            user_id=context['user_id'],
            upload_batch_id=context.get('upload_batch_id'),
        )
        return {
            'processed_count': result['manifests_processed'],
            'error_rows': result['error_rows'],
        }

# Backward-compatible shim
def process_manifest_upload(uploaded_file, warehouse_id, user_id):
    return ManifestUploadService().execute(uploaded_file, {
        'warehouse_id': warehouse_id,
        'user_id': user_id,
    })
```

**Step 4 — Register in `services/upload_factory.py`:**

```python
from .manifest_service import ManifestUploadService

class UploadProcessorFactory:
    _REGISTRY = {
        UploadType.ORDERS:    OrderUploadService,
        UploadType.INVOICES:  InvoiceUploadService,
        UploadType.PRODUCTS:  ProductUploadService,
        UploadType.MANIFESTS: ManifestUploadService,   # ← add here
    }
```

**Step 5 — Add the route in `routes/` (see Section 2).**

---

## 4. Writing Business Logic

Business logic files live in `business/`. Rules:

- **No Flask imports** (`request`, `g`, `current_app`) — these are not route handlers
- **No file I/O** — file handling belongs in the service layer
- **No per-row DB calls** — use the 3-phase pattern

### The 3-Phase Pattern (Required for any bulk operation)

```python
def process_something_dataframe(df, warehouse_id, user_id, upload_batch_id=None) -> dict:
    logger = get_logger(__name__)

    # ──────────────────────────────────────────────
    # Phase 1: Bulk DB reads — collect all IDs first,
    #           then fetch everything in one IN query
    # ──────────────────────────────────────────────
    unique_order_ids = df['Order #'].dropna().unique().tolist()
    orders_map = order_repo.find_bulk_by_original_ids(unique_order_ids)
    # orders_map: {original_order_id: PotentialOrder}

    # ──────────────────────────────────────────────
    # Phase 2: Pure Python — classify each row
    #           NO DB calls in this loop
    # ──────────────────────────────────────────────
    rows_to_write = []
    error_rows = []

    for _, row in df.iterrows():
        order_id = str(row.get('Order #', '')).strip()
        order = orders_map.get(order_id)

        if order is None:
            error_rows.append({
                'order_id': order_id,
                'name': '',
                'reason': f'Order {order_id} not found',
            })
            continue

        # ... validate, transform, collect
        rows_to_write.append({...})

    # ──────────────────────────────────────────────
    # Phase 3: Bulk DB writes — executemany, one
    #           round-trip per type of operation
    # ──────────────────────────────────────────────
    if rows_to_write:
        some_repo.bulk_insert(rows_to_write)

    return {
        'processed_count': len(rows_to_write),
        'error_rows': error_rows,
    }
```

### Validating State Transitions in Business Logic

```python
from ..business.order_state_machine import OrderStateMachine
from ..constants.order_states import OrderStatus

current = OrderStatus(order.status)   # cast string to enum

if OrderStateMachine.is_terminal(current):
    error_rows.append({'order_id': order_id, 'reason': f'Order in terminal state {current}'})
    continue

if not OrderStateMachine.can_bulk_transition(current, target_status):
    error_rows.append({'order_id': order_id, 'reason': f'Cannot transition {current} → {target_status}'})
    continue
```

---

## 5. Writing Repository Methods

Repository methods live in `repositories/`. Each repository inherits from `BaseRepository`.

### Anatomy of a repository method

```python
from .base_repository import BaseRepository
from ..db_manager import mysql_manager, partition_filter
from ..constants.order_states import OrderStatus

class OrderRepository(BaseRepository):

    def find_open_orders_for_warehouse(self, warehouse_id: int) -> list[dict]:
        """Returns all OPEN orders for a warehouse within the active partition window."""
        pf_sql, pf_params = self._pf('potential_order', alias='po')

        sql = f"""
            SELECT po.potential_order_id, po.original_order_id, po.status,
                   po.created_at, d.name AS dealer_name
            FROM potential_order po
            LEFT JOIN dealers d ON po.dealer_id = d.dealer_id
            WHERE {pf_sql}
              AND po.warehouse_id = %s
              AND po.status = %s
            ORDER BY po.created_at DESC
        """
        return self._db.execute_query(sql, pf_params + (warehouse_id, OrderStatus.OPEN))

    def bulk_update_status(self, order_ids: list[int], new_status: OrderStatus, updated_at) -> None:
        """Bulk update status for a list of order IDs."""
        if not order_ids:
            return
        placeholders = ', '.join(['%s'] * len(order_ids))
        sql = f"""
            UPDATE potential_order
            SET status = %s, updated_at = %s
            WHERE potential_order_id IN ({placeholders})
        """
        self._db.execute_query(
            sql,
            (new_status, updated_at) + tuple(order_ids),
            fetch=False,
        )
```

### Bulk insert pattern

```python
def bulk_insert_records(self, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = """
        INSERT IGNORE INTO some_table
            (col_a, col_b, col_c, created_at)
        VALUES (%s, %s, %s, %s)
    """
    data = [(r['col_a'], r['col_b'], r['col_c'], r['created_at']) for r in rows]
    with mysql_manager.get_cursor(commit=True) as cursor:
        cursor.executemany(sql, data)
        return cursor.rowcount
```

### Rules

- Always `self._pf(table, alias)` for partitioned tables
- Use `INSERT IGNORE` for idempotent bulk inserts
- Use `executemany` for bulk writes — never loop and call `execute_query` per row
- `fetch=False` when you don't need results (UPDATE / DELETE / INSERT without returning IDs)
- Keep methods focused: one SQL operation per method

---

## 6. Writing Route Handlers

### Full route handler template

```python
@rest_api.route('/api/domain/<string:item_id>/action')
class ItemAction(Resource):

    @rest_api.expect(action_request_model)
    @rest_api.doc(description='Perform action on item')
    @token_required
    @active_required
    def post(self, current_user, item_id):
        # 1. Parse inputs
        req = request.get_json()
        if not req:
            return {'success': False, 'msg': 'Request body required'}, 400

        warehouse_id = req.get('warehouse_id')
        if not warehouse_id:
            return {'success': False, 'msg': 'warehouse_id required'}, 400

        # 2. Validate inputs (use validation layer)
        ok, err = validate_warehouse_exists(warehouse_id)
        if not ok:
            return err

        ok, err = validate_warehouse_company_access(current_user, warehouse_id, req.get('company_id'))
        if not ok:
            return err

        # 3. Business/DB operation
        try:
            result = some_repo.find_by_id(item_id)
            if result is None:
                return {'success': False, 'msg': f'Item {item_id} not found'}, 404

            # ... do work
            return {'success': True, 'item': result, 'msg': 'Done'}, 200

        except WMSException as e:
            return e.to_dict(), e.http_status
        except Exception as e:
            logger.error("Unexpected error in ItemAction", exc_info=True)
            return {'success': False, 'msg': 'Internal server error'}, 500
```

### Response shape convention

All responses follow this shape:
```json
{"success": true/false, "msg": "...", ...domain_fields}
```

Error responses (4xx/5xx) are normalized by the `after_request` handler to:
```json
{"success": false, "msg": "..."}
```

### File upload endpoints

```python
upload_parser = rest_api.parser()
upload_parser.add_argument('file', location='files', type=FileStorage, required=True)
upload_parser.add_argument('warehouse_id', location='form', type=int, required=True)
upload_parser.add_argument('company_id', location='form', type=int, required=True)

@rest_api.route('/api/domain/upload')
class DomainUpload(Resource):

    @rest_api.expect(upload_parser)
    @token_required
    @active_required
    @upload_permission_required('domain')
    def post(self, current_user):
        args = upload_parser.parse_args()
        uploaded_file = args['file']
        warehouse_id = args['warehouse_id']
        company_id = args['company_id']

        ok, err = validate_warehouse_company_access(current_user, warehouse_id, company_id)
        if not ok:
            return err

        return domain_service.process_domain_upload(
            uploaded_file, warehouse_id, company_id, current_user.id
        )
```

---

## 7. Using Auth Decorators

### Decorator order is fixed

```python
@token_required                           # 1st — always
@active_required                          # 2nd — always when needed
@upload_permission_required('invoices')   # 3rd — always last
def post(self, current_user):
```

Never rearrange. `@token_required` must run first because it injects `current_user` which `@active_required` reads.

### When to use each decorator

| Decorator | Use when |
|---|---|
| `@token_required` | Any endpoint that requires a logged-in user |
| `@active_required` | Any write endpoint (upload, status update, etc.) |
| `@upload_permission_required(type)` | Upload endpoints only |

### E-way bill specific decorators

`eway_bill_routes.py` has its own local decorators:

```python
@eway_admin_required    # checks perms.eway_bill_admin
@eway_filling_required  # checks perms.eway_bill_filling
```

These are defined locally in `routes/eway_bill_routes.py` and stack on top of `@token_required`.

### Checking permissions manually inside a handler

```python
@token_required
def get(self, current_user):
    perms = get_permissions(current_user.role)

    if not perms.get('all_warehouses'):
        # filter by user's assigned warehouses
        ...

    if not can_see_order_state(current_user.role, OrderStatus.INVOICED):
        # exclude invoiced orders from response
        ...
```

---

## 8. Working with Order States

### Always use the enum, never raw strings

```python
# Wrong
order.status = 'Dispatch Ready'
if order.status == 'Completed':

# Right
order.status = OrderStatus.DISPATCH_READY
if order.status == OrderStatus.COMPLETED:
```

The `str` mixin ensures `OrderStatus.DISPATCH_READY == 'Dispatch Ready'` is `True`, so DB comparisons still work.

### Validating a state transition (bulk)

```python
target = OrderStatus.PICKING  # the requested target

source = OrderStateMachine.required_source_for_bulk(target)
# → OrderStatus.OPEN (only OPEN orders can be moved to PICKING via bulk)

orders = order_repo.find_bulk_by_original_ids(order_ids)
for order_id, order in orders.items():
    current = OrderStatus(order.status)
    if not OrderStateMachine.can_bulk_transition(current, target):
        error_rows.append({...})
        continue
    # proceed
```

### Validating a state transition (single order)

```python
current = OrderStatus(order.status)
target  = OrderStatus(requested_status)

if not OrderStateMachine.can_single_transition(current, target):
    return {
        'success': False,
        'msg': f'Cannot transition from {current} to {target}'
    }, 400
```

### Adding a new state transition

Edit **only** `business/order_state_machine.py`:

```python
SINGLE_ORDER_TRANSITIONS = {
    ...
    OrderStatus.PACKED: [OrderStatus.PICKING, OrderStatus.DISPATCH_READY],  # ← add new target
}
```

Do not touch any route handlers or business files — they call the state machine.

### Recording state history

Every status change must write to `order_state_history`:

```python
from ..repositories import order_repo
from datetime import datetime, timezone

state = order_repo.get_or_create_state(OrderStatus.PICKING, 'Order is being picked')
order_repo.create_state_history(
    potential_order_id=order.potential_order_id,
    state_id=state.state_id,
    user_id=current_user.id,
    changed_at=datetime.now(timezone.utc),
)
```

---

## 9. Writing DB Queries

### Always use parameterized queries

```python
# Wrong — SQL injection
sql = f"SELECT * FROM users WHERE email = '{email}'"

# Right
sql = "SELECT * FROM users WHERE email = %s"
rows = mysql_manager.execute_query(sql, (email,))
```

### Partition filter pattern

```python
from ..db_manager import mysql_manager, partition_filter

pf_sql, pf_params = partition_filter('potential_order', alias='po')

sql = f"""
    SELECT po.*, d.name AS dealer_name
    FROM potential_order po
    JOIN dealers d ON po.dealer_id = d.dealer_id
    WHERE {pf_sql}
      AND po.warehouse_id = %s
      AND po.company_id = %s
"""
rows = mysql_manager.execute_query(sql, pf_params + (warehouse_id, company_id))
```

**The alias parameter** must match the alias used in the SQL. If you don't alias the table, omit it:
```python
pf_sql, pf_params = partition_filter('potential_order')
# pf_sql → "created_at >= %s"
```

### Multi-table joins with multiple partitioned tables

Apply filter once per partitioned table:

```python
pf_order, p_order_params = partition_filter('potential_order', alias='po')
pf_hist, p_hist_params   = partition_filter('order_state_history', alias='osh')

sql = f"""
    SELECT po.original_order_id, osh.changed_at, osh.changed_by
    FROM potential_order po
    JOIN order_state_history osh ON osh.potential_order_id = po.potential_order_id
    WHERE {pf_order}
      AND {pf_hist}
      AND po.warehouse_id = %s
"""
rows = mysql_manager.execute_query(sql, p_order_params + p_hist_params + (warehouse_id,))
```

### Bulk IN queries

```python
if not order_ids:
    return {}

placeholders = ', '.join(['%s'] * len(order_ids))
pf_sql, pf_params = partition_filter('potential_order', alias='po')

sql = f"""
    SELECT * FROM potential_order po
    WHERE {pf_sql}
      AND po.original_order_id IN ({placeholders})
"""
rows = mysql_manager.execute_query(sql, pf_params + tuple(order_ids))
```

### Explicit transactions (multi-step writes)

```python
with mysql_manager.get_cursor(commit=False) as cursor:
    cursor.execute(sql_1, params_1)
    cursor.execute(sql_2, params_2)
    cursor.executemany(sql_3, many_rows)
    cursor.connection.commit()
# On exception: caller handles rollback
```

The `BaseUploadService` already wraps `process_dataframe()` in a transaction. You don't need to manage transactions in business logic — only in repository methods that are called outside the service layer.

---

## 10. Adding a New Constant or Enum Value

### New order status

```python
# constants/order_states.py
class OrderStatus(str, Enum):
    ...
    ON_HOLD = 'On Hold'   # ← new

    @classmethod
    def from_frontend_slug(cls, slug: str) -> 'OrderStatus':
        _map = {
            ...
            'on-hold': cls.ON_HOLD,   # ← add mapping
        }
```

Then update `OrderStateMachine` with transition rules for the new state.

### New upload type

```python
# constants/upload_types.py
class UploadType(str, Enum):
    ...
    MANIFESTS = 'manifests'   # ← new
```

Then follow [Section 3](#3-adding-a-new-upload-type) to wire it up.

### New user role

```python
# constants/upload_types.py
class UserRole(str, Enum):
    ...
    AUDITOR = 'auditor'   # ← new
```

Then add the role to the `roles` DB table and configure its permissions in `role_order_states` and `role_uploads`.

---

## 11. Error Handling Patterns

### In route handlers — use WMSException

```python
from ..core.exceptions import WMSException, OrderNotFoundException

try:
    order = order_repo.find_by_id(order_id)
    if order is None:
        raise OrderNotFoundException(order_id)
    ...
except WMSException as e:
    return e.to_dict(), e.http_status
except Exception as e:
    logger.error("Unexpected error", exc_info=True, extra={'order_id': order_id})
    return {'success': False, 'msg': 'Internal server error'}, 500
```

### In business logic — collect errors, don't raise

Business functions return `error_rows`, they don't raise for per-row failures:

```python
for _, row in df.iterrows():
    try:
        # process row
        ...
    except ValueError as e:
        error_rows.append({
            'order_id': row.get('Order #', 'unknown'),
            'name': row.get('Purchaser Name', ''),
            'reason': str(e),
        })
        continue  # never break the loop on a single row failure
```

Only raise for fatal errors (DB connection lost, file can't be parsed):

```python
if df.empty:
    raise EmptyFileException()
```

### In repositories — let DB errors propagate

```python
def bulk_insert_invoices(self, invoices: list) -> int:
    # Don't swallow exceptions — the service layer handles rollback
    with mysql_manager.get_cursor(commit=True) as cursor:
        cursor.executemany(sql, data)
        return cursor.rowcount
```

### Validation helpers

Validators return `(bool, error_tuple | None)`, they never raise:

```python
ok, err = validate_file_extension(filename)
if not ok:
    return err   # returns (response_dict, status_code) directly to Flask
```

---

## 12. Logging Patterns

### Module-level logger setup

```python
# At the top of every module that logs, after imports
from ..core.logging import get_logger

logger = get_logger(__name__)
```

### What to log and at what level

| Level | When |
|---|---|
| `logger.debug(...)` | Detailed internal state, only useful during debugging |
| `logger.info(...)` | Normal operation events (upload started, processed N rows) |
| `logger.warning(...)` | Recoverable issues (skipped row, fallback used) |
| `logger.error(...)` | Failed operations that need attention (DB write failed) |
| `logger.critical(...)` | App can't start or continue (DB connection refused) |

### Adding structured context

```python
logger.info("Order upload complete",
            extra={
                'warehouse_id': warehouse_id,
                'company_id': company_id,
                'processed': orders_processed,
                'errors': len(error_rows),
                'batch_id': upload_batch_id,
            })

logger.error("Invoice processing failed",
             exc_info=True,   # includes stack trace
             extra={'row_index': i, 'order_id': order_id})
```

### Logging in the route handler

```python
logger.info("POST /api/orders/upload called",
            extra={'user_id': current_user.id, 'warehouse_id': warehouse_id})
```

---

## 13. Common Mistakes to Avoid

### Importing from deleted files

```python
# Wrong — routes.py is deleted
from .routes import rest_api, token_required

# Right
from ..extensions import rest_api
from ..core.auth import token_required, active_required
```

### Duplicate RestX model names

```python
# Wrong — 'StateHistory' is already registered in order_routes.py
state_history_model = rest_api.model('StateHistory', {...})

# Right — prefix with domain
dash_state_history_model = rest_api.model('DashStateHistory', {...})
```

### Calling initialize_database() more than once

`create_app()` calls it. Do not call it again in tests or route handlers.

### Missing partition filter on bulk queries

```python
# Wrong — full table scan
sql = "SELECT * FROM potential_order WHERE warehouse_id = %s"

# Right
pf_sql, pf_params = partition_filter('potential_order')
sql = f"SELECT * FROM potential_order WHERE {pf_sql} AND warehouse_id = %s"
rows = mysql_manager.execute_query(sql, pf_params + (warehouse_id,))
```

### Using model methods instead of repositories for new code

```python
# Wrong — adds more SQL to models.py
orders = PotentialOrder.find_by_filters(...)

# Right — use the repository
orders = order_repo.find_bulk_by_original_ids(ids)
```

### Per-row DB writes in business logic

```python
# Wrong — N+1
for _, row in df.iterrows():
    order = PotentialOrder.get_by_id(row['order_id'])   # DB call per row!
    order.status = target_status
    order.save()                                          # DB call per row!

# Right — bulk pre-fetch, then bulk write
orders_map = order_repo.find_bulk_by_original_ids(all_ids)  # 1 query
# ... classify in memory ...
order_repo.bulk_update_status(order_ids, target_status, ts) # 1 query
```

### Not clearing caches between uploads

```python
# Wrong — dealer cache from previous upload bleeds into next
def process_order_dataframe(df, ...):
    for _, row in df.iterrows():
        dealer_id = get_or_create_dealer(row['dealer'])

# Right
def process_order_dataframe(df, ...):
    clear_dealer_cache()   # ← always clear at start of upload
    for _, row in df.iterrows():
        dealer_id = get_or_create_dealer(row['dealer'])
```

---

## 14. Prompts for AI-Assisted Development

Use these prompts when asking an AI assistant (like Claude) to write or modify code in this codebase. The prompts encode the constraints above so the AI produces compliant code.

---

### Prompt: Add a new API endpoint

```
Add a new [GET/POST/DELETE] endpoint at [/api/path] to [description of what it does].

Context:
- Backend is Flask + Flask-RESTX. Routes live in api-server-flask/api/routes/.
- The endpoint belongs in [auth_routes.py / order_routes.py / dashboard_routes.py / etc.].
- All imports must use relative paths (e.g., `from ..extensions import rest_api`).
- Use `@token_required` (and `@active_required` if it's a write endpoint).
- `current_user: Users` is injected as 2nd positional arg by `@token_required`.
- Define a RestX model with a globally unique name (prefix with domain if ambiguous).
- Return shape: `{"success": true/false, "msg": "...", ...fields}`.
- Use `validate_warehouse_exists()` / `validate_warehouse_company_access()` from api/validation/.
- Use the repository (api/repositories/) for DB access, not models.py directly.
- Use `get_logger(__name__)` at module level for logging, never print().
- Use OrderStatus enum from constants/order_states.py, not string literals.

The endpoint should [specific business logic description].
```

---

### Prompt: Add a new upload type

```
Add a new upload type called [name] that processes [description of the file format].

Context:
- Backend upload pipeline uses Template Method pattern (BaseUploadService).
- Steps:
  1. Add [NAME] = '[value]' to UploadType enum in constants/upload_types.py.
  2. Create business/[name]_business.py with process_[name]_dataframe() using the 3-phase pattern:
     Phase 1: bulk DB reads (use repositories, collect all IDs first)
     Phase 2: pure Python classification (zero DB calls)
     Phase 3: bulk DB writes (executemany, not per-row execute)
  3. Create services/[name]_service.py extending BaseUploadService:
     - Set upload_type = '[value]'
     - Set required_columns = [...]
     - Implement process_dataframe() calling the business function
     - Add backward-compat shim function at module level
  4. Register in services/upload_factory.py _REGISTRY dict.
  5. Add route in routes/[domain]_routes.py following the upload endpoint pattern.
- Required CSV columns are: [list them].
- The file is in api-server-flask/api/.
```

---

### Prompt: Add a new order state transition

```
Add a new valid state transition: [SOURCE_STATE] → [TARGET_STATE].

Context:
- All state transition rules live exclusively in business/order_state_machine.py.
- Never define transitions anywhere else.
- If this is a bulk transition (CSV bulk-status-update), add to BULK_TRANSITIONS dict.
- If this is a single-order endpoint transition, add TARGET_STATE to the list for SOURCE_STATE in SINGLE_ORDER_TRANSITIONS.
- If TARGET_STATE is terminal (no further transitions allowed), add it to TERMINAL_STATES frozenset.
- Use OrderStatus enum values, never string literals.
- After updating the state machine, verify no route handler hardcodes the old list of valid targets.
- The state machine file is at api-server-flask/api/business/order_state_machine.py.
```

---

### Prompt: Add a repository method

```
Add a method to [OrderRepository / InvoiceRepository / ProductRepository] that [description].

Context:
- Repository is at api-server-flask/api/repositories/[name]_repository.py.
- Extend the existing class, inherit from BaseRepository.
- Use self._db (mysql_manager) for queries and self._pf (partition_filter) for partitioned tables.
- Partitioned tables: potential_order, potential_order_product, invoice, order_state_history, order, order_product, order_box, box_product, upload_batches, jwt_token_blocklist.
- Non-partitioned: warehouses, companies, dealers, products, boxes, order_states, roles, users.
- Always include partition filter for partitioned tables: `pf_sql, pf_params = self._pf('table_name', alias='alias')`
- For bulk reads: use IN queries, never loop + execute_query per ID.
- For bulk writes: use cursor.executemany(), never loop + execute_query per row.
- Use INSERT IGNORE for idempotent bulk inserts.
- Use fetch=False for UPDATE/DELETE/INSERT when you don't need results.
- Use parameterized queries (%s), never f-string SQL with user data.
- The method should return: [describe return type].
```

---

### Prompt: Write a business logic function (3-phase)

```
Write a business function process_[name]_dataframe() that processes a pandas DataFrame for [description].

Context:
- File: api-server-flask/api/business/[name]_business.py
- Must follow the 3-phase bulk pattern:
  Phase 1: Bulk DB reads. Collect all unique IDs from the DataFrame first (df['col'].unique().tolist()), then fetch in one IN query via repositories.
  Phase 2: Pure Python. Loop over df.iterrows(). Classify rows using in-memory maps from Phase 1. Zero DB calls in this loop. Append to lists (e.g., rows_to_write, error_rows).
  Phase 3: Bulk DB writes. If lists are non-empty, call repository bulk methods (executemany).
- Error row format: {'order_id': str, 'name': str, 'reason': str}
- Use get_logger(__name__) for logging (never print).
- Use OrderStatus enum for status comparisons.
- Use OrderStateMachine for state validation.
- Import repositories from ..repositories: order_repo, invoice_repo, etc.
- Return dict: {'[count_key]': int, 'error_rows': list}
- The function signature: def process_[name]_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id=None) -> dict
```

---

### Prompt: Modify an existing endpoint

```
Modify the [ClassName] endpoint in api-server-flask/api/routes/[file].py to [description of change].

Context:
- Read the file first before making changes.
- Do not change the auth decorator stack order: @token_required, @active_required, @upload_permission_required (if applicable).
- Do not change the RestX model name — other code may reference it.
- current_user is injected as 2nd positional arg, path params come after.
- If you add a DB query, use the repository layer, not direct mysql_manager calls unless a repository method doesn't exist yet.
- If the change involves state transitions, use OrderStateMachine, not hardcoded if/elif.
- If the change adds logging, use logger = get_logger(__name__) at module level.
- Keep the response shape consistent: {"success": bool, "msg": str, ...domain_fields}.
- The specific change needed: [describe exactly what should change].
```

---

### Prompt: Fix a bug

```
Fix the following bug in the WMS Flask backend: [describe the bug and observed behavior].

Context:
- Backend is at api-server-flask/api/.
- Architecture: routes/ → services/ → business/ → repositories/ → db_manager → MySQL.
- State machine: business/order_state_machine.py (single source of truth for transitions).
- Auth decorators: core/auth.py (token_required, active_required, upload_permission_required).
- All DB queries for partitioned tables must include partition_filter().
- Do not introduce per-row DB calls in business logic.
- Do not use magic strings — use OrderStatus, UserRole, UploadType enums.
- Do not add print() — use get_logger(__name__).
- Relevant files likely involved: [list files if known].
- The bug occurs when: [reproduce steps].
```
