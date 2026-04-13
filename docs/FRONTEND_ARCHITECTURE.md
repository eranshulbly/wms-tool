# WMS Frontend — Architecture & Knowledge Reference

A complete technical reference for the React frontend located at `react-ui/src/`. Read this before touching any frontend code.

---

## Table of Contents

1. [Directory Structure](#1-directory-structure)
2. [Application Bootstrap](#2-application-bootstrap)
3. [Configuration Layer](#3-configuration-layer)
4. [Redux Store](#4-redux-store)
5. [Authentication Flow](#5-authentication-flow)
6. [API Service Layer](#6-api-service-layer)
7. [Context Layer](#7-context-layer)
8. [Custom Hooks](#8-custom-hooks)
9. [Routing & Route Guards](#9-routing--route-guards)
10. [Component Architecture](#10-component-architecture)
11. [Constants & Utils](#11-constants--utils)
12. [Order Lifecycle (Frontend)](#12-order-lifecycle-frontend)
13. [Upload Flow](#13-upload-flow)
14. [Key Function & Component Signatures](#14-key-function--component-signatures)

---

## 1. Directory Structure

```
react-ui/src/
├── App.js                          # Root component — router + Redux provider
├── config.js                       # API_SERVER base URL, other env constants
├── index.js                        # ReactDOM.render() entry point
│
├── services/                       # All backend communication
│   ├── api.js                      # Single shared axios instance with auth interceptor
│   ├── authService.js              # login(), logout(), register()
│   ├── orderService.js             # All order operations (get, update, bulk)
│   ├── warehouseService.js         # getWarehouses(), getCompanies()
│   ├── adminService.js             # Admin batch management endpoints
│   └── supplySheetService.js       # getSupplySheetDealers(), getSupplySheetRoutes(), getRouteDealers(), generateSupplySheet()
│
├── store/                          # Redux configuration
│   ├── index.js                    # configureStore() + redux-persist setup
│   ├── actions.js                  # Action type constants (SET_MENU, etc.)
│   ├── accountReducer.js           # Auth state: isLoggedIn, user, token
│   └── customizationReducer.js     # UI state: theme, drawer open/closed
│
├── context/
│   └── WarehouseContext.js         # Global warehouse/company selection state
│
├── hooks/
│   ├── useWarehouse.js             # useContext(WarehouseContext) alias
│   └── useSnackbar.js              # Notification state: show/hide snackbar
│
├── routes/
│   ├── index.js                    # Root router switch
│   ├── MainRoutes.js               # Authenticated app routes (lazy-loaded)
│   └── AuthenticationRoutes.js     # Login/register routes
│
├── layout/
│   ├── MainLayout/                 # Authenticated shell: AppBar + Sidebar + content
│   │   ├── index.js                # Wraps children in WarehouseProvider
│   │   ├── Header/                 # Top bar with warehouse selector + profile menu
│   │   └── Sidebar/                # Collapsible nav drawer
│   └── MinimalLayout/              # Bare layout for login/register pages
│
├── menu-items/
│   └── warehouse.js                # Sidebar nav items definition
│
├── context/
│   └── WarehouseContext.js         # WarehouseProvider + useWarehouse hook
│
├── views/
│   ├── pages/
│   │   └── authentication/
│   │       └── login/
│   │           └── RestLogin.js    # Login form (Formik + authService)
│   │
│   ├── admin/
│   │   ├── AdminControls.js            # Admin tab host (Delete Uploads, Dealer Town, Product Nickname)
│   │   └── tabs/
│   │       ├── DeleteUploads.js        # Admin batch deletion UI
│   │       ├── DealerTownUpload.js     # Bulk CSV upload + inline edit for dealer → town mapping
│   │       └── ProductNicknameUpload.js # Bulk CSV upload + inline edit for product nicknames
│   │
│   └── warehouse/
│       ├── constants/
│       │   └── statuses.js         # Single source: all status enums, mappings, columns
│       │
│       ├── utils/
│       │   └── index.js            # formatDate, getTimeInState, status converters
│       │
│       ├── components/
│       │   ├── FilterControls.js         # Warehouse/company/status dropdowns
│       │   ├── StatusChip.js             # Color-coded status badge
│       │   ├── CompactStatusSummary.js   # Horizontal status count pills strip
│       │   ├── StatusCard.js             # Per-status count card (dashboard grid)
│       │   ├── StatusActionButton.js     # Per-row "Move to X" button
│       │   ├── OrdersTable.js            # Unified paginated orders table
│       │   ├── OrderDetailsDialog.js     # Unified order modal (read-only + management)
│       │   ├── BulkActionsBar.js         # File upload + target-status bar
│       │   ├── UploadResultCard.js       # Upload result display (counts + error rows)
│       │   └── FileUploadForm/
│       │       └── index.js             # Generic config-driven upload form
│       │
│       ├── WarehouseDashboard.js         # Dashboard: status summary + orders table
│       ├── OrderManagement.js            # Full order management with status transitions
│       ├── OrderUpload.js                # Thin wrapper around FileUploadForm
│       ├── InvoiceUpload.js              # Thin wrapper around FileUploadForm
│       ├── ProductUpload.js              # Thin wrapper around FileUploadForm
│       ├── SupplySheetDownload.js        # Marketing supply sheet — searchable dealer table, auto-sorted PDF (dealer → order type → date)
│       └── EwayBillGenerator.js         # E-way bill generation
│
└── ui-component/                   # Shared UI primitives (MainCard, SubCard, etc.)
```

**Dependency graph (leaf → root, no cycles):**

```
config.js
  └─► services/api.js
        └─► services/authService, orderService, warehouseService
              └─► context/WarehouseContext
                    └─► hooks/useWarehouse
                          └─► views/warehouse/components/*
                                └─► views/warehouse/*.js (pages)
```

---

## 2. Application Bootstrap

### Entry point: `index.js`

```
ReactDOM.render(
  <Provider store={store}>          ← Redux store (with persist)
    <PersistGate persistor={persistor}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PersistGate>
  </Provider>
)
```

### App.js

Renders the root `<Switch>` with two top-level route groups:
- `/` (and sub-paths) → `MainRoutes` (requires authentication)
- `/login`, `/register` → `AuthenticationRoutes`

### MainLayout bootstrap

When any authenticated page loads, `MainLayout/index.js` wraps everything in `<WarehouseProvider>`. This means:
1. Warehouses are fetched once from the API via `getWarehouses()`
2. Companies are fetched once from the API via `getCompanies()`
3. All child pages access these via `useWarehouse()` — no page-level fetch needed

---

## 3. Configuration Layer

**`src/config.js`:**

```javascript
const config = {
  API_SERVER: 'http://localhost:5000/api/',  // trailing slash required
  // other env-specific values
};
export default config;
```

**Critical:** `config.API_SERVER` always ends with `/`. All service paths are written without a leading `/` or `/api/` prefix:

```javascript
// Correct
api.get('orders')
api.post('users/login', ...)

// Wrong
api.get('/api/orders')
api.get('/orders')
```

---

## 4. Redux Store

### `store/index.js`

Uses `redux-persist` to persist the `account` slice to `localStorage`:

```javascript
const persistConfig = {
  key: 'root',
  storage,
  whitelist: ['account']  // only account is persisted
};
```

### `store/accountReducer.js`

Manages auth state. Shape:

```javascript
{
  isLoggedIn: false,
  user: null,            // { id, name, email, role, warehouse_id, permissions }
  token: null            // JWT string (also written to localStorage as 'wms_token')
}
```

**Action types:**

| Action | Effect |
|---|---|
| `LOGIN` | Sets `isLoggedIn: true`, stores `user` and `token`, writes `wms_token` to `localStorage` |
| `LOGOUT` | Resets to initial state, removes `wms_token` from `localStorage` |

**`user.permissions`** shape:

```javascript
{
  order_states:      ['open', 'picking', 'packed', 'invoiced', ...],  // visible/actionable statuses
  uploads:           ['orders', 'invoices', 'products'],               // allowed upload types
  all_warehouses:    false,    // bypass warehouse scoping
  eway_bill_admin:   false,    // can configure e-way bill routes/mappings
  eway_bill_filling: false,    // can fill vehicle numbers and generate e-way files
  supply_sheet:      false,    // can access supply sheet and download PDFs
}
```

### `store/customizationReducer.js`

Controls sidebar open/closed and theme settings. Not business-logic related.

---

## 5. Authentication Flow

### Login sequence

```
RestLogin.js (Formik submit)
  → authService.login(email, password)
      → api.post('users/login', ...)
          ← { token, user: { id, name, email, role, warehouse_id, permissions } }
  → dispatch({ type: LOGIN, token, user })
      → accountReducer stores state + writes 'wms_token' to localStorage
  → navigate to '/'
```

### Request auth (every API call after login)

```
Any service call (e.g. orderService.getOrders(...))
  → api.js interceptor reads localStorage.getItem('wms_token')
  → Injects header: Authorization: Bearer <token>
  → Backend validates JWT
```

### Logout sequence

```
ProfileSection/index.js (user clicks Logout)
  → authService.logout()
      → api.post('users/logout')  ← token is in header via interceptor
  → dispatch({ type: LOGOUT })
      → accountReducer resets state + removes 'wms_token' from localStorage
  → navigate to '/login'
```

### Route Guards

| Guard | File | Behavior |
|---|---|---|
| `AuthGuard` | `routes/` | Redirects to `/login` if `!isLoggedIn` |
| `GuestGuard` | `routes/` | Redirects to `/` if already `isLoggedIn` |
| `AdminGuard` | `routes/` | Redirects unless `user.role === 'admin'` |
| `EwayFillingGuard` | `routes/` | Redirects unless `user.permissions.eway_bill_filling` or `user.role === 'admin'` |
| `UploadPermissionGuard` | `routes/` | Redirects unless the upload type is in `user.permissions.uploads` or `user.role === 'admin'` |
| `SupplySheetGuard` | `routes/` | Redirects unless `user.permissions.supply_sheet` or `user.role === 'admin'` |

All authenticated page routes in `MainRoutes.js` use Route's `render` prop to evaluate guards only when the specific path is matched — guards must never be placed as direct children of `<Switch>` or they will evaluate on every navigation. Each route wraps `AuthGuard` as the outermost guard, then the feature-specific guard inside.

---

## 6. API Service Layer

### `services/api.js` — Base instance

The single shared axios instance. **All services must import from here.**

```javascript
import axios from 'axios';
import config from '../config';

const api = axios.create({ baseURL: config.API_SERVER });

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('wms_token');
  if (token) {
    cfg.headers = cfg.headers || {};
    cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

export default api;
```

### `services/authService.js`

```javascript
login(email, password)   → api.post('users/login', { email, password })
logout()                 → api.post('users/logout')
register(data)           → api.post('users/register', data)
```

### `services/warehouseService.js`

```javascript
getWarehouses()          → api.get('warehouses').then(res => res.data)
getCompanies()           → api.get('companies').then(res => res.data)
```

Both return the raw `res.data` object (not the axios response wrapper). The returned object shapes:

```javascript
// getWarehouses() returns:
{ success: true, warehouses: [{ warehouse_id, name }, ...] }

// getCompanies() returns:
{ success: true, companies: [{ id, name }, ...] }
```

**Note:** Warehouses use `warehouse_id` as their primary key field (not `id`). Companies use `id`.

### `services/orderService.js`

All order operations. Every function returns the full axios response (caller reads `.data`).

```javascript
getOrders(warehouseId, companyId, status)
  // GET orders?warehouse_id=&company_id=&status=
  // status is a backend PascalCase string or empty for all

getOrderStatusCounts(warehouseId, companyId)
  // GET orders/status-counts?warehouse_id=&company_id=

getOrderDetails(orderId)
  // GET orders/<orderId>/details
  // Normalises current_state_time: appends 'Z' if no timezone suffix

updateOrderStatus(orderId, newStatus, additionalData)
  // POST orders/<orderId>/update-status
  // body: { new_status, ...additionalData }

completeDispatch(orderId)
  // POST orders/<orderId>/complete-dispatch

bulkStatusUpdate(file, targetStatus, warehouseId, companyId)
  // POST orders/bulk-update (multipart/form-data)
  // Returns UploadResultCard-compatible response

getRecentActivity(warehouseId, companyId, limit)
  // GET orders/recent-activity?warehouse_id=&company_id=&limit=
```

### `services/adminService.js`

Handles admin batch management. Unchanged from original — not part of the 5-phase refactor scope.

### `services/supplySheetService.js`

Supply sheet feature — all functions return `.then(res => res.data)` (resolves to the response body, not the axios wrapper).

```javascript
getSupplySheetDealers(warehouseId, companyId)
  // GET supply-sheet/dealers?warehouse_id=&company_id=
  // → { success, dealers: [{ dealer_id, name, dealer_code, town }] }
  // Only dealers with orders currently in 'Invoiced' state are returned.
  // Dealers whose orders have already been finalized (Dispatch Ready) are excluded.

getSupplySheetRoutes()
  // GET supply-sheet/routes
  // → { success, routes: [{ route_id, name, description }] }

getRouteDealers(routeId, warehouseId, companyId)
  // GET supply-sheet/routes/<routeId>/dealers?warehouse_id=&company_id=
  // → { success, dealers: [...] }
  // Also filtered to Invoiced orders only.

generateSupplySheet({ warehouse_id, company_id, dealer_ids, finalize })
  // POST supply-sheet/generate  — responseType: 'blob'
  // finalize: false (default) → preview only, no order state changes
  // finalize: true            → PDF generation + bulk-transition matching Invoiced
  //                             orders to Dispatch Ready (with audit history rows)
  // → Blob (PDF binary); create an object URL with URL.createObjectURL(blob)
```

---

## 7. Context Layer

### `context/WarehouseContext.js`

**Purpose:** Fetch reference data (warehouses + companies) once per app session and share the selection state across all pages. Eliminates the pattern of every page independently fetching warehouses on mount.

**Provider location:** `layout/MainLayout/index.js` wraps its children in `<WarehouseProvider>`. This means the context is available to every authenticated page.

**Context shape:**

```javascript
{
  warehouses: [{ warehouse_id, name }, ...],
  companies:  [{ id, name }, ...],
  warehouse:   string,              // selected warehouse id (warehouse_id value)
  company:     string,              // selected company id
  setWarehouse: (id) => void,
  setCompany:   (id) => void,
}
```

**Bootstrap behavior:**
1. On mount, `Promise.all([getWarehouses(), getCompanies()])` is called once
2. First warehouse is set as default via `wh.warehouse_id ?? wh.id` (handles legacy shape)
3. First company is set as default
4. Pages that need warehouse/company use `useWarehouse()` hook — no local state or fetch needed

---

## 8. Custom Hooks

### `hooks/useWarehouse.js`

```javascript
import { useContext } from 'react';
import { WarehouseContext } from '../context/WarehouseContext';

export default function useWarehouse() {
  return useContext(WarehouseContext);
}
```

Used in every component that needs `warehouses`, `companies`, `warehouse`, `company`, or the setters.

### `hooks/useSnackbar.js`

```javascript
export function useSnackbar() {
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

  const showSnackbar = (message, severity = 'success') =>
    setSnackbar({ open: true, message, severity });

  const hideSnackbar = (_, reason) => {
    if (reason === 'clickaway') return;
    setSnackbar(s => ({ ...s, open: false }));
  };

  return { snackbar, showSnackbar, hideSnackbar };
}
```

The `hideSnackbar` function guards against `clickaway` dismissal — only explicit close or auto-hide triggers it.

---

## 9. Routing & Route Guards

### `routes/MainRoutes.js`

All authenticated routes are lazy-loaded via `Loadable()`:

```javascript
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement    = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));
// ...
```

This project uses **React Router v5**. Each route uses the `render` prop to evaluate guards only when that specific path is matched — never wrap guards as direct `<Switch>` children or they evaluate on every navigation.

```javascript
// Pattern: AuthGuard (outermost) wraps the feature guard (innermost) wraps the page
<Switch location={location} key={location.pathname}>
  <Route path="/dashboard/default"
    render={() => <AuthGuard><WarehouseDashboard /></AuthGuard>} />

  <Route path="/warehouse/upload-products"
    render={() => (
      <AuthGuard>
        <UploadPermissionGuard uploadType="products">
          <ProductUpload />
        </UploadPermissionGuard>
      </AuthGuard>
    )} />

  <Route path="/warehouse/supply-sheet"
    render={() => (
      <AuthGuard>
        <SupplySheetGuard>
          <SupplySheetDownload />
        </SupplySheetGuard>
      </AuthGuard>
    )} />

  <Route path="/admin/controls"
    render={() => (
      <AuthGuard>
        <AdminGuard>
          <AdminControls />
        </AdminGuard>
      </AuthGuard>
    )} />
</Switch>
```

### Navigation guard chain

```
Request URL
  → Switch matches the first <Route path="..."> that fits
    → Route render prop fires
      → AuthGuard: not logged in → <Redirect to="/login" />, pending → waiting screen
      → Feature guard (AdminGuard / SupplySheetGuard / etc.): no permission → <Redirect to="/dashboard/default" />
      → Page component renders
```

---

## 10. Component Architecture

### Layout components

| Component | Purpose |
|---|---|
| `MainLayout` | App shell: AppBar + Sidebar + main content area. Wraps in `WarehouseProvider`. |
| `Header` | Top bar. Contains warehouse/company selectors and `ProfileSection`. |
| `Sidebar` | Collapsible nav drawer. Reads `menu-items/warehouse.js` for nav links. |
| `ProfileSection` | User avatar dropdown. Dispatches LOGOUT + calls `authService.logout()`. |

### Warehouse page components

#### `FilterControls`

Unified warehouse/company/status dropdown row used on both Dashboard and OrderManagement.

```javascript
Props:
  warehouses         [{ warehouse_id, name }]
  companies          [{ id, name }]
  warehouse          string              // selected warehouse id
  company            string              // selected company id
  statusFilter       string              // 'all' | status slug
  onWarehouseChange  (event) => void
  onCompanyChange    (event) => void
  onStatusFilterChange (event) => void
  allowedStatuses    string[] | null     // RBAC filter; null = show all
  classes            makeStyles object
```

#### `StatusChip`

Color-coded `<Chip>` component for displaying order status.

```javascript
Props:
  status   string   // any status string (backend or frontend, slug or PascalCase)
  classes  object   // makeStyles classes object
```

Internally normalises: `status.toLowerCase().replace(/ /g, '-')` then looks up display label in `STATUS_LABELS` and CSS class in `getStatusChipClass()`.

#### `CompactStatusSummary`

Horizontal strip of colored pill chips showing order count per status. Used at the top of WarehouseDashboard.

```javascript
Props:
  statusCounts   { open: n, picking: n, packed: n, ... }
  onStatusClick  (slug) => void
  classes        object
```

#### `OrdersTable`

Unified paginated orders table. Renders differently based on whether `onStatusUpdate` is provided.

```javascript
Props:
  orders                  Order[]
  totalCount              number               // for controlled pagination
  page                    number | undefined   // undefined = internal pagination
  rowsPerPage             number | undefined
  onPageChange            (event, page) => void | undefined
  onRowsPerPageChange     (event) => void | undefined
  loading                 boolean
  statusFilter            string
  onOrderClick            (order) => void
  onStatusUpdate          (order, action, data?) => void | undefined
                          // undefined = read-only mode (no Actions column)
  classes                 object
```

**Mode switching:**
- `showActions = typeof onStatusUpdate === 'function'`
- `showActions: true` → renders 6-column table with Actions column, wraps itself in `<Card>`
- `showActions: false` → renders 5-column table, returns bare table (no Card wrapper)
- `page === undefined` → internal pagination (slices data locally)
- `page !== undefined` → controlled pagination (parent passes pre-sliced data)

#### `OrderDetailsDialog`

Unified order detail modal. Mode-switched by `onStatusUpdate` prop.

```javascript
Props:
  order          Order | null
  open           boolean
  onClose        () => void
  onStatusUpdate (order, action, data?) => void | undefined
                 // undefined = read-only mode (dashboard)
```

**Read-only mode (Dashboard):** Shows order header, basic info, timeline.  
**Management mode (OrderManagement):** Shows stepper (Order Details → Packed → Invoiced → Dispatch Ready → Completed), product table, action buttons (with box-count prompt for Picking→Packed), timeline.

Internal state flag `isCompletingDispatch` prevents duplicate `completeDispatch()` calls.

#### `StatusActionButton`

Per-row button that moves an order to its next status. Shows box-count dialog for Picking→Packed.

```javascript
Props:
  order          Order
  onStatusUpdate (order, action, data?) => void
  classes        object
```

Uses an internal `CORRECT_STATUS_PROGRESSION` map (not the one from constants) to determine the next state and button label.

#### `BulkActionsBar`

File-upload bar for bulk status changes. Shows inline `UploadResultCard` after upload.

```javascript
Props:
  warehouse        string    // warehouse id
  company          string    // company id
  onUploadComplete () => void
```

Calls `bulkStatusUpdate()` from `orderService`. The file input accepts `.csv, .xls, .xlsx`.

#### `UploadResultCard`

Displays upload result counts and an optional error rows table.

```javascript
Props:
  result   {
    success: boolean,
    message: string,
    processed?: number,
    errors?: number,
    error_rows?: [{ row, error }],
    // + domain-specific fields passed via computeExtraStats
  }
  onDownloadErrors  () => void | undefined
```

#### `FileUploadForm` (`components/FileUploadForm/index.js`)

Generic config-driven upload form. The single implementation shared by OrderUpload, InvoiceUpload, ProductUpload.

```javascript
Props:
  endpoint           string         // relative API path (e.g. 'orders/upload')
  maxSizeMB          number         // default: 10
  acceptedFormats    string         // e.g. '.csv,.xls,.xlsx'
  requiresWarehouse  boolean        // show warehouse selector
  requiresCompany    boolean        // show company selector
  title              string         // page heading
  successLabel       string         // label for processed count chip
  errorFilename      string         // base filename for error download
  processingMessage  string
  uploadButtonLabel  string
  inputId            string         // unique id for hidden file <input>
  descriptionNode    ReactNode      // slot for page-specific description text
  rulesNode          ReactNode      // slot for file format rules
  computeExtraStats  (responseData) => [{ label, value, color }]
                                    // function for domain-specific result stats
```

Internals: uses `useWarehouse()` for warehouse/company state, `useSnackbar()` for notifications, `api.js` directly for the authenticated POST.

### Page components

#### `SupplySheetDownload`

- Reads `{ warehouse, company }` from `useWarehouse()` — no local warehouse state
- Loads only dealers with currently **Invoiced** orders (backend filters out already-dispatched dealers)
- **Searchable dealer table** — client-side filter by name, dealer code, or town; no dropdown
- Route selector (optional) auto-adds route dealers into the current selection via `getRouteDealers()`
- Selected dealers shown as removable chips; select-all checkbox scopes to the current search results
- PDF columns: Invoice No. · Order No. · **Order Type** · Account Name · Town · Invoice Value · Cases · [oil product columns] · Invoice Date; rows sorted server-side: dealer name → order type → invoice date

**Two-step download flow (Preview vs. Download):**

| Action | `finalize` flag | Side effects |
|---|---|---|
| **Preview PDF** | `false` | Generates PDF, caches object URL, opens preview dialog. No order state changes. |
| **Download PDF** | `true` | Shows confirmation dialog first. On confirm, always re-generates PDF with `finalize: true`, downloads it, then reloads the dealer list and clears the selection. |

**Confirmation dialog** (shown before every download):
- Lists the selected dealer names (up to 20 + overflow count)
- Warns that all Invoiced orders for those dealers will be moved to **Dispatch Ready** and cannot be selected for a supply sheet again
- Buttons: Cancel | Confirm & Download

After a confirmed download the dealer list is automatically refreshed — finalized dealers disappear because their orders are no longer in `Invoiced` state.

#### `AdminControls`

Tab host for admin-only management panels. Adding a new admin tab = add one entry to the `TABS` array at the top of `AdminControls.js`; no other changes needed.

| Tab id | Label | Component | Purpose |
|---|---|---|---|
| `delete-uploads` | Delete Uploads | `DeleteUploads` | Hard-delete order/invoice upload batches |
| `dealer-town` | Dealer Town Master | `DealerTownUpload` | Bulk CSV upload + inline edit for dealer → town mapping |
| `product-nickname` | Product Nickname | `ProductNicknameUpload` | Bulk CSV upload + inline edit for product nicknames used on supply sheet PDFs |

`ProductNicknameUpload` mirrors `DealerTownUpload` in structure: drag-and-drop file upload (columns: `Product String`, `Nickname`) + searchable product table with inline edit. The nickname, if set, replaces the product description as the oil-column header in the supply sheet PDF.

#### `WarehouseDashboard`

- Reads `{ warehouse, company }` from `useWarehouse()` — no local warehouse state
- Fetches `getOrderStatusCounts()` and `getRecentActivity()` when warehouse/company change
- Uses `CompactStatusSummary` + `OrdersTable` (uncontrolled/read-only) + `OrderDetailsDialog` (read-only)
- `onOrderClick` → `getOrderDetails()` → opens dialog

#### `OrderManagement`

- Reads `{ warehouse, company }` from `useWarehouse()` — no local warehouse state
- Uses `useSnackbar()` for notifications
- Controlled pagination: page/rowsPerPage in local state, slices `orders` before passing to `OrdersTable`
- Uses `FilterControls`, `BulkActionsBar`, `OrdersTable` (management mode), `OrderDetailsDialog` (management mode)
- `onStatusUpdate` dispatches to `updateOrderStatus()` or `completeDispatch()` then refreshes

---

## 11. Constants & Utils

### `views/warehouse/constants/statuses.js`

**Single source of truth for all status-related constants.** Never define status strings, labels, or mappings anywhere else.

Key exports:

| Export | Type | Purpose |
|---|---|---|
| `ORDER_STATUS_DATA` | Object | Icon, label, chipClass per status slug |
| `STATUS_LABELS` | Object | slug → display string (e.g. `'dispatch-ready'` → `'Dispatch Ready'`) |
| `STATUS_FILTER_OPTIONS` | Array | `[{ value, label }]` for filter dropdowns |
| `STATUS_PROGRESSION` | Object | Manual UI transitions: slug → next slug (or `null`) |
| `BULK_TARGET_STATUSES` | Array | `[{ value, label, requiresBoxes }]` |
| `FRONTEND_TO_BACKEND_STATUS` | Object | `'dispatch-ready'` → `'Dispatch Ready'` |
| `BACKEND_TO_FRONTEND_STATUS` | Object | `'Dispatch Ready'` → `'dispatch-ready'` |
| `DATE_FORMAT_OPTIONS` | Object | Shared `Intl.DateTimeFormat` options |
| `TABLE_COLUMNS_BASE` | Array | 5 column definitions (no Actions) |
| `TABLE_COLUMNS_WITH_ACTIONS` | Array | 6 column definitions (with Actions) |

**Status slug convention:**

```
Frontend slugs: lowercase, hyphenated   →  'dispatch-ready', 'partially-completed'
Backend strings: PascalCase with spaces →  'Dispatch Ready', 'Partially Completed'
```

Always convert using `FRONTEND_TO_BACKEND_STATUS` / `BACKEND_TO_FRONTEND_STATUS` when crossing the API boundary.

### `views/warehouse/utils/index.js`

Key exports:

```javascript
formatDate(dateString)
  // → 'Apr 12, 2026, 10:30 AM' using DATE_FORMAT_OPTIONS
  // Returns 'N/A' for null/undefined

getTimeInState(dateString)
  // → '2h 15m' or '3d 4h' — time elapsed since dateString
  // Appends 'Z' if the string has no timezone suffix (backend returns UTC without Z)

getNextStatus(currentStatus)
  // → next slug string per STATUS_PROGRESSION, or null if no manual transition

getStatusChipClass(status)
  // → CSS class name string for makeStyles chip styling
  // Normalises to slug before lookup

filterOrdersByStatus(orders, statusFilter)
  // → filtered array; returns all if statusFilter === 'all'

frontendToBackendStatus(slug)   // 'dispatch-ready' → 'Dispatch Ready'
backendToFrontendStatus(status) // 'Dispatch Ready' → 'dispatch-ready'
```

---

## 12. Order Lifecycle (Frontend)

### Status slugs and transitions

```
open
  ↓  (manual: Move to Picking)
picking
  ↓  (manual: Move to Packed — prompts for box count)
packed
  ↓  (automatic: when invoice is uploaded via InvoiceUpload)
invoiced
  ↓  (manual: Complete Dispatch — in OrderDetailsDialog management mode)
dispatch-ready
  ↓  (automatic or manual depending on config)
completed
    (also: partially-completed — terminal state, no manual transition)
```

### Invoice-submitted badge

When `order.invoice_submitted === true` but status is not yet `invoiced`, `OrdersTable` renders an orange "Invoice Submitted" chip alongside the status chip. Tooltip explains: invoice uploaded but order is not yet Packed; will auto-transition when moved to Packed.

### RBAC filtering

`user.permissions.order_states` is an array of slugs the user is allowed to see/act on. `FilterControls` receives this as `allowedStatuses` and filters dropdown options accordingly.

---

## 13. Upload Flow

All three upload pages (`OrderUpload`, `InvoiceUpload`, `ProductUpload`) are thin wrappers around `FileUploadForm`. The full flow is:

```
User drops file or clicks Browse
  → FileUploadForm validates file type (acceptedFormats) and size (maxSizeMB)
  → Validation fails: showSnackbar('...', 'error'), no API call
  → Validation passes: setLoading(true)
      → api.post(endpoint, FormData { file, warehouse_id?, company_id? })
          ← { success, message, processed, errors, error_rows, ... }
      → setLoading(false)
      → success: show UploadResultCard with counts
      → failure: showSnackbar(error message, 'error')

Error download:
  → User clicks "Download Error Report" in UploadResultCard
      → Constructs Excel in-memory (SheetJS or backend endpoint)
      → Triggers browser download
```

**Auth:** `FileUploadForm` uses `api.js` directly — the auth interceptor is always applied. Never use raw `axios` for uploads.

---

## 14. Key Function & Component Signatures

### Service signatures (all return axios response or `.then(res => res.data)`)

```javascript
// authService
login(email: string, password: string): Promise<AxiosResponse>
logout(): Promise<AxiosResponse>
register(data: object): Promise<AxiosResponse>

// warehouseService
getWarehouses(): Promise<{ success, warehouses }>
getCompanies(): Promise<{ success, companies }>

// supplySheetService (all return .then(res => res.data))
getSupplySheetDealers(warehouseId, companyId): Promise<{ success, dealers }>
getSupplySheetRoutes(): Promise<{ success, routes }>
getRouteDealers(routeId, warehouseId, companyId): Promise<{ success, dealers }>
generateSupplySheet({ warehouse_id, company_id, dealer_ids, finalize }): Promise<Blob>

// orderService
getOrders(warehouseId, companyId, status): Promise<AxiosResponse>
getOrderStatusCounts(warehouseId, companyId): Promise<AxiosResponse>
getOrderDetails(orderId): Promise<AxiosResponse>
updateOrderStatus(orderId, newStatus, additionalData): Promise<AxiosResponse>
completeDispatch(orderId): Promise<AxiosResponse>
bulkStatusUpdate(file, targetStatus, warehouseId, companyId): Promise<AxiosResponse>
getRecentActivity(warehouseId, companyId, limit): Promise<AxiosResponse>
```

### Hook return shapes

```javascript
// useWarehouse()
{
  warehouses: [{ warehouse_id, name }],
  companies:  [{ id, name }],
  warehouse:   string,
  company:     string,
  setWarehouse: (id: string) => void,
  setCompany:   (id: string) => void,
}

// useSnackbar()
{
  snackbar: { open: boolean, message: string, severity: 'success'|'error'|'warning'|'info' },
  showSnackbar: (message: string, severity?: string) => void,
  hideSnackbar: (event, reason?) => void,
}
```

### Redux dispatch patterns

```javascript
// Login
dispatch({ type: 'LOGIN', token: string, user: object })

// Logout
dispatch({ type: 'LOGOUT' })

// Read auth state
const { isLoggedIn, user, token } = useSelector(state => state.account)
```
