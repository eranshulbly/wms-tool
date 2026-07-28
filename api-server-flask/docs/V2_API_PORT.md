# Porting the wms-v2-backend API into this backend — schema changes & mapping

**Status: IMPLEMENTED (rev 3).** All 34 API endpoints are live at `/api/v1/*` and
verified end-to-end. Two deviations were forced by the existing schema:

1. `potential_order` is RANGE-partitioned by `created_at`, and MySQL requires a UNIQUE
   index to include every partitioning column — so `order_number` uses a plain index.
   It is unique by construction (`ORD-{order_id:06d}`, derived from the auto-increment PK).
2. `potential_order.original_order_id` is NOT NULL with no default (it carries the source
   id for web uploads). App-created orders have no external id, so it is set to the
   generated order number.

## Why
An Android app is built against `wms-v2-backend` (FastAPI + Postgres) — 37 endpoints under
`/api/v1/*`. This backend (Flask + MySQL, the live web app) must serve those same endpoints
so it powers the Android app too, from **one** codebase, **one** auth model, and **one**
order lifecycle.

## Constraints
- Adapt onto the existing v1 MySQL schema; **additive changes only** (nothing renamed or
  dropped) so the live web app keeps working.
- All 37 endpoints, **full business logic** (inventory ledger with row locks + idempotency,
  order approve→picklist via events, fulfillment sync-back).
- **One auth system** shared by the web UI and the Android app (upgrade, don't fork).
- **One order lifecycle** shared by both channels.
- Fresh — no data migration from v2 Postgres; this backend is the source of truth.
- New routes keep the exact v2 paths `/api/v1/*`, alongside the existing `/api/*` web routes.
  Each v2 module maps to the same-named module here (`auth→user_auth`, `catalog`, `order`,
  `inventory`, `assignment`), each getting a `router_v1.py`.

---

## Decision 1 — Unified order lifecycle (one `status` column)
There is **no** separate app status. The v2 entry states are *prepended* to the existing
warehouse chain, so an app order flows into the normal warehouse process:

```
app-created:  submitted → approved → Open → Picking → Packed → Invoiced → Dispatch Ready → Completed
web-uploaded:                        Open → Picking → Packed → Invoiced → Dispatch Ready → Completed
rejected:     submitted → rejected   (terminal)
```

- Orders uploaded from the current web UI still start at **Open** — unchanged behaviour.
- Orders created by the app (`POST /api/v1/orders`) start at **submitted**.
- `POST /api/v1/orders/{id}/approve` → **approved** (and generates the picklist).
- **approved → Open** is a normal state transition, so an approved app order shows up in the
  web Manage-Orders screen as the next thing to action, then follows the existing flow.
- `POST /api/v1/orders/{id}/reject` → **rejected** (terminal).

Implementation: add `submitted`, `approved`, `rejected` rows to the existing `order_state`
table and extend `modules/order/state_machine.py` with the new transitions
(`submitted→approved|rejected`, `approved→Open`). Everything downstream of `Open` is untouched.

> Note on the app's view: v2's `fulfilled` / `partially_fulfilled` are **not** introduced as
> new statuses. Picklist completion advances the order along the existing chain
> (`Picking → Packed`) and still syncs `quantity_fulfilled` onto the order lines, which is
> what the app reads per item.

## Decision 2 — Unified auth: upgrade to real RBAC (shared by web + app)
The current model is one role string per user plus boolean flags. It is upgraded in place to
a proper permission model so **one** auth serves both clients and a user can hold **several
roles** (e.g. "mobile app manager" *and* "web manager"), with effective permissions = the
**union** across their roles.

- New tables: `permissions` (codes), `role_permissions` (M2M), `user_roles` (M2M).
- The existing `roles` table is kept (its flags stay for now); `users.role` is **kept and
  still written** for backward compatibility, and every existing user is seeded into
  `user_roles` from it — so current web behaviour is preserved on day one.
- Permission codes are the **union** of the v2 set and the web app's existing concepts, so a
  single vocabulary drives both surfaces:
  - v2 (19): `user:read|manage`, `dealer:read|manage`, `catalog:read|manage`,
    `order:read|write|approve`, `inventory:read|pick|pack|stack|putaway|move`,
    `assignment:read|manage`, `report:view`, `warehouse:all`
  - web-specific (added): `eway:fill`, `eway:admin`, `supply_sheet:view`,
    `upload:orders|invoices|products`, plus per-state visibility retained via the existing
    `role_order_states` table.
- `api/modules/user_auth/permissions.py` resolves effective permissions from the new tables,
  **falling back to the legacy role flags** when a role has no explicit permission rows — so
  nothing breaks mid-migration. Both the web decorators and the `/api/v1` permission checks
  read this one resolver.
- Tokens: both logins issue the same claim shape (`sub`, `type`, `perms`, `iat`, `exp`), signed
  with the existing secret. `/api/v1/auth/login` additionally returns a rotating refresh token
  (new `refresh_tokens` table); the existing web login keeps working as-is and simply gains the
  `perms` claim.

---

## Schema changes

### New tables (5)
```sql
-- ── auth/RBAC upgrade ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS permissions (
    permission_id INT AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(100) NOT NULL UNIQUE,     -- e.g. 'order:approve'
    description   VARCHAR(255) NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id)
);

-- a user may hold several roles (web role + mobile role)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     INT NOT NULL,
    role_id     INT NOT NULL,
    assigned_by INT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  VARCHAR(255) NOT NULL UNIQUE,       -- sha256 hex of the raw refresh JWT
    expires_at  DATETIME NOT NULL,
    revoked_at  DATETIME NULL,
    user_agent  VARCHAR(255) NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_refresh_user (user_id)
);

-- ── catalog ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    parent_id   INT NULL,
    description VARCHAR(255) NULL,
    is_active   TINYINT(1) NOT NULL DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_categories_parent (parent_id)
);
```

### Altered tables (additive only)
```sql
-- catalog SKUs: a v2 "SKU" is a v1 product; sku_code == product.product_string
ALTER TABLE product
    ADD COLUMN nickname    VARCHAR(200) NULL,     -- skip if migration_product_nickname.sql already applied
    ADD COLUMN category_id INT NULL,
    ADD COLUMN uom         VARCHAR(20) NULL,
    ADD COLUMN size        VARCHAR(100) NULL,
    ADD COLUMN weight      DECIMAL(10,3) NULL,
    ADD COLUMN barcode     VARCHAR(100) NULL,
    ADD COLUMN hsn_code    VARCHAR(20) NULL,
    ADD COLUMN is_active   TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE product ADD UNIQUE INDEX uq_product_string (product_string);  -- sku_code identity
ALTER TABLE product ADD UNIQUE INDEX uq_product_barcode (barcode);
-- (verified safe: product table is currently empty, no duplicate product_string)

ALTER TABLE dealer
    ADD COLUMN email   VARCHAR(255) NULL,
    ADD COLUMN phone   VARCHAR(32) NULL,
    ADD COLUMN town    VARCHAR(100) NULL,          -- skip if the town migration is already applied
    ADD COLUMN address TEXT NULL,
    ADD COLUMN gstin   VARCHAR(20) NULL,
    ADD COLUMN status  VARCHAR(20) NOT NULL DEFAULT 'active';

ALTER TABLE warehouse
    ADD COLUMN code      VARCHAR(20) NULL,
    ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE warehouse ADD UNIQUE INDEX uq_warehouse_code (code);
UPDATE warehouse SET code = CONCAT('WH', warehouse_id) WHERE code IS NULL;  -- backfill

-- orders: v2 fields on the existing order table (ONE lifecycle, no extra status column)
ALTER TABLE potential_order
    ADD COLUMN order_number           VARCHAR(50) NULL,
    ADD COLUMN created_by             INT NULL,
    ADD COLUMN approved_by            INT NULL,
    ADD COLUMN approved_at            DATETIME NULL,
    ADD COLUMN rejection_reason       VARCHAR(255) NULL,
    ADD COLUMN submitted_at           DATETIME NULL,
    ADD COLUMN expected_delivery_date DATE NULL,
    ADD COLUMN notes                  TEXT NULL;
ALTER TABLE potential_order ADD UNIQUE INDEX uq_po_order_number (order_number);

-- order lines: v2 snapshots sku_code/name/uom and tracks fulfillment per line
ALTER TABLE potential_order_product
    ADD COLUMN sku_code           VARCHAR(100) NULL,
    ADD COLUMN product_name       VARCHAR(255) NULL,
    ADD COLUMN uom                VARCHAR(20) NULL,
    ADD COLUMN quantity_fulfilled INT NULL,
    ADD COLUMN item_status        VARCHAR(30) NOT NULL DEFAULT 'pending';
```

### Seed data (not schema)
- `order_state`: add `submitted`, `approved`, `rejected`.
- `permissions`: insert the full code vocabulary; `role_permissions`: seed each existing role
  from its current flags/uploads so present behaviour is preserved; `user_roles`: one row per
  existing user from `users.role`.

### Unchanged
`stock`, `inventory_transactions`, `picklists`, `picklist_items`, `jobs`,
`worker_availability`, `allocation_policies` already exist and match v2 — the ledger and
picklist logic ports straight onto them.

---

## Per-endpoint mapping (v2 → v1 backing)

### user_auth `/api/v1/auth/*` → `modules/user_auth`
| Endpoint | Backed by | Notes |
|---|---|---|
| POST /login | `users`, `refresh_tokens` | username+password; `perms` from unified RBAC |
| POST /refresh | `refresh_tokens` | rotate, single-use, sha256 lookup |
| GET /me | `users`, `user_roles`, `user_warehouse_company` | roles = all roles held |
| POST /users | `users`, `user_roles` | `role_names` → multiple `user_roles` rows |
| GET/POST /dealers | `dealer` (+ new cols) | list filters `status='active'` |

### catalog `/api/v1/catalog/*` → `modules/catalog`
| Endpoint | Backed by |
|---|---|
| GET/POST /categories | `categories` (new) |
| GET/POST /skus, GET/PATCH /skus/{sku_code} | `product` (+ new cols), `sku_code == product_string` |

### order `/api/v1/orders/*` → `modules/order`
| Endpoint | Backed by | Notes |
|---|---|---|
| POST / | `potential_order` + `potential_order_product` | status `submitted`, `ORD-######` |
| GET /list, /{id} | same | warehouse scoping from token perms |
| POST /{id}/approve | same + `picklists` | → `approved`, picklist in same txn, events |
| POST /{id}/reject | same | → `rejected` |
| GET /{id}/fulfillment | `stock` | on-hand vs requested |

### inventory `/api/v1/inventory/*` → `modules/inventory`
| Endpoint | Backed by | Notes |
|---|---|---|
| GET/POST /warehouses | `warehouse` (+ code, is_active) | |
| GET /stock, /stock/{wh}/{sku}, /transactions | `stock`, `inventory_transactions` | as-is |
| POST /stock/receive, /adjust | `_apply_movement` | ledger + `FOR UPDATE` lock + idempotency + below-zero reject |
| GET /picklists, /{id}; POST /generate, /{id}/complete | `picklists`, `picklist_items` | complete → stock draw-down + fulfillment sync + `PickingCompleted` |

### assignment `/api/v1/assignment` → `modules/assignment`
Status endpoint only.

All module-status GETs return `{"module": "...", "status": "ok"}`, unauthenticated.
Error→HTTP: 400 validation · 401 missing/invalid auth · 403 missing permission · 404 not found
· 409 conflict / invalid transition / insufficient stock · 422 request-schema violation.

---

## Implementation order
1. `migration_v2_api.sql` — the new tables + ALTERs + seeds above (idempotent).
2. Auth/RBAC upgrade: permission resolver (new tables, legacy fallback), token `perms` claim,
   refresh tokens, `require_permission` usable by both web and `/api/v1`.
3. Order lifecycle: new states + state-machine transitions.
4. `router_v1.py` per module + the ported service logic.
5. Verify: full smoke of all 37 endpoints + regression of the existing web flows.

## Risks / call-outs
- The auth upgrade touches the **live** web app's permission checks — mitigated by seeding
  `role_permissions` from current flags and keeping a legacy fallback, then regression-testing
  the web UI.
- Making `product_string` unique is safe today (table empty); if products are loaded before
  this ships, duplicates must be resolved first.
- The app will see warehouse-stage statuses (`Open`, `Picking`, …) once an order is approved —
  intended, since the lifecycle is now shared.
- Not doing: v2 Postgres data migration; the assignment engine (unbuilt in v2 too);
  location-level `fc_*` inventory (backs none of the 37 endpoints).
