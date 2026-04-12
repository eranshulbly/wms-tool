# WMS Tool — Project Context & Architecture

> Generated: 2026-04-12. Re-read key files and update as the codebase evolves.

---

## Overview

A **Warehouse Management System (WMS)** full-stack web app:
- **Backend**: Python / Flask + Flask-RESTX, direct MySQL via PyMySQL (no ORM)
- **Frontend**: React (CRA), Material-UI v4, Redux for state, Axios for HTTP, Formik + Yup for forms
- **DB**: MySQL with custom range-column partitioning on date columns for performance

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask, Flask-RESTX, PyMySQL, Werkzeug, Pandas, openpyxl, Pillow |
| Frontend | React 17, Material-UI v4, Redux, Formik, Yup, Axios, @tabler/icons |
| Database | MySQL (partitioned), manual connection pool |
| Auth | Custom JWT via PyJWT, token blocklist in DB |

---

## Directory Structure

```
wms-tool/
├── api-server-flask/
│   ├── api/
│   │   ├── __init__.py          — Flask app factory
│   │   ├── config.py            — Env-based config (Dev/Staging/Prod)
│   │   ├── models.py            — MySQL model classes (Users, Orders, Invoices, etc.)
│   │   ├── db_manager.py        — MySQLManager, connection pool, partition_filter()
│   │   ├── routes.py            — Main REST API (orders, auth, uploads)
│   │   ├── auth_routes.py       — Alternate auth API (/api/auth/*)
│   │   ├── dashboard_routes.py  — Dashboard, warehouses, companies, orders list
│   │   ├── admin_routes.py      — Admin: upload batch management and deletion
│   │   ├── eway_bill_routes.py  — E-way bill: routes, customer mappings, manifests
│   │   ├── permissions.py       — DB-driven RBAC (roles, order_states, uploads)
│   │   ├── partition_manager.py — MySQL partition management utilities
│   │   ├── business/
│   │   │   ├── order_business.py   — Order upload processing, bulk status update
│   │   │   ├── invoice_business.py — Invoice upload processing, state transitions
│   │   │   └── dealer_business.py  — Dealer lookup/create with cache
│   │   ├── services/
│   │   │   ├── order_service.py    — File validation, temp file handling, batch creation
│   │   │   └── invoice_service.py  — File validation, temp file handling for invoices
│   │   └── utils/
│   │       └── upload_utils.py     — File save/read/cleanup, column resolution, response builder
│   └── run.py / gunicorn-cfg.py
│
└── react-ui/src/
    ├── config.js                — API_SERVER URL, app metadata
    ├── store/
    │   ├── accountReducer.js    — JWT token + user in localStorage/Redux
    │   └── customizationReducer.js
    ├── services/
    │   ├── orderManagementService.js — Order CRUD API calls (uses REACT_APP_API_URL)
    │   ├── dashboardService.js       — Dashboard API calls (uses config.API_SERVER)
    │   ├── adminService.js           — Admin upload batch calls
    │   └── orderService.js           — Order upload/download
    ├── views/warehouse/
    │   ├── OrderManagement.js        — Main order management page
    │   ├── WarehouseDashboard.js     — Dashboard with status counts
    │   ├── InvoiceUpload.js          — Invoice file upload UI
    │   ├── OrderUpload.js            — Order file upload UI
    │   ├── EwayBillGenerator.js      — E-way bill generator
    │   ├── components/
    │   │   ├── orderManagement.components.js    — Table, filters, dialogs
    │   │   └── warehouseDashboard.components.js — Status cards, filters
    │   ├── constants/               — Status labels, column defs, status data
    │   ├── styles/                  — makeStyles per page
    │   └── utils/                   — formatDate, getTimeInStatus, etc.
    ├── views/admin/
    │   └── AdminControls.js         — Admin batch delete UI
    ├── views/pages/authentication/
    │   └── login/RestLogin.js       — Formik login form → /api/users/login
    ├── utils/route-guard/
    │   ├── AuthGuard.js             — Checks isLoggedIn, blocks pending users
    │   ├── AdminGuard.js            — Checks role === 'admin'
    │   └── EwayFillingGuard.js      — Checks eway_bill_filling permission
    └── layout/MainLayout/index.js   — App shell with sidebar + topbar
```

---

## Data Model (Key Tables)

```
users                       — id, username, email, password(hashed), jwt_auth_active, status, role
roles                       — role_id, name, all_warehouses, eway_bill_admin, eway_bill_filling
role_order_states           — role_id, state_name
role_uploads                — role_id, upload_type
user_warehouse_company      — user_id, warehouse_id, company_id

warehouse                   — warehouse_id, name, location
company                     — company_id, name
dealer                      — dealer_id, name, dealer_code

potential_order             — potential_order_id, original_order_id, status, warehouse_id,
                              company_id, dealer_id, box_count, invoice_submitted,
                              upload_batch_id, created_at [PARTITIONED]
potential_order_product     — potential_order_product_id, potential_order_id, product_id,
                              quantity, quantity_packed, created_at [PARTITIONED]
order_state_history         — id, potential_order_id, state_id, changed_by, changed_at [PARTITIONED]
order_state                 — state_id, state_name, description

order                       — order_id, potential_order_id, order_number, status,
                              box_count, dispatched_date, created_at [PARTITIONED]
order_box                   — id, order_id, name, created_at [PARTITIONED]
order_product               — id, order_id, product_id, quantity, created_at [PARTITIONED]
box_product                 — id, box_id, product_id, potential_order_id, quantity, created_at [PARTITIONED]

invoice                     — invoice_id, invoice_number, original_order_id, potential_order_id,
                              warehouse_id, company_id, dealer_id, invoice_date, total_invoice_amount,
                              upload_batch_id, created_at [PARTITIONED]
upload_batches              — id, upload_type, filename, record_count, status, warehouse_id,
                              company_id, uploaded_by, uploaded_at [PARTITIONED]
jwt_token_blocklist         — id, jwt_token, created_at [PARTITIONED]

transport_routes            — route_id, name, description
customer_route_mappings     — mapping_id, dealer_id, route_id, distance
daily_route_manifests       — manifest_id, route_id, manifest_date, data (JSON)
invoice_processing_config   — id, order_type, is_bypass_enabled
```

---

## Order Lifecycle (State Machine)

```
Upload → Open → Picking → Packed → Invoiced → Dispatch Ready → Completed
                                ↑
                         (bypass types: Open/Picking can skip to Invoiced directly)
                         (invoice_submitted flag: invoice arrives before Packed)
```

**State transition rules:**
1. `Open → Picking` — manual, via Order Management UI or bulk upload
2. `Picking → Packed` — manual, requires box count; or via bulk upload file
3. `Packed → Invoiced` — triggered by invoice file upload; creates `Order` record
4. `Open/Picking → Invoiced` (bypass) — bypass order types (e.g. ZGOI) skip Packed
5. `invoice_submitted` flag — invoice arrives while order is Open/Picking; auto-transitions to Invoiced when Packed
6. `Invoiced → Dispatch Ready` — created by `MoveToInvoiced` endpoint (`/api/orders/<id>/move-to-invoiced`)
7. `Dispatch Ready → Completed` — `CompleteDispatch` endpoint (`/api/orders/<id>/complete-dispatch`)
8. `Packed → Partially Completed` — `OrderDispatchFinal` endpoint if some products remain

---

## Authentication Flow

1. User POSTs credentials to `/api/users/login` (routes.py) or `/api/auth/login` (auth_routes.py)
2. Backend issues JWT with `exp` and stores `jwt_auth_active=True` on user
3. Token stored in `localStorage` (`wms_token`, `wms_user`) and Redux state
4. `@token_required` decorator on every protected endpoint reads `Authorization` header, decodes JWT, checks blocklist
5. Logout: token added to `jwt_token_blocklist`, `jwt_auth_active` set to False
6. `@active_required` — blocks pending users (status='pending') with 403
7. `@upload_permission_required(type)` — checks role's upload permissions from DB
8. `@_admin_required` — checks role === 'admin'

**Warning:** Two separate JWT secrets (`SECRET_KEY` vs `JWT_SECRET_KEY`) exist; tokens from one system cannot be verified by the other.

---

## Role-Based Permissions

Stored in DB, managed via Flask-Admin:
- `roles.all_warehouses` — can access all warehouses (admin/manager)
- `roles.eway_bill_admin/eway_bill_filling` — e-way bill permissions
- `role_order_states` — which statuses this role can see/manage
- `role_uploads` — which upload types (orders/invoices) this role can perform
- `user_warehouse_company` — per-user warehouse+company access list

---

## Partitioning Strategy

10 tables are partitioned by `RANGE COLUMNS` on their date column. `PARTITION_WINDOW_MONTHS = 4` — queries via `partition_filter()` only look at the last 4 months. **Orders older than 4 months become invisible to all queries.**

---

## Key Configuration

| Env Var | Default | Used for |
|---|---|---|
| SECRET_KEY | random (regenerated each restart!) | JWT signing in routes.py |
| JWT_SECRET_KEY | random (regenerated each restart!) | JWT signing in auth_routes.py |
| DB_HOST/PORT/USERNAME/PASS/NAME | localhost/3306/root/root-pw/warehouse_management | MySQL |
| APP_ENV | production | Config class selection |
| REACT_APP_API_URL | http://localhost:5000 | orderManagementService base URL |
| REACT_APP_BACKEND_SERVER | http://localhost:5000/api/ | config.js API_SERVER |
