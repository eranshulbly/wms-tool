# WMS Tool — Top 50 Bugs Report

> Generated: 2026-04-12  
> Scope: Full codebase review — backend (Flask/Python) + frontend (React/JS)  
> No code was changed during this analysis.

---

## Severity Legend
- **CRITICAL** — Security hole or data-destroying logic error; must fix immediately
- **HIGH** — Data integrity failure or functional breakage in core flows
- **MEDIUM** — Incorrect behavior visible to users, misleading data, or silent failures
- **LOW** — Code smell, dead code, minor UX issue, or future-proofing concern

---

## CRITICAL — Security

---

### Bug 1 — `OrderPackedUpdate` endpoint has NO authentication
**File:** [api/routes.py:958](../api-server-flask/api/routes.py#L958)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

The `/api/orders/<id>/packed` POST endpoint (`OrderPackedUpdate` class) has no `@token_required` decorator. Anyone on the internet with the API URL can update packed quantities and box assignments for any order without logging in.

```python
# routes.py:958 — no @token_required, no @active_required
def post(self, order_id):
```

---

### Bug 2 — `OrderDispatchFinal` endpoint has NO authentication
**File:** [api/routes.py:1249](../api-server-flask/api/routes.py#L1249)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

The `/api/orders/<id>/dispatch` POST endpoint has no `@token_required`. Anyone can move orders to Completed/Partially Completed status and delete product records without authentication.

---

### Bug 3 — `OrderDetailWithProducts` endpoint has NO authentication
**File:** [api/routes.py:580](../api-server-flask/api/routes.py#L580)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

The `/api/orders/<id>/details` GET endpoint has no `@token_required`. Full order details including dealer name, products, box assignments, and state history are publicly accessible.

---

### Bug 4 — `InvoiceList` endpoint has NO authentication
**File:** [api/routes.py:1641](../api-server-flask/api/routes.py#L1641)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

`/api/invoices` GET has no `@token_required`. The full invoice list (financial data) is public.

---

### Bug 5 — `InvoiceStatistics` endpoint has NO authentication
**File:** [api/routes.py:1609](../api-server-flask/api/routes.py#L1609)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

`/api/invoices/statistics` GET has no `@token_required`. Financial statistics are publicly accessible.

---

### Bug 6 — `InvoiceErrorDownload` endpoint has NO authentication
**File:** [api/routes.py:1577](../api-server-flask/api/routes.py#L1577)  
**Severity:** CRITICAL  
**Category:** Security — Missing Auth

`/api/invoices/download-errors` POST has no `@token_required`. Though this endpoint only accepts CSV content in the request body rather than reading from DB, it still returns a file download with no auth.

---

### Bug 7 — Two incompatible JWT secrets; tokens from one system break the other
**File:** [api/config.py:19-25](../api-server-flask/api/config.py#L19), [api/routes.py:237](../api-server-flask/api/routes.py#L237), [api/auth_routes.py:69](../api-server-flask/api/auth_routes.py#L69)  
**Severity:** CRITICAL  
**Category:** Security — Auth Architecture

`config.py` defines **two separate JWT secrets**: `SECRET_KEY` (used by `routes.py`) and `JWT_SECRET_KEY` (used by `auth_routes.py`). If both are unset (env vars not configured), each generates a separate random secret on startup. A token minted by `auth_routes.py` login cannot be verified by `routes.py`'s `token_required` decorator and vice versa — causing random 401 errors depending on which endpoint a user hits.

```python
# routes.py:237
data = jwt.decode(token, BaseConfig.SECRET_KEY, algorithms=["HS256"])

# auth_routes.py:69
data = jwt.decode(token, BaseConfig.JWT_SECRET_KEY, algorithms=["HS256"])
```

---

### Bug 8 — JWT secret keys regenerate randomly on every restart if env vars not set
**File:** [api/config.py:19-25](../api-server-flask/api/config.py#L19)  
**Severity:** CRITICAL  
**Category:** Security — Token Invalidation

```python
SECRET_KEY = os.getenv('SECRET_KEY', None)
if not SECRET_KEY:
    SECRET_KEY = ''.join(random.choice(string.ascii_lowercase) for i in range(32))
```

Every time the Flask app restarts without `SECRET_KEY` and `JWT_SECRET_KEY` in the environment, all existing JWT tokens become permanently invalid, logging all users out. In production, this means any deployment/restart causes a forced logout for every user.

---

### Bug 9 — Blocked users can still obtain new JWT tokens via login
**File:** [api/routes.py:339-382](../api-server-flask/api/routes.py#L339)  
**Severity:** CRITICAL  
**Category:** Security — Access Control

The login endpoint checks `check_password()` but does NOT check `user_exists.status`. A blocked user (`status='blocked'`) can successfully log in and get a valid JWT token. The `@token_required` decorator checks `status == 'blocked'` and returns 403, but the token has already been issued and stored. This allows blocked users to make any unauthenticated API calls (see Bugs 1–6).

---

## HIGH — Logic & Data Integrity

---

### Bug 10 — `db_target` mutated inside bulk-status-update loop corrupts all subsequent rows
**File:** [api/business/order_business.py:383](../api-server-flask/api/business/order_business.py#L383)  
**Severity:** HIGH  
**Category:** Logic Error — Loop Mutation

In `process_bulk_status_update()`, `db_target` is a function-scoped variable set before the loop. When an order triggers the auto-transition to Invoiced (because `invoice_submitted=True`), `db_target` is reassigned inside the loop:

```python
# order_business.py:383 (inside the for loop)
db_target = 'Invoiced'
```

For all **subsequent rows** in the same Excel file, `db_target` is now `'Invoiced'` instead of `'Packed'`. This means:
- The `if db_target == 'Packed':` check on line 348 never fires again — box counts are ignored for remaining orders
- The `print` on line 397 reports wrong status for all subsequent orders
- The behavior is non-deterministic depending on order of rows in the file

---

### Bug 11 — Fake transaction in `process_order_upload`: individual saves use separate pool connections
**File:** [api/services/order_service.py:49-65](../api-server-flask/api/services/order_service.py#L49)  
**Severity:** HIGH  
**Category:** Data Integrity — Broken Transaction

```python
with mysql_manager.get_cursor(commit=False) as cursor:
    result = process_order_dataframe(df, warehouse_id, company_id, user_id, upload_batch_id)
    if result['orders_processed'] > 0:
        cursor.connection.commit()  # Only commits what THIS cursor did (nothing!)
    else:
        cursor.connection.rollback()
```

Inside `process_order_dataframe`, each `potential_order.save()` calls `mysql_manager.execute_query()` which acquires its **own separate connection** from the pool and auto-commits. The outer cursor's `commit=False` context has **no effect** on these child operations. If the loop fails halfway through 100 orders, the first 50 are permanently committed with no way to roll back.

---

### Bug 12 — `range(potential_order.box_count)` crashes when `box_count` is None
**File:** [api/business/invoice_business.py:207](../api-server-flask/api/business/invoice_business.py#L207)  
**Severity:** HIGH  
**Category:** Crash — TypeError

In `update_order_to_invoiced()`:

```python
for i in range(potential_order.box_count):  # TypeError if box_count is None
    OrderBox(order_id=final_order.order_id, name=f'Box-{i + 1}', ...).save()
```

For **bypass order types** (e.g. ZGOI) that are in Open or Picking state when the invoice arrives, `box_count` is never set (it's only set when the order is moved to Packed). Uploading an invoice for such an order crashes the entire invoice upload request with `TypeError: 'NoneType' object cannot be interpreted as integer`.

---

### Bug 13 — `order_date.isoformat()` called without null check causes AttributeError
**File:** [api/routes.py:679](../api-server-flask/api/routes.py#L679)  
**Severity:** HIGH  
**Category:** Crash — AttributeError

```python
'order_date': order_data['order_date'].isoformat(),  # Crashes if None
```

If `order_date` is NULL in the database (possible for orders uploaded without a submit date), this throws `AttributeError: 'NoneType' object has no attribute 'isoformat'`, returning a 400 error for the order details endpoint. Contrast with how `order_date` is handled in `dashboard_routes.py:297` which does `order_date.isoformat() if order_date else None`.

---

### Bug 14 — `CompleteDispatch` uses hardcoded `changed_by=1` in state history
**File:** [api/routes.py:1499](../api-server-flask/api/routes.py#L1499)  
**Severity:** HIGH  
**Category:** Data Integrity — Audit Trail Corruption

```python
completion_history = OrderStateHistory(
    potential_order_id=numeric_id,
    state_id=completed_state.state_id,
    changed_by=1,  # BUG: should be current_user.id
    changed_at=current_time
)
```

The `CompleteDispatch` endpoint has `current_user` available (via `@token_required`) but hardcodes `changed_by=1`. All "Completed" state history entries attribute the action to user ID 1 regardless of who actually dispatched the order. Audit trail is permanently wrong.

---

### Bug 15 — `OrderDispatchFinal` uses hardcoded `changed_by=1` (unauthenticated endpoint)
**File:** [api/routes.py:1325](../api-server-flask/api/routes.py#L1325)  
**Severity:** HIGH  
**Category:** Security + Data Integrity

Same as Bug 14 but in `OrderDispatchFinal` which has no auth at all (Bug 2), so `current_user` isn't even available. The state history always says user ID 1 made the change.

---

### Bug 16 — After `CompleteDispatch`, `PotentialOrder` stays in 'Invoiced' state instead of 'Completed'
**File:** [api/routes.py:1504-1508](../api-server-flask/api/routes.py#L1504)  
**Severity:** HIGH  
**Category:** State Machine Logic Error

In `MoveToInvoiced` (line 1397), `potential_order.status` is set to `'Invoiced'`. In `CompleteDispatch`:

```python
# routes.py:1504-1508
if potential_order.status == 'Dispatch Ready':   # This is FALSE — it's 'Invoiced'
    potential_order.status = 'Completed'
    potential_order.updated_at = current_time
    potential_order.save()
```

The condition checks for `'Dispatch Ready'` but `potential_order.status` is actually `'Invoiced'` (set during `MoveToInvoiced`). The condition is always False, so `PotentialOrder` is **never moved to Completed**. The final `Order` record gets `status='Completed'` correctly, but `PotentialOrder` remains stuck at `'Invoiced'` forever. The dashboard still counts it as "Invoiced" after dispatch.

---

### Bug 17 — Partition window silently excludes all orders older than 4 months
**File:** [api/db_manager.py:47](../api-server-flask/api/db_manager.py#L47)  
**Severity:** HIGH  
**Category:** Data Visibility — Silent Data Loss

```python
PARTITION_WINDOW_MONTHS = 4
```

Every query using `partition_filter()` adds `WHERE created_at >= <4 months ago>`. Any order created more than 4 months ago is **completely invisible** to all API endpoints — it won't appear in order lists, status counts, or detail views. There is no warning to the user. This includes orders stuck in Open/Picking status for over 4 months.

---

### Bug 18 — `_delete_order_batch` has no database transaction — partial deletion leaves orphans
**File:** [api/admin_routes.py:402-458](../api-server-flask/api/admin_routes.py#L402)  
**Severity:** HIGH  
**Category:** Data Integrity — Missing Transaction

The delete helper executes three sequential DELETE statements (history → products → orders) with no wrapping transaction. If the second or third DELETE fails (e.g., DB timeout), some records are deleted and others are not, leaving the database in an inconsistent state with orphaned rows.

---

### Bug 19 — `MoveToInvoiced` creates Order with status 'Dispatch Ready' but this endpoint is labeled as "Invoiced"
**File:** [api/routes.py:1385-1397](../api-server-flask/api/routes.py#L1385)  
**Severity:** HIGH  
**Category:** State Machine Logic Error

```python
final_order = Order(
    ...
    status='Dispatch Ready',  # Order record = Dispatch Ready
    ...
)
final_order.save()
potential_order.status = 'Invoiced'  # PotentialOrder = Invoiced
```

The Order record and PotentialOrder record have different statuses immediately after this endpoint. This inconsistency causes Bug 16 above and creates confusion in any code that reads both records.

---

## MEDIUM — Functional Issues

---

### Bug 20 — Company list endpoint ignores the `warehouse_id` query parameter
**File:** [api/dashboard_routes.py:136-142](../api-server-flask/api/dashboard_routes.py#L136)  
**Severity:** MEDIUM  
**Category:** Logic Error — Unused Parameter

```python
warehouse_id = request.args.get('warehouse_id', type=int)
companies = Company.get_all()  # warehouse_id never used — returns ALL companies
```

All companies are returned regardless of which warehouse was selected. Users may be shown companies they should not have access to. The `warehouse_id` parameter is read but immediately discarded.

---

### Bug 21 — `BulkOrderExport` silently truncates at 1000 orders with no warning
**File:** [api/dashboard_routes.py:369-374](../api-server-flask/api/dashboard_routes.py#L369)  
**Severity:** MEDIUM  
**Category:** Data Completeness — Silent Truncation

```python
potential_orders = PotentialOrder.find_by_filters(
    status=db_status, warehouse_id=warehouse_id, company_id=company_id,
    limit=1000  # Hard limit with no warning to user
)
```

If there are 1500 orders in a status, the Excel export only contains 1000. The user downloading the file has no indication that data is missing.

---

### Bug 22 — `get_permissions()` makes 3 DB queries per call; called multiple times per request
**File:** [api/permissions.py:12-36](../api-server-flask/api/permissions.py#L12)  
**Severity:** MEDIUM  
**Category:** Performance — N+1 Queries

Every call to `get_permissions()` runs 3 SQL queries. The decorators `@active_required`, `@upload_permission_required`, and any manual `can_see_order_state()` / `has_all_warehouse_access()` calls each invoke `get_permissions()` independently. A single API request can trigger 9–12 DB round-trips just for permission checks, with no caching.

---

### Bug 23 — `warehouseDashboard.components.js` uses `wh.id` but API returns `warehouse_id`
**File:** [react-ui/src/views/warehouse/components/warehouseDashboard.components.js:73](../react-ui/src/views/warehouse/components/warehouseDashboard.components.js#L73)  
**Severity:** MEDIUM  
**Category:** Frontend — Broken UI

```jsx
{warehouses.map((wh) => (
  <MenuItem key={wh.id} value={wh.id}>  {/* Should be wh.warehouse_id */}
```

The warehouse API (`/api/warehouses`) returns objects with `warehouse_id` not `id`. The WarehouseDashboard warehouse dropdown always shows `undefined` keys and selects `undefined` values, so warehouse filtering never works on the dashboard page. The OrderManagement page correctly handles this with `wh.warehouse_id !== undefined ? wh.warehouse_id : wh.id`.

---

### Bug 24 — Order table pagination shows wrong total count; breaks for >100 orders
**File:** [react-ui/src/views/warehouse/OrderManagement.js:309](../react-ui/src/views/warehouse/OrderManagement.js#L309), [react-ui/src/views/warehouse/OrderManagement.js:353](../react-ui/src/views/warehouse/OrderManagement.js#L353)  
**Severity:** MEDIUM  
**Category:** Frontend — Broken Pagination

```jsx
// OrderManagement.js:309 — client-side slice
const pagedOrders = filteredOrders.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

// OrderManagement.js:353 — passes local array length, not server total
<OrdersTable
  orders={pagedOrders}
  totalCount={filteredOrders.length}  // Should be response.total from API
```

The API returns `{ total: <server-total>, orders: <up to 100 records> }`. The component ignores `total` and uses `filteredOrders.length` (max 100). `TablePagination` shows "1–25 of 100" even if there are 5000 orders. Clicking to page 5 of 100 fetches nothing new because the client only holds 100 records.

---

### Bug 25 — `RestLogin.js` function signature is malformed — `others` is always empty
**File:** [react-ui/src/views/pages/authentication/login/RestLogin.js:79](../react-ui/src/views/pages/authentication/login/RestLogin.js#L79)  
**Severity:** MEDIUM  
**Category:** Frontend — Incorrect Syntax

```jsx
const RestLogin = (props, { ...others }) => {
```

React components only receive one argument (`props`). The second parameter `{ ...others }` destructures from `undefined`, so `others` is always `{}`. The form at line 150 spreads `{...others}` which adds nothing. If any parent was trying to pass HTML attributes via spread, they would be silently dropped.

---

### Bug 26 — Expired JWT token in `localStorage` rehydrates as logged-in on page load
**File:** [react-ui/src/store/accountReducer.js:5-13](../react-ui/src/store/accountReducer.js#L5)  
**Severity:** MEDIUM  
**Category:** Frontend — Stale Auth State

```js
const savedToken = localStorage.getItem('wms_token');
const savedUser = (() => { try { return JSON.parse(localStorage.getItem('wms_user')); } catch { return null; } })();

export const initialState = {
    isLoggedIn: !!(savedToken && savedUser),  // No expiry check!
```

On page reload, if a token exists in `localStorage` the user is immediately set as `isLoggedIn: true` and sees the full authenticated UI. If the token has expired (8-hour validity), every API call silently fails with 401 until the user tries to do something. No automatic redirect to login.

---

### Bug 27 — No auth token sent in API calls — missing axios auth header setup
**File:** [react-ui/src/services/orderManagementService.js](../react-ui/src/services/orderManagementService.js), [react-ui/src/services/dashboardService.js](../react-ui/src/services/dashboardService.js)  
**Severity:** MEDIUM  
**Category:** Frontend — Auth Headers Not Set

None of the service files set the `Authorization` header on requests. The token is in Redux state/localStorage but never attached to API calls. Protected backend endpoints that use `@token_required` would return `{"success": false, "msg": "Valid JWT token is missing"}`. The app only "works" because the most frequently hit endpoints (order details, invoice list, etc.) are unauthenticated (Bugs 1–6).

---

### Bug 28 — `token_required` in routes.py stores raw token (with "Bearer " prefix) in blocklist; auth_routes.py stores stripped token
**File:** [api/routes.py:415-417](../api-server-flask/api/routes.py#L415), [api/auth_routes.py:260-263](../api-server-flask/api/auth_routes.py#L260)  
**Severity:** MEDIUM  
**Category:** Auth — Token Blocklist Inconsistency

`routes.py` `LogoutUser.post()` stores `request.headers["authorization"]` verbatim (may include "Bearer " prefix). The `token_required` decorator in `auth_routes.py` strips the "Bearer " prefix before decoding. If a token is issued and then a client sends `"Bearer <token>"`, the blocklist check in `auth_routes.py` looks for the stripped token but the blocklist has the prefixed version — the token is never actually revoked.

---

### Bug 29 — `process_order_dataframe` prints raw row data including PII to stdout in production
**File:** [api/business/order_business.py:30-34](../api-server-flask/api/business/order_business.py#L30)  
**Severity:** MEDIUM  
**Category:** Security — PII Leakage to Logs

```python
print(f"Processing DataFrame with {len(df)} rows")
print(f"Processing row {index}: {dict(row)}")  # Prints full row including names, addresses
```

Every uploaded order row is printed verbatim to stdout/logs, including purchaser names, SAP codes, shipping addresses, and VIN numbers. This is PII that should not appear in application logs.

---

### Bug 30 — `token_required` in routes.py catches ALL exceptions and returns "Token is invalid"
**File:** [api/routes.py:257-258](../api-server-flask/api/routes.py#L257)  
**Severity:** MEDIUM  
**Category:** Error Masking — False Error Messages

```python
except Exception:
    return {"success": False, "msg": "Token is invalid"}, 401
```

If a database error occurs while checking the token blocklist (e.g., DB is down), the response is "Token is invalid" instead of a server error. This hides infrastructure failures, makes debugging impossible, and could confuse users into thinking their session expired when the DB is actually down.

---

### Bug 31 — `"Remember me"` checkbox in login form is non-functional — state never used
**File:** [react-ui/src/views/pages/authentication/login/RestLogin.js:84](../react-ui/src/views/pages/authentication/login/RestLogin.js#L84)  
**Severity:** MEDIUM  
**Category:** Frontend — Misleading UI

```jsx
const [checked, setChecked] = React.useState(true);
```

The checkbox state `checked` is toggled when clicked but is never read or used anywhere. Whether checked or unchecked, login behavior is identical. Users are misled into thinking their session will persist based on this checkbox.

---

### Bug 32 — Two separate registration endpoints with slightly different behavior
**File:** [api/routes.py:299](../api-server-flask/api/routes.py#L299), [api/auth_routes.py:101](../api-server-flask/api/auth_routes.py#L101)  
**Severity:** MEDIUM  
**Category:** Architecture — Duplicate Systems

There are two register+login flows: `/api/users/register` + `/api/users/login` (routes.py) and `/api/auth/register` + `/api/auth/login` (auth_routes.py). They use different JWT secrets, have slightly different validation logic, and the frontend (`RestLogin.js`) only uses the `routes.py` login. The `auth_routes.py` system appears unused by the frontend but still exists as attack surface.

---

### Bug 33 — `StatusActionButton` shows no error when user clears box count field
**File:** [react-ui/src/views/warehouse/components/orderManagement.components.js:197-202](../react-ui/src/views/warehouse/components/orderManagement.components.js#L197)  
**Severity:** MEDIUM  
**Category:** Frontend — Silent Failure / UX

```jsx
const handleBoxConfirm = (e) => {
  e.stopPropagation();
  const boxes = parseInt(boxCount, 10);
  if (!boxes || boxes < 1) return;  // Silently returns if field is empty
```

If the user clears the "Number of Boxes" field and clicks "Move to Packed", `parseInt('', 10)` returns `NaN`, `!NaN` is `true`, and the function silently returns. The dialog closes (it doesn't close on this path actually — wait, it doesn't close here) no wait — actually the dialog doesn't close and nothing happens. No error message is shown to the user. They just click "Move to Packed" and nothing happens.

---

### Bug 34 — `bulkStatusUpdate` in orderManagementService is missing try/catch
**File:** [react-ui/src/services/orderManagementService.js:123-134](../react-ui/src/services/orderManagementService.js#L123)  
**Severity:** MEDIUM  
**Category:** Frontend — Unhandled Promise Rejection

```js
async bulkStatusUpdate(file, targetStatus, warehouseId, companyId) {
    const formData = new FormData();
    // ... no try/catch unlike ALL other methods in this class
    const response = await axios.post(...);
    return response.data;
}
```

Every other method in `OrderManagementService` wraps its call in try/catch and returns `{ success: false, msg: error.message }` on failure. `bulkStatusUpdate` does not — a network error throws an unhandled rejection that propagates to the component.

---

### Bug 35 — `_delete_invoice_batch` doesn't check partition filter for `order` table deletion
**File:** [api/admin_routes.py:501-516](../api-server-flask/api/admin_routes.py#L501)  
**Severity:** MEDIUM  
**Category:** Data Integrity — Potential Data Loss

```python
existing_order = mysql_manager.execute_query(
    f"SELECT order_id FROM `order` WHERE potential_order_id = %s AND {pf_ord_sql}",
    (order_id, *pf_ord_params),
)
```

The partition filter uses `PARTITION_WINDOW_MONTHS = 4`. If an Order record was created more than 4 months ago (possible for old invoices), `existing_order` returns empty, and the Order record is NOT deleted during invoice batch revert. The invoice is deleted but the Order record stays, leaving data in an inconsistent state.

---

## LOW — Code Quality & Minor Issues

---

### Bug 36 — `eway_admin_required` / `eway_filling_required` skip check if `current_user` is None
**File:** [api/eway_bill_routes.py:27-45](../api-server-flask/api/eway_bill_routes.py#L27)  
**Severity:** LOW  
**Category:** Security — Permissive Guard

```python
def decorator(*args, **kwargs):
    current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
    if current_user:  # If None, skips the permission check entirely
        perms = get_permissions(current_user.role)
        if not perms.get('eway_bill_admin'):
            return {'success': False, 'msg': 'E-way Bill Admin permission required'}, 403
    return f(*args, **kwargs)
```

If `current_user` is somehow `None`, the permission check is skipped and the function is called. While `@token_required` should always provide a user, the defensive guard inverts the intended security logic (should default-deny, not default-allow).

---

### Bug 37 — Hardcoded DB default password `'root-pw'` in config
**File:** [api/config.py:37](../api-server-flask/api/config.py#L37), [api/db_manager.py:165](../api-server-flask/api/db_manager.py#L165)  
**Severity:** LOW  
**Category:** Security — Default Credentials

```python
DB_PASS = os.getenv('DB_PASS', 'root-pw')  # config.py
'password': os.getenv('DB_PASS', 'root-pw'),  # db_manager.py
```

If `DB_PASS` env var is not set, the application attempts to connect with password `root-pw`. If a developer accidentally leaves this default in a staging or production environment, the DB is trivially accessible.

---

### Bug 38 — `/api/orders/<id>/dispatch` endpoint appears to be dead code
**File:** [api/routes.py:1240](../api-server-flask/api/routes.py#L1240)  
**Severity:** LOW  
**Category:** Dead Code

The `OrderDispatchFinal` endpoint at `/api/orders/<id>/dispatch` is never called by the frontend. `orderManagementService.js` calls `/api/orders/${orderId}/complete-dispatch` (the `CompleteDispatch` endpoint). `OrderDispatchFinal` is unauthenticated (Bug 2), mutates product records, and uses hardcoded `changed_by=1` (Bug 15). It should be removed or secured.

---

### Bug 39 — `Warehouse.get_all()` and `Company.get_all()` have no pagination — will fail at scale
**File:** [api/models.py:168-171](../api-server-flask/api/models.py#L168)  
**Severity:** LOW  
**Category:** Performance — Missing Pagination

```python
@classmethod
def get_all(cls):
    results = mysql_manager.execute_query("SELECT * FROM warehouse")
    return [cls(**row) for row in results]
```

These methods return all rows with no limit. Fine for current usage, but if the DB grows (multiple warehouses/companies), these queries will return everything and load it into memory.

---

### Bug 40 — `dashboardService.getOrderDetails()` calls a non-existent endpoint format
**File:** [react-ui/src/services/dashboardService.js:84-90](../react-ui/src/services/dashboardService.js#L84)  
**Severity:** LOW  
**Category:** Frontend — Wrong API URL

```js
getOrderDetails: async (orderId) => {
    const response = await axios.get(`${config.API_SERVER}orders/${orderId}`);
```

This calls `/api/orders/<id>` (no `/details` suffix). The backend has no such endpoint — the correct endpoint is `/api/orders/<id>/details`. This service method would always return 404 if called.

---

### Bug 41 — `process_order_dataframe` makes ~2 DB queries per row; 500 orders = ~1000 queries
**File:** [api/business/order_business.py:32-99](../api-server-flask/api/business/order_business.py#L32)  
**Severity:** LOW  
**Category:** Performance — N+1 Queries

Each order upload row triggers: `get_or_create_dealer()` (1 DB query), `potential_order.save()` (1 DB query), `OrderState.find_by_name()` (1 DB query), `state_history.save()` (1 DB query). For 500 orders: ~2000 DB round-trips. Batch insert with `executemany` would reduce this by 100x.

---

### Bug 42 — Connection pool returns potentially broken connection to pool after exception
**File:** [api/db_manager.py:205-215](../api-server-flask/api/db_manager.py#L205)  
**Severity:** LOW  
**Category:** Connection Pool — Zombie Connections

```python
except Exception as e:
    if conn:
        conn.rollback()
    raise e
finally:
    if conn:
        with self.pool_lock:
            if len(self.pool) < self.pool_size:
                self.pool.append(conn)  # Returns conn even if it's broken
```

If `conn.rollback()` itself fails (e.g., connection was dropped by MySQL), the `except` re-raises, but `finally` still adds the broken connection back to the pool. The next thread to acquire this connection will get an already-dead connection.

---

### Bug 43 — `OrderDetailsDialog` active step shows Open and Picking as identical step 0
**File:** [react-ui/src/views/warehouse/components/orderManagement.components.js:384-396](../react-ui/src/views/warehouse/components/orderManagement.components.js#L384)  
**Severity:** LOW  
**Category:** Frontend — UX / Misleading Visual

The stepper steps are `['Order Details', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed']`. Both Open and Picking orders are mapped to `setActiveStep(0)`. There is no "Picking" step in the visual. A user cannot tell from the dialog whether an order is in Open vs Picking status from the stepper alone.

---

### Bug 44 — `analyze_errors` in invoice_service.py checks for wrong status name ('Invoiced' instead of relevant)
**File:** [api/services/invoice_service.py:44](../api-server-flask/api/services/invoice_service.py#L44)  
**Severity:** LOW  
**Category:** Logic Error — Wrong Status Check

```python
elif 'status' in error_lower and ('invoiced' in error_lower or 'dispatch ready' in error_lower):
    error_types['wrong_status'] += 1
```

The error summary message says "X orders were not in 'Invoiced' status" but this refers to errors matching 'invoiced' in the error string. The actual error scenario for invoice upload is "order is ALREADY invoiced" (a duplicate), not "order is not in Invoiced status." The error category label and count is misleading in the upload result UI.

---

### Bug 45 — `auth_routes.py` `Logout.post()` re-reads the token from header after `@token_required` already parsed it
**File:** [api/auth_routes.py:259-263](../api-server-flask/api/auth_routes.py#L259)  
**Severity:** LOW  
**Category:** Code Quality — Duplication / Potential Mismatch

```python
@token_required
def post(self, current_user):
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
    else:
        token = auth_header
```

The `@token_required` decorator already validated and decoded the token. The logout endpoint re-reads and re-parses the same header. If the format changes or the decorator modifies behavior, the logout could store a different string in the blocklist than what was validated.

---

### Bug 46 — `invoice_business.py` `_TERMINAL_STATES` includes 'Dispatch Ready' and 'Completed' but not 'Partially Completed'
**File:** [api/business/invoice_business.py:33](../api-server-flask/api/business/invoice_business.py#L33)  
**Severity:** LOW  
**Category:** Logic Error — Incomplete State Check

```python
_TERMINAL_STATES = {'Invoiced', 'Dispatch Ready', 'Completed'}
```

`'Partially Completed'` is not in `_TERMINAL_STATES`. An order in 'Partially Completed' status could have an invoice uploaded against it again, potentially creating duplicate invoice records or causing unexpected state transitions.

---

### Bug 47 — `routes.py` `EditUser.post()` allows updating email/username without checking for duplicates
**File:** [api/routes.py:384-405](../api-server-flask/api/routes.py#L384)  
**Severity:** LOW  
**Category:** Data Integrity — No Uniqueness Check

```python
if _new_username:
    current_user.update_username(_new_username)
if _new_email:
    current_user.update_email(_new_email)
current_user.save()
```

No check whether the new email/username is already taken. A user can change their email to match another user's email, potentially causing `get_by_email()` to return the wrong user (MySQL will return the first match). This can break JWT auth lookups since tokens contain the email.

---

### Bug 48 — `invoice_business.py:302` `safe_date()` calls `pd.isna(value)` before the `isinstance(value, str)` check, but `datetime` objects raise `TypeError` in pandas
**File:** [api/business/invoice_business.py:317-319](../api-server-flask/api/business/invoice_business.py#L317)  
**Severity:** LOW  
**Category:** Defensive Coding — Potential Crash

```python
def safe_date(value):
    ...
    try:
        if pd.isna(value):  # Raises ValueError for ambiguous datetime objects
            return None
    except (TypeError, ValueError):
        pass
```

`pd.isna()` on a `datetime` object raises `ValueError: The truth value of a Series is ambiguous`. The `except (TypeError, ValueError)` block catches this, so it won't crash, but the pattern silently suppresses errors that might indicate genuine data issues.

---

### Bug 49 — `routes.py` `OrderStatusUpdate` allows "backward" transitions (Picking → Open, Packed → Picking) with no audit trail indicator
**File:** [api/routes.py:763-766](../api-server-flask/api/routes.py#L763)  
**Severity:** LOW  
**Category:** Business Logic — Unclear Intent

```python
valid_transitions = {
    'Open': ['Picking'],
    'Picking': ['Packed', 'Open'],   # Allow going back to Open
    'Packed': ['Picking'],           # Allow going back to Picking
```

Backward transitions are allowed with no special flag or audit note. The state history will show a backward step with no indication it was a correction. If someone moves Picking→Open in error and then Open→Picking again, the history is ambiguous. There is also no permission check — any user who can manage the order can move it backward.

---

### Bug 50 — `WarehouseDashboard` and `OrderManagement` import the same `FilterControls` name from different files — wrong component may be used
**File:** [react-ui/src/views/warehouse/components/warehouseDashboard.components.js:42](../react-ui/src/views/warehouse/components/warehouseDashboard.components.js#L42), [react-ui/src/views/warehouse/components/orderManagement.components.js:55](../react-ui/src/views/warehouse/components/orderManagement.components.js#L55)  
**Severity:** LOW  
**Category:** Frontend — Naming Collision Risk

Both files export a component named `FilterControls`. If a developer imports from the wrong file (easy to do given similar paths), the wrong filter UI renders silently — warehouse dashboard gets order management filters and vice versa. The components have different props signatures so it would likely cause a runtime error, but the root cause is hard to trace.

---

## Summary Table

| # | Severity | File | Short Description |
|---|---|---|---|
| 1 | CRITICAL | routes.py:958 | `OrderPackedUpdate` — no auth |
| 2 | CRITICAL | routes.py:1249 | `OrderDispatchFinal` — no auth |
| 3 | CRITICAL | routes.py:580 | `OrderDetailWithProducts` — no auth |
| 4 | CRITICAL | routes.py:1641 | `InvoiceList` — no auth |
| 5 | CRITICAL | routes.py:1609 | `InvoiceStatistics` — no auth |
| 6 | CRITICAL | routes.py:1577 | `InvoiceErrorDownload` — no auth |
| 7 | CRITICAL | config.py:19-25 | Two incompatible JWT secrets |
| 8 | CRITICAL | config.py:19-25 | JWT secrets regenerate on restart |
| 9 | CRITICAL | routes.py:339 | Blocked users can still log in |
| 10 | HIGH | order_business.py:383 | `db_target` mutation in loop corrupts bulk update |
| 11 | HIGH | order_service.py:49 | Fake transaction — child saves use separate connections |
| 12 | HIGH | invoice_business.py:207 | `range(None)` crash for bypass orders |
| 13 | HIGH | routes.py:679 | `order_date.isoformat()` no null check |
| 14 | HIGH | routes.py:1499 | `changed_by=1` hardcoded in CompleteDispatch |
| 15 | HIGH | routes.py:1325 | `changed_by=1` hardcoded in OrderDispatchFinal |
| 16 | HIGH | routes.py:1504 | PotentialOrder never moves to Completed after dispatch |
| 17 | HIGH | db_manager.py:47 | Partition window silently hides orders >4 months old |
| 18 | HIGH | admin_routes.py:402 | Batch deletion has no transaction |
| 19 | HIGH | routes.py:1385 | Order and PotentialOrder get different statuses in MoveToInvoiced |
| 20 | MEDIUM | dashboard_routes.py:136 | Company list ignores warehouse_id filter |
| 21 | MEDIUM | dashboard_routes.py:369 | Bulk export silently truncates at 1000 orders |
| 22 | MEDIUM | permissions.py:12 | 9-12 DB queries per request for permission checks |
| 23 | MEDIUM | warehouseDashboard.components.js:73 | `wh.id` should be `wh.warehouse_id` — dashboard dropdown broken |
| 24 | MEDIUM | OrderManagement.js:353 | Pagination shows wrong total count; breaks >100 orders |
| 25 | MEDIUM | RestLogin.js:79 | Malformed function signature — `others` always empty |
| 26 | MEDIUM | accountReducer.js:10 | Expired token rehydrates as logged-in with no expiry check |
| 27 | MEDIUM | orderManagementService.js | Auth token never sent in API calls |
| 28 | MEDIUM | routes.py:415 | Token blocklist stores raw vs stripped tokens inconsistently |
| 29 | MEDIUM | order_business.py:34 | Full row data (PII) printed to stdout on every upload |
| 30 | MEDIUM | routes.py:257 | All exceptions masked as "Token is invalid" |
| 31 | MEDIUM | RestLogin.js:84 | "Remember me" checkbox is non-functional |
| 32 | MEDIUM | routes.py:299 / auth_routes.py:101 | Two separate auth systems, only one used by frontend |
| 33 | MEDIUM | orderManagement.components.js:197 | Empty box count field silently fails with no feedback |
| 34 | MEDIUM | orderManagementService.js:123 | `bulkStatusUpdate` missing try/catch |
| 35 | MEDIUM | admin_routes.py:501 | Invoice batch revert misses Order records older than 4 months |
| 36 | LOW | eway_bill_routes.py:27 | Eway guards skip check if current_user is None |
| 37 | LOW | config.py:37 | Hardcoded default DB password `root-pw` |
| 38 | LOW | routes.py:1240 | `/api/orders/<id>/dispatch` is dead code — never called by frontend |
| 39 | LOW | models.py:168 | `get_all()` has no pagination — will fail at scale |
| 40 | LOW | dashboardService.js:84 | `getOrderDetails` calls wrong API endpoint (no `/details`) |
| 41 | LOW | order_business.py:32 | ~2 DB queries per row in upload — 500 orders = 1000 queries |
| 42 | LOW | db_manager.py:205 | Broken connections returned to pool after exception |
| 43 | LOW | orderManagement.components.js:384 | Open and Picking show as same stepper step |
| 44 | LOW | invoice_service.py:44 | `analyze_errors` has wrong status name in error summary |
| 45 | LOW | auth_routes.py:259 | `Logout.post()` re-reads and re-parses token already validated by decorator |
| 46 | LOW | invoice_business.py:33 | `_TERMINAL_STATES` missing 'Partially Completed' |
| 47 | LOW | routes.py:384 | `EditUser` allows duplicate email/username without uniqueness check |
| 48 | LOW | invoice_business.py:317 | `pd.isna()` on datetime raises ValueError (caught but silent) |
| 49 | LOW | routes.py:763 | Backward state transitions allowed with no audit indication |
| 50 | LOW | components/ | `FilterControls` name collision between two component files |
