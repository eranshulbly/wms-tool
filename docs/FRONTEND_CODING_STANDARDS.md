# WMS Frontend — Coding Standards & Patterns

How to write new code and modify existing code in this React codebase. Read `FRONTEND_ARCHITECTURE.md` first for context. This document answers: **how do I actually write it?**

---

## Table of Contents

1. [Golden Rules (Never Break These)](#1-golden-rules-never-break-these)
2. [Adding a New Service Function](#2-adding-a-new-service-function)
3. [Adding a New Page](#3-adding-a-new-page)
4. [Adding a New Upload Page](#4-adding-a-new-upload-page)
5. [Adding a New Component](#5-adding-a-new-component)
6. [Working with Order Statuses](#6-working-with-order-statuses)
7. [Working with Warehouse & Company State](#7-working-with-warehouse--company-state)
8. [Handling Notifications](#8-handling-notifications)
9. [Styling Patterns](#9-styling-patterns)
10. [State Management Rules](#10-state-management-rules)
11. [Import Path Rules](#11-import-path-rules)
12. [Common Mistakes to Avoid](#12-common-mistakes-to-avoid)
13. [Prompts for AI-Assisted Development](#13-prompts-for-ai-assisted-development)

---

## 1. Golden Rules (Never Break These)

These rules exist because of past incidents or deliberate architectural decisions. Violating any of them introduces bugs or regressions.

### Never use raw `axios` — always use `services/api.js`
**Why:** Raw axios calls skip the auth interceptor. The backend returns 401 and the user sees a silent failure with no redirect.  
**Instead:**
```javascript
// Wrong
import axios from 'axios';
axios.post('http://localhost:5000/api/orders/upload', formData);

// Correct
import api from '../../services/api';
api.post('orders/upload', formData);
```

### Never fetch warehouses or companies inside a page component
**Why:** Before the refactor, every page independently called `getWarehouses()` on mount. This caused 5+ redundant API calls on navigation and stale state when the user changed the selection on one page.  
**Instead:** Call `useWarehouse()`. The `WarehouseProvider` (in `MainLayout`) fetches once and shares the state.
```javascript
// Wrong
const [warehouses, setWarehouses] = useState([]);
useEffect(() => { getWarehouses().then(r => setWarehouses(r.warehouses)); }, []);

// Correct
const { warehouses, companies, warehouse, company, setWarehouse, setCompany } = useWarehouse();
```

### Never hardcode status strings — use constants from `statuses.js`
**Why:** Status strings like `'Dispatch Ready'` or `'dispatch-ready'` are used in comparisons, API calls, and display. A single typo (`'Dispatch ready'`) is a silent bug — it won't crash, it just shows wrong data.  
**Instead:**
```javascript
// Wrong
if (order.status === 'Dispatch Ready') { ... }
api.post('orders/1/update-status', { new_status: 'Picking' });

// Correct
import { FRONTEND_TO_BACKEND_STATUS } from '../constants/statuses';
if (backendToFrontendStatus(order.status) === 'dispatch-ready') { ... }
api.post(`orders/${id}/update-status`, { new_status: FRONTEND_TO_BACKEND_STATUS['picking'] });
```

### Never use raw `axios.Authorization` without `Bearer ` prefix
**Why:** The original `ProfileSection` logout sent `Authorization: ${token}` (missing `Bearer `). The backend rejected it silently. The bug was masked because the page still redirected.  
**Instead:** Use `authService.logout()` which goes through the `api.js` interceptor that correctly formats `Bearer <token>`.

### Never define status transitions outside the statuses constants
**Why:** `StatusActionButton` has an internal progression map AND `statuses.js` has `STATUS_PROGRESSION`. If you add a new status, you must update both — this is a known duplication. Do not create a third map.  
**Rule:** When editing status transitions, update `STATUS_PROGRESSION` in `constants/statuses.js` first, then sync `StatusActionButton.js`'s internal map if it diverges.

### Never use `console.log` for debugging in committed code
**Why:** Leaks internal state and order data to the browser console. Use React DevTools or a proper error boundary.  
**Instead:** Remove debug logs before committing. `console.error` is acceptable for caught errors.

### Always show a confirmation dialog before irreversible backend state changes
**Why:** Actions like supply sheet download transition orders to Dispatch Ready permanently — there is no undo. A user who clicks the button accidentally or without reading the implications causes operational errors.  
**Rule:** Any frontend action that triggers a permanent, bulk state change (e.g. moving orders, deleting batches) must:
1. Open a `<Dialog>` that describes exactly what will change and lists affected items
2. Require an explicit confirm click before calling the API
3. Show a success snackbar after completion that confirms what changed

The `finalize: true` supply sheet download in `SupplySheetDownload.js` is the reference implementation for this pattern.

### Never add `localStorage` token access outside `services/api.js`
**Why:** The token key (`'wms_token'`) is accessed in `api.js` (interceptor) and `accountReducer.js` (write/delete). Any third location reading the token directly bypasses the auth flow and will break if the key name changes.  
**Instead:** Get the token from Redux state if you need to display it, or let `api.js` handle it for API calls.

### Always gate new features behind the appropriate permission guard
**Why:** The sidebar can hide menu items, but a user who knows the URL can still navigate directly to an unguarded route. Backend decorators enforce access at the API level, but the frontend must also redirect unauthorized users so they never see a broken page.  
**Rule:** Every new route must answer: *who can access this?* Then wrap it in the right guard in `MainRoutes.js` **and** hide its menu item in `MenuList/index.js`.

| Feature type | Route guard | Menu visibility |
|---|---|---|
| Admin-only pages | `<AdminGuard>` | Hidden for non-admin via `item.id === 'admin'` check |
| Upload pages (`orders`, `invoices`, `products`) | `<UploadPermissionGuard uploadType="...">` | Filtered via `UPLOAD_PERMISSION_MAP` in `MenuList` |
| Supply sheet | `<SupplySheetGuard>` | Gated via `user.permissions.supply_sheet` in `MenuList` |
| E-way bill filling | `<EwayFillingGuard>` | Gated via `user.permissions.eway_bill_filling` in `MenuList` |
| Authenticated users only | `<AuthGuard>` (already wraps all main routes) | — |

If the feature introduces a brand-new permission type, **create a new guard component** in `utils/route-guard/` following the same pattern as `SupplySheetGuard.js` or `EwayFillingGuard.js`. Do not skip the guard and rely on backend 403s alone — that produces a broken blank page for the user.

---

## 2. Adding a New Service Function

### Step 1 — Decide which service file it belongs to

| Domain | File |
|---|---|
| Login, logout, register | `services/authService.js` |
| Warehouse list, company list | `services/warehouseService.js` |
| Orders, status updates, bulk ops | `services/orderService.js` |
| Admin batch management | `services/adminService.js` |
| Supply sheet dealers, routes, PDF generation | `services/supplySheetService.js` |
| New domain entirely | Create `services/newDomainService.js` |

### Step 2 — Write a named export function

```javascript
// services/orderService.js

// Correct pattern: named export, uses api.js, relative path (no /api/ prefix)
export const cancelOrder = (orderId, reason) =>
  api.post(`orders/${orderId}/cancel`, { reason });

// Wrong: default export, raw axios, wrong path format
export default function cancelOrder(orderId) {
  return axios.post('/api/orders/' + orderId + '/cancel');
}
```

### Step 3 — Return the full axios response (not `.data`)

Service functions return the raw axios response. The calling component reads `.data`:

```javascript
// In service
export const getOrders = (warehouseId, companyId) =>
  api.get('orders', { params: { warehouse_id: warehouseId, company_id: companyId } });

// In component
const response = await getOrders(warehouse, company);
const orders = response.data.orders;
```

**Exception:** `warehouseService.js` returns `.then(res => res.data)` for convenience since it's called in the context initializer. Follow the existing pattern in the file you're editing.

### Step 4 — Handle errors in the component, not the service

```javascript
// Service: just throw/reject
export const deleteOrder = (orderId) => api.delete(`orders/${orderId}`);

// Component: catch and show notification
try {
  await deleteOrder(orderId);
  showSnackbar('Order deleted', 'success');
} catch (err) {
  showSnackbar(err.response?.data?.msg || 'Delete failed', 'error');
}
```

---

## 3. Adding a New Page

### Step 1 — Create the page file

Place it in `views/warehouse/` for warehouse-related pages:

```javascript
// views/warehouse/NewPage.js
import React, { useState, useEffect } from 'react';
import { Grid } from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../hooks/useWarehouse';
import { useSnackbar } from '../../hooks/useSnackbar';

const useStyles = makeStyles((theme) => ({
  // page-specific styles only
}));

const NewPage = () => {
  const classes = useStyles();
  const { warehouse, company } = useWarehouse();
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  // page state here

  return (
    <Grid container spacing={gridSpacing}>
      {/* content */}
    </Grid>
  );
};

export default NewPage;
```

### Step 2 — Add a lazy-loaded route in `routes/MainRoutes.js`

```javascript
const NewPage = Loadable(lazy(() => import('../views/warehouse/NewPage')));

// In the children array:
{ path: 'new-page', element: <NewPage /> }
```

### Step 3 — Add to sidebar navigation in `menu-items/warehouse.js`

```javascript
{
  id: 'new-page',
  title: 'New Page',
  type: 'item',
  url: '/new-page',
  icon: IconSomething,
  breadcrumbs: false
}
```

### Step 4 — Always define user-level authorization (required, not optional)

Every new page must be gated. Use React Router v5's `render` prop pattern in `MainRoutes.js` — **never** wrap `<Route>` inside a guard as a child, because React Router v5's `<Switch>` evaluates pathless wrappers unconditionally and the guard fires on every navigation.

```javascript
// Wrong — guard fires on EVERY navigation, not just when path matches
<SupplySheetGuard>
    <Route path="/warehouse/supply-sheet" component={SupplySheetDownload} />
</SupplySheetGuard>

// Correct — guard only fires when this path is matched
<Route
    path="/warehouse/supply-sheet"
    render={() => (
        <AuthGuard>
            <SupplySheetGuard>
                <SupplySheetDownload />
            </SupplySheetGuard>
        </AuthGuard>
    )}
/>

// Admin-only page
<Route
    path="/admin/controls"
    render={() => (
        <AuthGuard>
            <AdminGuard>
                <AdminControls />
            </AdminGuard>
        </AuthGuard>
    )}
/>

// Upload page gated by upload permission
<Route
    path="/warehouse/upload-products"
    render={() => (
        <AuthGuard>
            <UploadPermissionGuard uploadType="products">
                <ProductUpload />
            </UploadPermissionGuard>
        </AuthGuard>
    )}
/>
```

Guard nesting order: `AuthGuard` (outermost, always first) → feature guard → page component.

Then hide the corresponding menu item in `menu-items/warehouse.js` by adding it to `UPLOAD_PERMISSION_MAP` in `MenuList/index.js` (for upload-type permissions) or adding an explicit `child.id` check (for boolean permissions like `supply-sheet`). A user who lacks permission should never see the menu item — the route guard is the safety net, not the primary UX.

If none of the existing guards fit, create a new one in `utils/route-guard/` modelled on `SupplySheetGuard.js`.

---

## 4. Adding a New Upload Page

All upload pages are thin wrappers around `FileUploadForm`. Do not duplicate upload logic.

```javascript
// views/warehouse/NewTypeUpload.js
import React from 'react';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';

const NewTypeUpload = () => (
  <MainCard title="Upload New Type">
    <FileUploadForm
      endpoint="new-type/upload"          // relative path, no /api/ prefix
      acceptedFormats=".csv,.xls,.xlsx"
      maxSizeMB={10}
      requiresWarehouse={true}
      requiresCompany={true}
      inputId="new-type-file-input"       // must be unique across all upload pages
      title="Drop your file here"
      successLabel="Records Processed"
      errorFilename="new_type_errors"
      processingMessage="Processing your file..."
      uploadButtonLabel="Upload File"
      descriptionNode={
        <p>Description of the expected file format.</p>
      }
      rulesNode={
        <ul>
          <li>Row format rule 1</li>
          <li>Row format rule 2</li>
        </ul>
      }
      computeExtraStats={(data) => [
        { label: 'Records Created', value: data.created ?? 0, color: 'success' },
        { label: 'Errors', value: data.error_count ?? 0, color: 'error' },
      ]}
    />
  </MainCard>
);

export default NewTypeUpload;
```

**`inputId` must be unique.** If two upload pages share the same `id` on their hidden file input, clicking "Browse" on one page may trigger the wrong input.

---

## 5. Adding a New Component

### Placement rules

| Component type | Location |
|---|---|
| Reused across multiple warehouse pages | `views/warehouse/components/` |
| Used by a single page only | Inline in the page file, or `views/warehouse/components/` if it's large |
| Shared across the whole app | `ui-component/` |

### Component template

```javascript
// views/warehouse/components/NewComponent.js
import React from 'react';
import { Box, Typography } from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';

const useStyles = makeStyles((theme) => ({
  root: {
    // styles
  }
}));

/**
 * NewComponent — one-sentence description.
 *
 * Props:
 *   value    — description
 *   onChange — (newValue) => void
 */
const NewComponent = ({ value, onChange, classes: externalClasses }) => {
  const classes = useStyles();

  return (
    <Box className={classes.root}>
      {/* content */}
    </Box>
  );
};

export default NewComponent;
```

### Props conventions

- If the parent passes a `classes` prop (makeStyles object), accept it as `classes` and use it for shared style tokens.
- Use `externalClasses` vs local `classes` when both exist (see pattern in `OrdersTable.js`).
- Never use inline `style={{}}` for variant-driven styles — use `makeStyles` class names.
- Inline `style={{}}` is acceptable for one-off layout tweaks like `style={{ marginTop: 16 }}`.

---

## 6. Working with Order Statuses

### Always use the slug ↔ backend string converters

```javascript
import {
  FRONTEND_TO_BACKEND_STATUS,
  BACKEND_TO_FRONTEND_STATUS,
  STATUS_LABELS,
  STATUS_FILTER_OPTIONS,
} from '../constants/statuses';
import { frontendToBackendStatus, backendToFrontendStatus } from '../utils';

// Convert before sending to API
const backendStatus = frontendToBackendStatus('dispatch-ready'); // → 'Dispatch Ready'

// Convert after receiving from API
const slug = backendToFrontendStatus(order.status); // → 'dispatch-ready'

// Display label for a slug
const label = STATUS_LABELS['dispatch-ready']; // → 'Dispatch Ready'
```

### Status comparison rules

Always compare using **slugs** (lowercase-hyphenated), never backend strings:

```javascript
// Wrong
if (order.status === 'Dispatch Ready') { }

// Correct
if (backendToFrontendStatus(order.status) === 'dispatch-ready') { }
```

### Adding a new status

1. Add the slug → label to `STATUS_LABELS` in `constants/statuses.js`
2. Add to `STATUS_FILTER_OPTIONS` array
3. Add to `FRONTEND_TO_BACKEND_STATUS` and `BACKEND_TO_FRONTEND_STATUS` maps
4. Add to `STATUS_PROGRESSION` (set value to `null` if it's a terminal state)
5. Add to `ORDER_STATUS_DATA` with icon, label, chipClass
6. Add chip color class to `makeStyles` in `OrderManagement.js` and `WarehouseDashboard.js`
7. Sync `StatusActionButton.js`'s internal progression map
8. Update the backend `OrderStatus` enum accordingly

---

## 7. Working with Warehouse & Company State

### Reading warehouse/company in a component

```javascript
import { useWarehouse } from '../../hooks/useWarehouse';

const MyComponent = () => {
  const { warehouse, company, warehouses, companies, setWarehouse, setCompany } = useWarehouse();
  // warehouse = selected warehouse id (warehouse_id value, not index)
  // company  = selected company id
};
```

### Warehouse id field name

Warehouse objects use `warehouse_id` as their primary key, not `id`. Companies use `id`. This inconsistency is in the backend API response:

```javascript
// Warehouse shape
{ warehouse_id: '1', name: 'Main Warehouse' }

// Company shape
{ id: '2', name: 'Acme Corp' }
```

When rendering warehouse selects, always use `wh.warehouse_id ?? wh.id` as the fallback in case the shape changes:

```javascript
warehouses.map((wh) => (
  <MenuItem key={wh.warehouse_id ?? wh.id} value={wh.warehouse_id ?? wh.id}>
    {wh.name}
  </MenuItem>
))
```

### Re-fetching data when warehouse/company changes

Use `useEffect` with `[warehouse, company]` as deps:

```javascript
useEffect(() => {
  if (!warehouse || !company) return;
  fetchOrders();
}, [warehouse, company]);
```

Do not fetch if either value is empty — the context is still loading.

---

## 8. Handling Notifications

Always use the `useSnackbar` hook. Never manage snackbar state manually.

```javascript
import { useSnackbar } from '../../hooks/useSnackbar';

const MyPage = () => {
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  const handleSave = async () => {
    try {
      await saveData();
      showSnackbar('Saved successfully', 'success');
    } catch (err) {
      showSnackbar(err.response?.data?.msg || 'Save failed', 'error');
    }
  };

  return (
    <>
      {/* page content */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={hideSnackbar}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Alert onClose={hideSnackbar} severity={snackbar.severity} variant="filled">
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  );
};
```

### Severity values

| Value | When to use |
|---|---|
| `'success'` | Operation completed without errors |
| `'error'` | Operation failed or API returned error |
| `'warning'` | Completed with partial errors (e.g. some rows failed) |
| `'info'` | Neutral information, no action required |

---

## 9. Styling Patterns

### Use `makeStyles` for all component-specific styles

```javascript
import { makeStyles } from '@material-ui/styles';

const useStyles = makeStyles((theme) => ({
  card: {
    marginBottom: theme.spacing(2),
  },
  header: {
    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    color: 'white',
    padding: theme.spacing(3),
    borderRadius: theme.shape.borderRadius,
  },
}));
```

### Status chip color classes

Status chips use CSS class names injected via `makeStyles`. Follow the existing pattern in `WarehouseDashboard.js`:

```javascript
const useStyles = makeStyles((theme) => ({
  chipOpen:             { backgroundColor: '#ed6c02', color: 'white' },
  chipPicking:          { backgroundColor: '#1976d2', color: 'white' },
  chipPacked:           { backgroundColor: '#9c27b0', color: 'white' },
  chipInvoiced:         { backgroundColor: '#0288d1', color: 'white' },
  chipDispatchReady:    { backgroundColor: '#2e7d32', color: 'white' },
  chipCompleted:        { backgroundColor: '#4caf50', color: 'white' },
  chipPartiallyCompleted: { backgroundColor: '#ff9800', color: 'white' },
}));
```

The class name strings must match exactly what `getStatusChipClass()` returns. If you rename a class, update both.

### Grid spacing

Always use `gridSpacing` from `store/constant`:

```javascript
import { gridSpacing } from '../../store/constant';

<Grid container spacing={gridSpacing}>
```

Never hardcode `spacing={3}` — `gridSpacing` is the configurable theme value.

---

## 10. State Management Rules

### Local state (useState) — use for

- UI-only state: dialog open/closed, loading flags, current page number
- Form values that don't need to persist across navigation
- Temporary result data (upload response, fetched order details)

### Context state (WarehouseContext) — use for

- Currently selected warehouse and company
- Warehouse and company lists (reference data)

### Redux state (store) — use for

- Auth: `isLoggedIn`, `user`, `token`
- UI customization: drawer open/closed, theme

### Rules

- **Do not** put order data in Redux. Orders are fetched per-page and are too volatile for global state.
- **Do not** replicate `warehouse`/`company` as local `useState` in any page component. Use the context.
- **Do not** dispatch custom Redux actions for business state — the store is for auth and UI only.

---

## 11. Import Path Rules

### Service imports

```javascript
// From a warehouse page (views/warehouse/*.js)
import api from '../../services/api';
import { getOrders } from '../../services/orderService';
import { useWarehouse } from '../../hooks/useWarehouse';
import { useSnackbar } from '../../hooks/useSnackbar';
```

### Constants and utils imports

```javascript
// From a component (views/warehouse/components/*.js)
import { STATUS_LABELS, STATUS_FILTER_OPTIONS } from '../constants/statuses';
import { formatDate, getTimeInState, backendToFrontendStatus } from '../utils';
```

### Component imports

```javascript
// From a warehouse page
import FilterControls from './components/FilterControls';
import OrdersTable from './components/OrdersTable';
import OrderDetailsDialog from './components/OrderDetailsDialog';
```

### Never use absolute paths or `src/` aliases

This codebase uses relative imports everywhere. Do not introduce path aliases (`@/`, `~/`) unless the build config is updated to support them.

```javascript
// Wrong
import api from 'src/services/api';
import api from '@/services/api';

// Correct
import api from '../../services/api';
```

---

## 12. Common Mistakes to Avoid

### Mistake: Calling `getWarehouses()` inside a page component

```javascript
// Wrong — causes duplicate fetches, stale state across pages
useEffect(() => {
  getWarehouses().then(r => setWarehouses(r.warehouses));
}, []);

// Correct
const { warehouses } = useWarehouse();
```

### Mistake: Using backend status string in JSX comparisons

```javascript
// Wrong — silent bug if backend capitalisation changes
order.status === 'Dispatch Ready'

// Correct
backendToFrontendStatus(order.status) === 'dispatch-ready'
```

### Mistake: Two `FileUploadForm` components with the same `inputId`

```javascript
// Wrong — clicking Browse on one page triggers both inputs
<FileUploadForm inputId="file-upload" ... />  // on OrderUpload
<FileUploadForm inputId="file-upload" ... />  // on InvoiceUpload

// Correct — unique ids
<FileUploadForm inputId="order-file-upload" ... />
<FileUploadForm inputId="invoice-file-upload" ... />
```

### Mistake: Raw `axios` in upload forms

```javascript
// Wrong — skips auth interceptor, upload returns 401
const formData = new FormData();
formData.append('file', file);
axios.post(`${config.API_SERVER}orders/upload`, formData);

// Correct
import api from '../../services/api';
api.post('orders/upload', formData);
```

### Mistake: Using `warehouse.id` instead of `warehouse.warehouse_id`

```javascript
// Wrong — 'id' does not exist on warehouse objects
params.append('warehouse_id', warehouse.id);

// Correct
params.append('warehouse_id', warehouse.warehouse_id ?? warehouse.id);
// Or when using context:
const { warehouse } = useWarehouse(); // warehouse is already the id string
params.append('warehouse_id', warehouse);
```

### Mistake: Hardcoding `localhost` URLs in service functions

```javascript
// Wrong — breaks in staging/production
api.get('http://localhost:5000/api/orders');

// Correct — api.js baseURL comes from config.js
api.get('orders');
```

### Mistake: Adding `Authorization` header manually in components

```javascript
// Wrong — duplicates interceptor logic, won't update when token rotates
headers: { Authorization: `Bearer ${localStorage.getItem('wms_token')}` }

// Correct — api.js interceptor does this automatically
api.get('orders'); // header injected transparently
```

---

## 13. Prompts for AI-Assisted Development

Use these prompts when asking an AI assistant to generate code in this codebase. They provide enough context for correct output on the first try.

### Adding a new service function

> "In this WMS React app, add a new function `cancelOrder(orderId, reason)` to `services/orderService.js`. The function must:
> - Use the shared `api` instance from `services/api.js` (not raw axios)
> - POST to `orders/<orderId>/cancel` with body `{ reason }` (relative path, no /api/ prefix)
> - Return the full axios response (not .data)
> - Be a named export (not default)
> The API server base URL is in `config.API_SERVER` and is already set as the axios baseURL."

### Adding a new upload page

> "In this WMS React app, add a new upload page `views/warehouse/NewTypeUpload.js`. It must:
> - Be a thin wrapper around `components/FileUploadForm/index.js` — do not duplicate upload logic
> - Use endpoint `new-type/upload` (relative, no /api/ prefix)
> - Require both warehouse and company selectors (requiresWarehouse=true, requiresCompany=true)
> - Accept .csv, .xls, .xlsx up to 10MB
> - Use a unique inputId `new-type-file-upload`
> - Display a `computeExtraStats` function that reads `data.created` and `data.error_count`
> Warehouse/company state comes from `useWarehouse()` hook — do not add local state for them."

### Adding a status chip for a new status

> "In this WMS React app, add a new order status `on-hold`. Update:
> 1. `views/warehouse/constants/statuses.js` — add to STATUS_LABELS, STATUS_FILTER_OPTIONS, FRONTEND_TO_BACKEND_STATUS, BACKEND_TO_FRONTEND_STATUS, STATUS_PROGRESSION (terminal state, value: null), ORDER_STATUS_DATA (with IconPause from @tabler/icons, color #757575, chipClass 'chipOnHold')
> 2. `makeStyles` in `WarehouseDashboard.js` and `OrderManagement.js` — add `chipOnHold: { backgroundColor: '#757575', color: 'white' }`
> 3. `views/warehouse/utils/index.js` — `getStatusChipClass` must return `'chipOnHold'` for slug `'on-hold'`
> Frontend slug: `'on-hold'`. Backend string: `'On Hold'`."

### Adding a new component

> "In this WMS React app, add a new component `views/warehouse/components/SummaryBanner.js`. It must:
> - Accept props: `title` (string), `value` (number), `color` (string), `classes` (makeStyles object)
> - Use `makeStyles` from `@material-ui/styles` for its own styles
> - Use Material-UI v4 components only (`@material-ui/core`)
> - Not use inline `style={{}}` for variant-driven colors (use makeStyles class names)
> - Be a named default export
> - Not use TypeScript — this codebase is plain JavaScript"

### Debugging a missing auth header

> "In this WMS React app, an API call is returning 401. The call uses raw axios instead of the shared api instance. Fix it by:
> 1. Removing the `import axios` and replacing with `import api from '../../services/api'`
> 2. Replacing `axios.get(config.API_SERVER + 'endpoint')` with `api.get('endpoint')`
> 3. Removing any manual `Authorization` header — the api.js interceptor adds `Bearer <token>` automatically from localStorage key `wms_token`"
