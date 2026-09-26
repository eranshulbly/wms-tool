# Packing app — screen-by-screen API contracts and table impact (v2)

Companion to [`PACKING_DESIGN.md`](./PACKING_DESIGN.md). That document argues the design;
this one is the build reference for the Android client (`wms-app`) and the backend.

For every screen: which endpoints it calls, in what order, the exact request and response
contract, whether the endpoint **already exists** or must be **built**, and precisely which
tables and which rows each call reads, inserts or updates.

**v2 supersedes v1.** Packing owns no tables. Everything runs on `entity_movement_request` +
`entity_movement_details`, the same engine picking and stacking use.

Existing contracts below were read out of the running code, not assumed.

---

## 0. Conventions that apply to every call

**Base URL** `https://<host>` · all packing endpoints under `/api/v1/packing/`.

**Auth** every endpoint except `POST /auth/login` and `POST /auth/refresh` requires
`Authorization: Bearer <access_token>`. Access TTL 60 min, refresh 14 days, single-use and
rotating (`modules/platform/user_auth/tokens.py`).

**Permission** every `/api/v1/packing/*` endpoint requires `inventory:pack`
(`rbac.P.INVENTORY_PACK`). The code exists; it is granted to no role yet. A `packer` role
must be created and granted it before the app can be used at all.

**Company scoping** `shared/auth_v1.py::company_filter`. Both `entity_movement_request` and
`entity_movement_details` already carry `company_id`. `company_ids = null` means unscoped;
`[]` means scoped-but-granted-nothing and must match zero rows, never everything.

**Errors** all `/api/v1/*` errors are `{"detail": "<sentence>"}`, enforced globally in
`api/__init__.py`. Packing adds a machine-readable `code` on business rejections. The app
switches on `code` and displays `detail`.

**Idempotency** every packing write accepts `Idempotency-Key: <uuid>`, generated once per
intent and reused on every retry.

> **Cross-cutting table impact — stated once, not repeated per endpoint.** Any write
> carrying `Idempotency-Key` performs `idempotency_keys` INSERT (claim) → UPDATE (store
> response) → DELETE (release on failure). A replayed key returns the stored response and
> touches nothing else.

> **Cross-cutting partition rule — stated once.** Every UPDATE against
> `entity_movement_request` / `entity_movement_details` must carry `created_on` in its
> WHERE clause, or MySQL probes all ~13 monthly partitions. The service holds each row's
> `created_on` in memory after insert and passes it on every update. See `PACKING_DESIGN.md`
> §6.3 — including the one-line `PARTITION_COLUMN` fix this depends on.

**Timestamps** every write carries a device-clock timestamp; the server records its own
`created_on` separately. The app sends local device time, ISO-8601 with milliseconds, and
does not attempt to correct for clock skew.

**Vocabulary on the wire.** The API speaks `sku_code` (= `product.product_string`); the
service translates to `product_id` at the boundary — the same rule the GRN design set.
Wire names are deliberately readable and do **not** mirror column names:

| Wire field | Column |
|---|---|
| `box_id` | `entity_movement_details.id` (box row) |
| `label_code` | `entity_movement_details.entity_id` (box row) |
| `tare_kg` | `tare_weight_kg` |
| `sealed_kg` | `weight_kg` |
| `expected_kg` | `expected_weight_kg` |
| `variance_g` | `variance_g` |

**Legend** `R` read · `I` insert · `U` update. **No packing endpoint deletes anything.**

---

## 1. Endpoint inventory

### Already exists — no backend work

| Endpoint | Screen |
|---|---|
| `POST /api/v1/auth/login` | 1 |
| `POST /api/v1/auth/refresh` | background |
| `POST /api/v1/auth/logout` | 15 |
| `GET /api/v1/auth/me` | 1 |
| `GET /api/v1/companies` | 2 |

### To be built — 12 endpoints

| Endpoint | Screen |
|---|---|
| `GET /api/v1/packing/config` | 3 |
| `GET /api/v1/packing/picklists` | 4, 5 |
| `GET /api/v1/packing/picklists/{potential_order_id}` | 5 |
| `GET /api/v1/packing/short-reasons` | 12 |
| `POST /api/v1/packing/jobs` | 6 |
| `GET /api/v1/packing/jobs/{request_id}` | 16 |
| `POST /api/v1/packing/jobs/{request_id}/boxes` | 6 |
| `POST /api/v1/packing/boxes/{box_id}/bind` | 7 |
| `POST /api/v1/packing/boxes/{box_id}/scans` | 8 |
| `POST /api/v1/packing/jobs/{request_id}/cartons` | 8b |
| `POST /api/v1/packing/boxes/{box_id}/close` | 9 |
| `POST /api/v1/packing/boxes/{box_id}/abandon` | 14 |
| `POST /api/v1/packing/jobs/{request_id}/save` | 11 |
| `POST /api/v1/packing/jobs/{request_id}/submit` | 12 |

**Dropped from v1 of this document:** `GET /packing/stations` (no station table — pairing is
OS-level device bonding) and `POST /packing/dispatch/scan` (dispatch is a read against the
order's box rows, and is not built in v1 — `PACKING_DESIGN.md` §7).

---

## SCREEN 1 — Login

### 1.1 `POST /api/v1/auth/login` — **EXISTING**

No auth. Note the field-name quirk: the endpoint accepts `email` **or** `username` as the
key, but the lookup is on **email** either way. Send `email`.

```jsonc
// Request
{ "email": "rahul.k@warehub.in", "password": "••••••••" }

// 200
{ "access_token": "eyJ…", "refresh_token": "eyJ…", "token_type": "bearer" }

// 401 { "detail": "Invalid email or password" } | { "detail": "Account is disabled" }
// 422 { "detail": "email and password are required" }
```

| Table | Op | What |
|---|---|---|
| `users` | R | email lookup, password hash, status |
| `user_roles`, `roles`, `role_permissions`, `permissions` | R | permission codes baked into the access token |
| `role_uploads` | R | legacy fallback only, for users with no RBAC rows |
| `refresh_tokens` | **I** | one row per login |

> The demo's "Packer ID + PIN" is not what this backend authenticates — `PACKING_DESIGN.md`
> §9 Q3.

### 1.2 `GET /api/v1/auth/me` — **EXISTING**

```jsonc
// 200
{ "user_id": 42, "username": "Rahul K.",
  "permissions": ["inventory:pack", "inventory:read", "order:read"],
  "roles": ["packer"],
  "warehouse_ids": [1], "has_all_warehouses": false,
  "company_ids": [3, 7], "has_all_companies": false }
```

| Table | Op |
|---|---|
| `users`, `user_roles`, `roles`, `role_permissions`, `permissions`, `user_warehouse_company` | R |

**Client rule:** if `inventory:pack` is absent, render the Packing tile disabled. Do not
discover this by calling a packing endpoint and handling 403.

---

## SCREEN 2 — Company select

### 2.1 `GET /api/v1/companies` — **EXISTING**

Returns a **bare JSON array**, not an envelope.

```jsonc
// 200
[ { "company_id": 3, "name": "Hero MotoCorp",
    "order_capture_mode": "itemised", "analytics_mode": "targets",
    "catalog_label_mode": "code_first" } ]
```

| Table | Op |
|---|---|
| `company` | R |
| `user_warehouse_company` | R — scope |
| `user_roles`…`permissions` | R — `company:all` short-circuit |

**Client rule:** with exactly one entry, skip this screen. The demo's three companies are
mock data.

**Gap:** no warehouse or location in this response, but the card shows one and every packing
endpoint needs `warehouse_id` — `PACKING_DESIGN.md` §9 Q4.

---

## SCREEN 3 — Bootstrap (invisible, on entering Packing)

### 3.1 `GET /api/v1/packing/config?warehouse_id=1` — **NEW**

Every operational threshold, read from **app config (env)**, not from a table — so tuning
tolerance is a config redeploy, not a schema change or an APK release.

```jsonc
// 200
{ "warehouse_id": 1,
  "tolerance_g": 50,
  "gross_overage_multiplier": 2.0,     // freeze mid-scan past expected + 2x heaviest SKU
  "settle_window_ms": 1000,
  "weight_verify_floor_g": 30,         // applied to quantity x unit weight PER SCAN
  "scan_batch_size": 20,               // flush after N scans...
  "scan_flush_ms": 4000,               // ...or T ms, whichever first
  "max_boxes_per_picklist": 50,

  // Audible feedback. Floors differ — a tone that carries in one warehouse is
  // inaudible in the next — so these are served, not baked into the APK.
  // Cue design and the rhythm-not-pitch rule: PACKING_DESIGN.md §6.9.
  "alert_volume": 1.0,                 // 0..1, applied to the fraud-lock alert
  "alert_repeat_ms": 1500,             // the lock re-sounds until weight is back in tolerance

  // How this company's scanned codes decode. Served, never compiled into the app,
  // so a new company or a changed layout is a config push. See PACKING_DESIGN.md §6.7.
  "barcode_format": {
    "delimiter": "/",
    "field_count": 11,
    "trim_fields": true,               // NOT fixed-width: pad and length both vary
    "product_field": 4,                // "14610086000RS"  — printed part number
    "quantity_field": 5,               // "000200"         — NET QUANTITY, already base units
    "upi_field": 3,                    // "DCGKM4WNNA4Z"   — Hero anti-counterfeit code
    "serial_field": 2,                 // "KH6G0000000344" — not printed; unconfirmed
    "batch_field": 7,                  // "ABF"            — B. NO. on the label
    "mrp_field": 6 } }                 // "0095.00"        — MRP, varies BY BATCH
```

| Table | Op |
|---|---|
| — | none. Serves config constants. |

**`barcode_format` is served rather than built in** because Hero, Castrol, Ebco and Cadila will
not share a layout, and because the app and the server must decode identically — the app for
its live weight display, the server for the quantity it will actually trust.

**`scan_batch_size` / `scan_flush_ms` are served, not hardcoded**, so the batching window
can be tuned against real load without an app release. See §8.1 for why batching is
load-bearing.

---

## SCREEN 4 — Home / module tiles

### 4.1 `GET /api/v1/packing/picklists?warehouse_id=1&limit=1` — **NEW**

Only `total` is used, for the tile's count badge.

| Table | Op |
|---|---|
| `potential_order` | R — count where `status='Picking'`, company + warehouse scoped |

**Client rule:** GRN / Stacking / Picking / RTV tiles are inert. Call nothing for them.

---

## SCREEN 5 — Picklist pool (list + search)

### 5.1 `GET /api/v1/packing/picklists` — **NEW**

Query: `warehouse_id` (required), `q` (matches display id or merchant), `limit` (default 50),
`offset`.

```jsonc
// 200
{ "items": [
  { "potential_order_id": 4821, "display_id": "PL-4821",
    "merchant": "Hero Dealer · Jaipur", "company_id": 3, "warehouse_id": 1,
    "sku_count": 3, "total_units": 18,
    "estimated_weight_kg": 4.480, "default_box_tare_kg": 0.400,
    "state": "pending",                // pending | resume
    "packed_units": 0,
    "request_id": null,                // the packing job, when one exists
    "boxes_sealed": 0,
    "weight_verifiable": true,         // false if any line has no usable unit weight
    "order_date": "2026-08-16T06:12:00" } ],
  "total": 3 }
```

| Table | Op | What |
|---|---|---|
| `potential_order` | R | pool: `status='Picking'`, company + warehouse scoped |
| `potential_order_product` | R | `sku_count`, `total_units` |
| `product` | R | `weight` → `estimated_weight_kg`, `weight_verifiable` |
| `dealer` | R | `merchant` |
| `entity_movement_request` | R | existing packing job → `state`, `request_id`, `packed_units` from `metadata.totals` |
| `entity_movement_details` | R | `boxes_sealed` (`entity_type='box'`) |
| `user_warehouse_company` | R | scope |

**Writes: none.**

**Search is server-side.** The pool is shared and self-serve; a stale local copy filtered on
the device sends two packers at the same picklist. `estimated_weight_kg` is computed here
too, so there is one definition of the arithmetic the fraud check later depends on.

### 5.2 `GET /api/v1/packing/picklists/{potential_order_id}` — **NEW**

Tapped card, **before** starting the job — the pre-flight read.

```jsonc
// 200
{ "potential_order_id": 4821, "display_id": "PL-4821",
  "merchant": "Hero Dealer · Jaipur", "company_id": 3, "warehouse_id": 1,
  "status": "Picking", "default_box_tare_kg": 0.400, "tolerance_g": 50,
  "items": [
    { "sku_code": "SKU-H1180", "product_id": 90114, "name": "Brake pad set",
      "barcode": "8901234500011", "unit_weight_kg": 0.620,
      "quantity_required": 4, "quantity_packed": 0, "quantity_remaining": 4,
      "weight_verifiable": true } ],
  "job": null,
  "boxes": [] }
```

On a resumable picklist:

```jsonc
  "job": { "request_id": 7701, "request_status": "saved", "box_seq": 1,
           "packed_units": 7, "total_units": 18, "tolerance_g": 50,
           "last_packer": "Rahul K.", "updated_on": "2026-08-16T08:22:11" },
  "boxes": [ { "box_id": 8801, "box_no": 1, "label_code": "WH1-000148212",
               "status": "sealed", "sealed_kg": 2.884, "expected_kg": 2.880,
               "variance_g": 4, "units": 7, "sealed_at": "2026-08-16T08:21:40" } ]
```

| Table | Op |
|---|---|
| `potential_order`, `potential_order_product`, `product`, `dealer` | R |
| `entity_movement_request` | R — the job + its `metadata` JSON |
| `entity_movement_details` | R — box rows and their `source_stock_info` JSON |

**Writes: none.**

**404** if the order is not `Picking`, or is outside the caller's scope — same body either
way, so the endpoint cannot be used to probe for other tenants' order ids.

---

## SCREEN 6 — Box setup step 1 (place empty box on scale)

Two calls: the packing job is created or resumed, then a box row is opened with its captured
tare. Separate because the job outlives every box.

### 6.1 `POST /api/v1/packing/jobs` — **NEW**

```jsonc
// Request        Idempotency-Key: <uuid>
{ "potential_order_id": 4821, "station": "TC21-07" }

// 200 — created or resumed, same shape
{ "request_id": 7701, "potential_order_id": 4821, "display_id": "PL-4821",
  "request_status": "in_progress", "resumed": true,
  "box_seq": 1, "tolerance_g": 50,
  "totals": { "required": 18, "packed": 7, "remaining": 11 },
  "items": [ { "sku_code": "SKU-H1180", "product_id": 90114,
               "unit_weight_kg": 0.620, "quantity_required": 4,
               "quantity_packed": 4, "quantity_remaining": 0,
               "weight_verifiable": true } ],
  "banner": "Resuming — 7 of 18 already packed. Fresh box for the rest." }

// 409 { "detail": "PL-4821 is already being packed by Anil S.", "code": "job_in_use" }
// 409 { "detail": "PL-4821 is no longer in Picking.", "code": "order_not_packable" }
```

| Table | Op | What |
|---|---|---|
| `potential_order` | R | status + scope check |
| `potential_order_product`, `product` | R | line snapshot, unit weights |
| `entity_movement_request` | R | existing job for this order? (`planogram_reqid_reftype` key) |
| `entity_movement_request` | **I** | first start — `movement_type='packing'`, `request_status='created'`, `request_identifier=<order_id>`, `reference_type='ORDER'`, `metadata` per `PACKING_DESIGN.md` §4.3 with `tolerance_g` snapshotted |
| `entity_movement_request` | **U** | resume — `request_status='in_progress'`, refresh `metadata`, `updated_by_id` |

**Concurrency.** Unlike v1 there is no unique key to race on — `entity_movement_request` has
no constraint preventing two packing jobs for one order. The service must therefore do a
`SELECT … FOR UPDATE` on the existing job (or claim via the order row) inside the
transaction before inserting. **Without that, two packers tapping the same card create two
jobs and both pack the same picklist.** This is the one place v2's table reuse costs
something real that v1's `UNIQUE(potential_order_id)` gave for free.

**Not written here:** no box row. A job with zero boxes is legitimate — the packer opened
the picklist and walked away.

### 6.2 `POST /api/v1/packing/jobs/{request_id}/boxes` — **NEW**

Fires when the empty box's weight settles. Setup step 1.

```jsonc
// Request        Idempotency-Key: <uuid>
{ "tare_kg": 0.402, "captured_at": "2026-08-16T09:38:02.140" }

// 201
{ "box_id": 8802, "box_no": 2, "request_id": 7701,
  "status": "setup", "tare_kg": 0.402,
  "next_step": "bind_label" }

// 409 { "detail": "Box 2 is still open. Close or abandon it first.", "code": "box_already_open" }
// 422 { "detail": "Empty box weight 0.040 kg is below the scale's 0.100 kg minimum.",
//       "code": "below_scale_minimum" }
```

| Table | Op | What |
|---|---|---|
| `entity_movement_request` | R | must be `created`/`in_progress`; read `metadata.box_seq` |
| `entity_movement_details` | R | reject if a `setup`/`open` box row already exists on this job |
| `entity_movement_details` | **I** | the **box row**: `entity_type='box'`, **`entity_id=''`** (the label arrives at bind), `source_bin_id=0`, `picked_quantity=0`, `source_location_id=6`, **`tare_weight_kg=0.400`**, `source_stock_info` = box JSON with `status:'setup'`, `box_no`, `weight_events:[{e:'tare'}]` |
| `entity_movement_request` | **U** | `metadata.box_seq += 1`, `request_status='in_progress'` |

**`box_no` is issued from `metadata.box_seq` inside the same transaction** — that is what
keeps numbering continuous across a save-and-resume (requirements §7).

**The insert's `lastrowid` is the box id.** The service keeps it *and* the row's `created_on`
in memory: every later update to this box needs both, or it scans all partitions.

---

## SCREEN 7 — Box setup step 2 (scan the pre-printed QR)

### 7.1 `POST /api/v1/packing/boxes/{box_id}/bind` — **NEW**

```jsonc
// Request        Idempotency-Key: <uuid>
{ "label_code": "WH1-000148213", "scanned_at": "2026-08-16T09:38:20.512" }

// 200
{ "box_id": 8802, "box_no": 2, "label_code": "WH1-000148213",
  "status": "open", "tare_kg": 0.402, "bound_at": "2026-08-16T09:38:20.512",
  "next_step": "pack" }

// 409 { "detail": "Label WH1-000148213 is already on a box for PL-4802.",
//       "code": "label_already_used" }
// 409 { "detail": "Capture the empty box weight first.", "code": "tare_missing" }
```

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | R | the box row — must be `status='setup'` with a non-null `tare_weight_kg` |
| `entity_movement_details` | R | **`WHERE entity_id = %s AND entity_type = 'box'`** — the single-use check, over `idx_emd_entity` |
| `entity_movement_details` | **U** | **`entity_id = 'WH1-000148213'`** (`''` → the label); `source_stock_info` → `status:'open'`, `bound_at` |

**The label is the box's `entity_id`** — no separate column. That is why `entity_id` is
`VARCHAR(64)`: these codes are alphanumeric and a `BIGINT` would not hold them
(`PACKING_DESIGN.md` §4.6).

**The setup order is enforced server-side**, not just by the UI: binding a box with no tare
is a 409. Requirements §5 fixes that order, and a client that got it backwards would produce
boxes whose expected weight has no baseline.

**The single-use check is an application check over an index, not a UNIQUE constraint** —
`entity_movement_details` is partitioned, so a global unique key on `entity_id` is impossible.
That is sufficient here: there is exactly one physical sticker, so two packers cannot bind it
simultaneously.

**The app never generates a code.** The demo's `QR-PL-4821-01-A7F2` is mock behaviour and
must not ship.

---

## SCREEN 8 — Active packing (the scan loop)

### 8.1 `POST /api/v1/packing/boxes/{box_id}/scans` — **NEW**

**Batched, and fire-and-forget.** The app appends each trigger pull to a durable local table
and flushes on `scan_batch_size` or `scan_flush_ms` (from §3.1). The UI updates from that
local table, never from this response — a packer must not wait on a round trip between
trigger pulls.

> **This endpoint is not the weight check.** The live red/green reconciliation runs **on the
> device**, against the Bluetooth scale stream, on every sample — because both inputs (the
> live weight and the unit weights from the job payload) are already there and the server has
> neither. A per-scan HTTP call cannot make that feedback arrive sooner: if the UI waits for
> it the packer is gated on network latency, and if the UI does not wait, the call was never
> part of the real-time loop. The authoritative, tamper-proof check is at close (§9.1).
> `PACKING_DESIGN.md` §6.2b works through the add-then-remove case and the full check-placement
> table.

**Flush weight anomalies immediately.** Ordinary scans wait for the batch window;
`excess_detected`, `excess_cleared` and `freeze` events should be flushed the moment they
occur, so ops sees a suspected sneak within a second rather than within a batch.

**Batching is load-bearing, not an optimisation.** One call per ack costs 7 auth queries
*before* the endpoint runs — 700 auth queries for a 100-unit picklist, ~70/sec across ten
packers, against a connection budget of 60. Batching at 20 takes that to 35.
`PACKING_DESIGN.md` §6.2 has the full sizing.

**Removing an item the packer did scan** is an explicit correction, not a re-scan: the app
sends `{"uid": …, "delta": -1, "sku_code": …}` and the server records `result: 'undo'`. Without
it the scan count and the weight diverge and the box can never close.

**The request carries the raw decoded string and nothing derived from it.** The scanned code is
a structured record whose fields include the quantity (`PACKING_DESIGN.md` §6.7), and quantity
is exactly the value a modified client would inflate. The app parses locally for its own live
weight display, but **the server re-parses `raw` and its reading is authoritative** — a
client-declared `quantity` in this payload is ignored if present.

```jsonc
// Request        Idempotency-Key: <uuid>
{ "scans": [
  { "uid": "0f7c-a1",
    "raw": "D/GFSG0000604934/FCGS2T438AVJ/14610086000RS     /000001/0000100.00/ABH/1/G/000/00",
    "t": "2026-08-16T09:39:01.220", "w": 1.022 },
  { "uid": "0f7c-a2",
    "raw": "D/KH6G0000000344/DCGKM4WNNA4Z/14610086000RS/000200/0095.00/ABF/1/G/000/00HSVGHDEHCFGBWJHDCBGDCFHBICFHBEICFHEW",
    "t": "2026-08-16T09:39:03.870", "w": 22.640 },
  { "uid": "0f7c-a3", "raw": "D/ZZZZ0000000001/…/99999999999XX/000001/…",
    "t": "2026-08-16T09:39:07.110", "w": 22.640 },
  { "uid": "0f7c-a4", "delta": -1, "sku_code": "SKU-C5500",
    "t": "2026-08-16T09:39:20.400", "w": 22.020 } ],       // explicit undo, no scan
  "weight_events": [
  { "e": "settle", "w": 22.640, "t": "2026-08-16T09:39:05.900" } ] }

// 200
{ "box_id": 8802,
  "results": [
    { "uid": "0f7c-a1", "result": "accepted", "sku_code": "SKU-C5500",
      "quantity": 1,   "serial": "GFSG0000604934", "qty_in_box": 2 },
    { "uid": "0f7c-a2", "result": "accepted", "sku_code": "SKU-C5500",
      "quantity": 1,   "serial": "GFSG0000604935", "qty_in_box": 2 },
    { "uid": "0f7c-a3", "result": "unknown_sku", "sku_code": null, "quantity": 0 },
    { "uid": "0f7c-a4", "result": "undo", "sku_code": "SKU-C5500",
      "quantity": -1,  "qty_in_box": 200 } ],
  "box": { "expected_kg": 22.020, "units": 200,
           "items": [ { "sku_code": "SKU-C5500", "quantity": 200 } ] },
  "job": { "packed_units": 200, "total_units": 350 } }
```

`result` values: `accepted` · `unparseable` (the string does not match the company's code
format) · `unknown_sku` (product field resolves to no `product` row) · `not_in_picklist` (real
SKU, not on this order) · `over_quantity` (the code's quantity would exceed `quantity_required`)
· `duplicate` (this `uid`, or this **serial**, already applied) · `undo` (a negative `delta`) ·
**`intact_carton`** (a full supplier carton — belongs at `/jobs/{id}/cartons`, §8b, and is
**never** absorbed into a built box).

**`quantity` comes from the code, so one trigger pull can be 200 units.** Everything
downstream — `picked_quantity`, the expected-weight sum, the `over_quantity` test — works in
the parsed quantity, not in scan count.

**`qty_in_box` is the SKU's total in the box after the whole batch is applied**, not a running
count reconstructed per scan. Twenty scans of one SKU all report the same figure. It is a
reconciliation value — the app's own display comes from local state — and the post-batch total
is the fact worth reconciling against.

**Every unit count on the wire is a JSON integer.** `picked_quantity` is `DECIMAL(16,4)` in the
table because the movement engine also carries weight-based stock, but packing counts discrete
things, and the app types these as `int`.

**The serial is the strong duplicate check.** Field 2 identifies a physical pack uniquely, so
the same serial arriving twice is a duplicate with certainty rather than by inference from
`uid`. Whether serials must be *queryable across boxes* is `PACKING_DESIGN.md` §9 Q13 — the one
open question that could still add a table.

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | R | box row — must be `status='open'` |
| `product` | R | resolve the **parsed product field** → `product_id` (matches `product_string` or `barcode`). **Not** the whole raw string — a composite code never equals a `barcode` value |
| `product_uom` | R | `WHERE product_id = %s AND factor_to_base = <field 5>` — identifies **which rung was scanned** and returns its `pack_gross_weight_kg`. Expected weight adds **one** gross pack weight per scan, not `qty × unit weight` (`PACKING_DESIGN.md` §6.7.3 Gap 1) |
| `potential_order_product` | R | `quantity_required`, to decide `over_quantity` against the **parsed quantity** |
| `entity_movement_details` | R | SKU rows for this box (`request_id`, `source_bin_id=box_id`) and this SKU across other boxes |
| `entity_movement_details` | **I** | a **SKU row** the first time a SKU appears in this box: `entity_type='sku'`, `entity_id=product_id`, `source_bin_id=<box_id>`, `picked_quantity`, JSON `{unit_weight_kg, weight_verifiable, scan_count}` |
| `entity_movement_details` | **U** | thereafter — `picked_quantity`, JSON `scan_count` |
| `entity_movement_details` | **U** | box row JSON: append to `scans[]` and `weight_events[]`, bump `flags.reject_scans` |

**`potential_order_product.quantity_packed` is NOT touched here.** Order-level progress moves
only when a box is **sealed** (§9) and is written back only at **submit** (§12). Otherwise an
abandoned box, or one refused at close, would leave the order believing units were packed
that are physically still on the bench — and the shortfall would surface at invoicing rather
than at the station.

**Rejected scans are stored, not discarded.** A packer repeatedly triggering a SKU that is
not on the picklist is exactly the pattern this module exists to make visible.

**Replay safety:** dedupe is on `(box_id, uid)` against the box JSON's `scans[]`. A retried
batch returns `duplicate` for rows already applied and writes nothing further, so the app can
retry the whole batch blindly.

**Two writes per batch, not per scan.** All accepted scans for one SKU collapse into a single
`picked_quantity` update, and the whole trail is one box-row JSON update — regardless of
batch size.

---

## SCREEN 8b — Scanning an intact supplier carton

An unopened OEM wholesale carton **is a shipping box**. It never goes inside the box being
built, so it does not pass through carton setup at all — one scan creates it, fills it, weighs
it and seals it. `PACKING_DESIGN.md` §6.8.

**A built box may be open at the same time and is untouched.** The packer can be halfway
through assembling box 3 when a full carton comes down; it becomes box 4, and box 3 stays open.

### 8b.1 `POST /api/v1/packing/jobs/{request_id}/cartons` — **NEW**

```jsonc
// Request        Idempotency-Key: <uuid>
{ "raw": "D/KH6G0000000344/DCGKM4WNNA4Z/14610086000RS/000200/0095.00/ABF/1/G/000/00HSVG…",
  "measured_kg": 9.402,
  "scanned_at": "2026-08-16T10:04:11.900" }

// 201
{ "box_id": 8807, "box_no": 4, "kind": "intact",
  "label_code": "KH6G0000000344",          // the carton's OWN code — field 2. No warehouse QR used.
  "status": "sealed",
  "contents": [ { "sku_code": "14610086000RS", "name": "Roller Comp Cam Chain",
                  "quantity": 200, "batch": "ABF" } ],
  "tare_kg": 1.400,                        // product_uom.pack_tare_kg for the 200-rung
  "expected_kg": 9.400,                    // tare + 200 x 0.040
  "sealed_kg": 9.402, "variance_g": 2, "within_tolerance": true,
  "job": { "packed_units": 200, "total_units": 350, "remaining_units": 150,
           "next_action": "new_box" } }

// 409 { "detail": "Carton holds 200 but only 150 are still needed for 14610086000RS. Open it and scan retail packs.",
//       "code": "carton_exceeds_need", "carton_quantity": 200, "remaining": 150 }
// 409 { "detail": "Carton reads 8.780 kg but should be 9.400 kg (−620 g, tolerance ±50 g). Do not ship — check the seal.",
//       "code": "weight_mismatch" }
// 409 { "detail": "Carton KH6G0000000344 is already packed on this order.", "code": "duplicate_carton" }
// 422 { "detail": "That is a retail pack, not an intact carton.", "code": "not_an_intact_carton" }
// 422 { "detail": "No packing weight on record for this carton size.", "code": "pack_tare_missing" }
```

| Table | Op | What |
|---|---|---|
| `entity_movement_request` | R | job must be `created`/`in_progress` |
| `product` | R | resolve the parsed part number |
| `product_uom` | R | `WHERE product_id = %s AND factor_to_base = <field 5>` → the rung and its **`pack_tare_kg`** |
| `potential_order_product` | R | remaining need, for the §6.8.2 intact-vs-open test |
| `entity_movement_details` | R | `WHERE entity_id = <carton code> AND entity_type='box'` — the same single-use check a warehouse label gets |
| `entity_movement_details` | **I** | the **box row**: `entity_type='box'`, `entity_id` = **the carton's own code**, `tare_weight_kg` from the ladder, `weight_kg` = measured, `expected_weight_kg`, `variance_g`, JSON `{kind:'intact', status:'sealed', …}` |
| `entity_movement_details` | **I** | one **SKU row** per line of the carton's contents, `source_bin_id` = the new box id |
| `entity_movement_request` | **U** | `metadata.box_seq += 1`, `metadata.totals.packed` |

**Everything happens in one transaction** — there is no `setup` or `open` state for an intact
carton, because there is nothing to add to it.

**The tare is read, not weighed.** A built box is weighed empty because nobody knows its weight
in advance; a sealed carton cannot be emptied to find out, so its packaging weight comes from
`product_uom.pack_tare_kg`. Same column on the row, same close arithmetic
(`tare + Σ(qty × unit weight)`) — which is what lets everything downstream treat the two kinds
identically.

**It is still weighed.** The scan says what should be inside; the scale confirms nothing was
removed before it reached the bench. A carton opened in transit and resealed is exactly what a
weight check catches and a trusted OEM seal does not.

**Routing is validated on both sides.** This endpoint rejects a retail-pack code
(`not_an_intact_carton`), and `/boxes/{id}/scans` rejects a carton code
(`result: 'intact_carton'`). The app routes off its own parse for the live display, but a
modified client cannot post a carton code to `/scans` and absorb 200 units into a hand-built
box whose weight it then controls.

---

## SCREEN 9 — Close box

### 9.1 `POST /api/v1/packing/boxes/{box_id}/close` — **NEW**

**This is the authoritative write.** A box whose `/scans` batches never uploaded still seals
correctly, because the item list is carried here in full.

```jsonc
// Request        Idempotency-Key: <uuid>
{ "sealed_kg": 4.482,
  "sealed_at": "2026-08-16T09:41:22.310",
  "items": [ { "sku_code": "SKU-H1180", "quantity": 4 },
             { "sku_code": "SKU-H1195", "quantity": 6 } ],
  "scans": [ /* optional: any not yet uploaded, same shape as 8.1 */ ],
  "weight_events": [ { "e": "seal", "w": 4.482, "t": "2026-08-16T09:41:22.310" } ] }

// 200
{ "box_id": 8802, "box_no": 2, "label_code": "WH1-000148213", "status": "sealed",
  "expected_kg": 4.480, "sealed_kg": 4.482,
  "variance_g": 2, "within_tolerance": true, "tolerance_g": 50,
  "unverifiable_kg": 0.000,
  "packed": { "units": 10, "skus": 2 },
  "packer": "Rahul K.", "sealed_at": "2026-08-16T09:41:22.310",
  "job": { "packed_units": 17, "total_units": 18, "remaining_units": 1,
           "next_action": "new_box" } }              // new_box | finish

// 409 — the fraud lock
{ "detail": "Box cannot close: scale reads 4.982 kg but scanned items total 4.480 kg (+502 g, tolerance ±50 g). Remove the unscanned item.",
  "code": "weight_mismatch",
  "expected_kg": 4.480, "sealed_kg": 4.982, "variance_g": 502, "tolerance_g": 50 }

// 409 { "detail": "Box is empty.", "code": "box_empty" }
// 409 { "detail": "SKU-H1180: 5 packed but only 4 required.", "code": "over_quantity" }
```

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | R | **the expected-weight aggregate** — `tare_weight_kg + SUM(sku.weight_kg × picked_quantity)` in one query, no JSON parsing (`PACKING_DESIGN.md` §4.5) |
| `potential_order_product` | R | required quantities for the over-quantity check |
| `entity_movement_details` | **I / U** | reconcile SKU rows to the `items` list in the body — **this list wins** over accumulated scans |
| `entity_movement_details` | **U** | box row: `picked_quantity` = total units; **`weight_kg`** = sealed weight; **`expected_weight_kg`**; **`variance_g`**; JSON → `status:'sealed'`, `within_tolerance`, `unverifiable_kg`, `sealed_at`, appended `scans[]` / `weight_events[]`, refreshed `flags` |
| `entity_movement_request` | **U** | `metadata.totals.packed`, `updated_on` |

**On 409 the box stays `open` and none of the above is written**, with one deliberate
exception: a `seal_rejected` entry is appended to the box JSON's `weight_events[]` and
`flags.seal_attempts` is incremented. A packer who attempts to seal an overweight box four
times is a signal, and discarding it would hide exactly the behaviour the module exists to
catch.

**The tolerance check runs here, on the server** — and it is now **one SQL aggregate**, not a
JSON parse per SKU:

```sql
SELECT b.tare_weight_kg + COALESCE(SUM(s.weight_kg * s.picked_quantity), 0) AS expected_kg
FROM       entity_movement_details b
LEFT JOIN  entity_movement_details s
       ON  s.request_id = b.request_id AND s.source_bin_id = b.id AND s.entity_type = 'sku'
WHERE b.id = %s AND b.created_on >= %s
GROUP BY b.id, b.tare_weight_kg;
```

The unit weights are the ones **snapshotted** onto each SKU row when the job started, not a
live read of `product.weight`. Any client-supplied expected value is ignored. The client-side
lock is a convenience copy of this rule, not the rule.

**`unverifiable_kg`** reports how much expected weight came from SKUs below
`weight_verify_floor_g`. A box of 5 g hinges passes a weight check that proves nothing.

**Trail truncation.** If the box JSON would exceed the `TEXT` 64 KB cap, the server truncates
`scans[]` oldest-first and sets `flags.scans_truncated`. It never fails the close — blocking
a packer from sealing a physically correct box because an audit field overflowed is the worse
outcome. `weight_events` and `flags` are never truncated.

---

## SCREEN 10 — Box complete

**No API call.** Renders entirely from the close response. The button offered is decided by
`job.next_action`: `new_box` → Screen 6.2, `finish` → Screen 12.

---

## SCREEN 11 — Save & exit

### 11.1 `POST /api/v1/packing/jobs/{request_id}/save` — **NEW**

```jsonc
// Request        Idempotency-Key: <uuid>
{ }

// 200
{ "request_id": 7701, "request_status": "saved",
  "packed_units": 17, "total_units": 18, "boxes_sealed": 2,
  "detail": "Saved. 17 of 18 packed — resume on a fresh box." }

// 409 { "detail": "Box 2 is still open. Close or abandon it before saving.",
//       "code": "box_still_open" }
```

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | R | reject if any box row is `setup`/`open` |
| `entity_movement_request` | **U** | `request_status='saved'`, `metadata.saved_at`, `metadata.totals` |

**Nothing is written to the order.** Save is a pause: `potential_order` stays `Picking` and
`quantity_packed` is untouched, because a half-written packed quantity would be read by
invoicing as final.

**Requirements §9.2 — resume always starts a fresh box.** Enforced by the 409 above: there is
no such thing as resuming into a box left open.

---

## SCREEN 12 — Submit (finalize, with or without shortfall)

### 12.1 `GET /api/v1/packing/short-reasons` — **NEW**

```jsonc
// 200
{ "items": [ { "reason_id": 3, "reason": "SKU not in Saleable Condition" },
             { "reason_id": 5, "reason": "Stock not found in bin" } ] }
```

| Table | Op |
|---|---|
| `understack_reason` | R — the one shared list; `WHERE is_active = 1` |

### 12.2 `POST /api/v1/packing/jobs/{request_id}/submit` — **NEW**

**The packer never enumerates the shortfall — the server derives it** from the job's own rows
(`quantity_required − quantity_packed` per SKU). Re-declaring it would be redundant typing at
the end of a job and a chance for the declaration to disagree with the packing record.

**Call it with an empty body first.** If the order is short it refuses **with the shortfall in
the body** — that rejection *is* the confirmation dialog, so the numbers the packer
acknowledges are produced by the same code that will write them:

```jsonc
// Step 1        POST /api/v1/packing/jobs/7701/submit
{ }

// 409 — the confirm step, not a failure
{ "code": "shortfall_requires_ack",
  "detail": "3 SKUs short. 12 units will be marked NOT FOUND and the order closed.",
  "shortfall": [
    { "sku_code": "14610086000RS", "name": "Roller Comp Cam Chain",
      "required": 200, "packed": 195, "short": 5 } ],
  "totals": { "required": 350, "packed": 338, "short": 12 } }
```

```jsonc
// Step 2        Idempotency-Key: <uuid>
{ "acknowledge_short": true,
  "reason_id": 5,                                // optional; applies to the whole submit
  "note": "picking short — bin A-12 empty",      // optional
  "reasons": { "14610086000RS": 3 } }            // optional per-SKU override

// 200
{ "request_id": 7701, "request_status": "submitted_short",
  "potential_order_id": 4821, "order_status": "Packed",
  "boxes": [ { "box_id": 8801, "box_no": 1, "label_code": "WH1-000148212",
               "units": 195, "sealed_kg": 9.204, "variance_g": 4 } ],
  "totals": { "packed": 338, "required": 350, "short": 12 },
  "shorts": [ { "sku_code": "14610086000RS", "name": "Roller Comp Cam Chain",
                "quantity": 5, "reason": "Stock not found in bin" } ],
  "box_count": 2 }

// 409 { "detail": "Box 2 is still open. Close or abandon it before submitting.",
//       "code": "box_still_open" }
// 409 { "detail": "Nothing has been packed. Return the picklist to the pool instead.",
//       "code": "nothing_packed" }        // see PACKING_DESIGN.md §6.10.4 / Q19
```

**A complete order needs no acknowledgement** — the first call just succeeds, and
`request_status` becomes `completed` rather than `submitted_short`.

**An accidental submit cannot close an order short.** Without `acknowledge_short` the call
refuses, so a mis-tap at the end of a shift cannot mark fifty units not found. There is also no
window between a preview and a commit in which the packed quantities could change, because
there is no separate preview call.

**The largest write in the module. One transaction.**

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | R | reject if any box is open; sum sealed boxes and per-SKU quantities |
| `potential_order_product` | R | **compute** the shortfall: `quantity − quantity_packed` per SKU |
| `entity_movement_details` | **I** | one **SHORT row** per short SKU, **server-generated**: `entity_type='sku'`, `entity_id=product_id`, **`source_bin_id=0`** (in no box), `picked_quantity=0`, `underpick_reason_id=<reason>` |
| `entity_movement_request` | **U** | `request_status='completed'`, `metadata.totals`, `metadata.submitted_at` |
| `potential_order_product` | **U** | `quantity_packed`, `quantity_remaining` — **via `order.service`, never direct SQL** |
| `potential_order` | **U** | `status='Packed'`, **`box_count` = sealed box count**, `short_pack_reason` |
| `order_state` | R | `state_id` lookup for the history row |
| `order_state_history` | **I** | one row: `Picking → Packed`, `changed_by` = the packer |

**Three things this write must get right.**

`box_count` is not decoration — it is read when the invoice and the `order` row are created
(`modules/fulfillment/invoice/repository.py:95`). A box count that never reaches it ships the
default of `1` onto every invoice regardless of how many boxes physically exist.

`Picking → Packed` is already legal in `OrderStateMachine.SINGLE_ORDER_TRANSITIONS` — no
state-machine change, no new status.

Packing must not write `potential_order*` with its own SQL. It calls `order.service`, the
boundary rule the rest of this codebase follows.

**Status stays `Packed` even when short.** `Picking → Packed` is the only forward transition
available, `short_pack_reason` already exists for exactly this, and inventing a "Packed Short"
state would force every downstream consumer of the lifecycle to learn it. The shortfall is
recorded by `quantity_packed < quantity`, the SHORT rows, and `short_pack_reason` — not by the
status.

> ### ⚠️ Marking units "not found" currently changes nothing on the invoice
>
> Both invoicing paths copy the **ordered** quantity into `order_product`, never the packed one:
>
> ```python
> # modules/fulfillment/invoice/repository.py:147 and :186
> SELECT potential_order_id, product_id, quantity, mrp, total_price, batch_id
> FROM potential_order_product …
> ```
>
> So a packer can mark 12 units not found, the order closes, and **the dealer is still invoiced
> for all 350** — billed for parts that never left the warehouse.
>
> The fix belongs to the invoice module, so it needs that owner's agreement rather than a
> unilateral change here — and it must be conditional on a completed packing job existing,
> because `quantity_packed` defaults to `0` and orders that never used this app would otherwise
> zero out. **Shipping the short-close flow without it produces confidently-recorded shortfalls
> that change nothing downstream.** `PACKING_DESIGN.md` §6.10.3 Gap 4 / Q18.

---

## SCREEN 13 — Picklist complete

**No API call.** Renders from the submit response.

---

## SCREEN 14 — Exit without saving / abandon box

### 14.1 `POST /api/v1/packing/boxes/{box_id}/abandon` — **NEW**

```jsonc
// Request        Idempotency-Key: <uuid>
{ "reason": "packer_exit" }        // packer_exit | wrong_label | damaged_box

// 200
{ "box_id": 8802, "status": "abandoned", "label_released": false }

// NOTE: label_released is FALSE — see below.
```

| Table | Op | What |
|---|---|---|
| `entity_movement_details` | **U** | box row JSON → `status:'abandoned'`, `abandoned_reason`, `abandoned_at` |
| `entity_movement_request` | **U** | `updated_on` |

**Nothing is deleted, ever.** The box row, its SKU rows and its whole JSON trail are kept in
full. A box abandoned immediately after a weight mismatch is a pattern worth being able to
see, and deleting the evidence would erase exactly the case the module exists for.

**The label is NOT released.** D6 says labels are single-use forever, so an abandoned box
keeps the label in its `entity_id` and that sticker is spent. Clearing it would either orphan
the code or let a second box claim it — two box rows, one label — which is the ambiguity the
single-use rule exists to prevent. The physical label is discarded with the carton; the packer
takes a fresh one. **If labels are expensive enough that this matters, say so** — the
alternative is a `voided` state and a release-on-abandon rule, which reopens that ambiguity.

**Client rule:** the demo's `confirmExit()` discards state locally. The real app must call
this first, or the box sits `open` forever and blocks the job from saving or submitting.

---

## SCREEN 15 — Account sheet

**Switch company** — no API call. Return to Screen 2 with the already-fetched list, then
re-bootstrap (§3).

### 15.1 `POST /api/v1/auth/logout` — **EXISTING**

```jsonc
// Request (Bearer required)
{ "refresh_token": "eyJ…" }
// 200 — always, even for an unknown token
{ "detail": "signed out" }
```

| Table | Op | What |
|---|---|---|
| `users`, `user_roles`…`permissions`, `user_warehouse_company` | R | resolving the caller |
| `refresh_tokens` | **U** | `revoked_at`, `revoked_reason='logout'` |

Deliberately always 200 and best-effort: a packer with no signal must still end up signed out
locally, and the endpoint must not reveal which tokens are real.

**Client rule:** if a job is in progress, save it (§11) before signing out.

---

## SCREEN 16 — Crash recovery and offline sync (cross-cutting)

### 16.1 `GET /api/v1/packing/jobs/{request_id}` — **NEW**

The reconciliation read after a crash, a battery swap or a long offline stretch. Returns the
full server-side truth so the app can diff its local queue against it.

```jsonc
// 200
{ "request_id": 7701, "potential_order_id": 4821, "display_id": "PL-4821",
  "request_status": "in_progress", "box_seq": 2, "tolerance_g": 50,
  "totals": { "required": 18, "packed": 7, "remaining": 11 },
  "items": [ { "sku_code": "SKU-H1180", "quantity_required": 4,
               "quantity_packed": 4, "quantity_short": 0 } ],
  "boxes": [
    { "box_id": 8801, "box_no": 1, "status": "sealed",
      "label_code": "WH1-000148212", "sealed_kg": 2.884, "units": 7 },
    { "box_id": 8802, "box_no": 2, "status": "open",
      "label_code": "WH1-000148213", "tare_kg": 0.402,
      "items": [ { "sku_code": "SKU-H1180", "quantity": 2 } ],
      "expected_kg": 1.642 } ] }
```

| Table | Op |
|---|---|
| `entity_movement_request`, `entity_movement_details` | R |
| `potential_order`, `potential_order_product`, `product`, `dealer` | R |

**Recovery rule:** the server's box state wins. If the app holds queued scans for a box the
server reports `sealed`, it drops them — that box's item list was settled authoritatively at
close.

### 16.2 Outbox ordering

Queued operations replay in dependency order, because each one's path contains an id minted
by the previous:

```
POST /jobs
  └─ POST /jobs/{request_id}/boxes        → box_id
       └─ POST /boxes/{box_id}/bind
            └─ POST /boxes/{box_id}/scans (batched, repeatable)
                 └─ POST /boxes/{box_id}/close
                      └─ POST /jobs/{request_id}/save | /submit
```

The app therefore **cannot** pack a whole picklist from a cold start with no signal: creating
the job and opening a box both need a server-minted id. If genuinely offline packing is
required, box identity must become a client-generated value — `PACKING_DESIGN.md` §9 Q5.
**Decide before build; retrofitting is expensive.**

### 16.3 What survives the app being killed or the device losing power

> **The local scan queue must be a durable write, not an in-memory buffer.** Every trigger
> pull writes one row to a local Room/SQLite table **synchronously** — sub-millisecond, well
> inside the gap between two trigger pulls — and a separate background worker drains that
> table to `/scans`. If the queue is a list held in a ViewModel, a kill or a flat battery
> loses every scan since the last flush, and the packer has no way to know which.

Three things must be persisted locally, not just the scans: the **`request_id`** of the open
job, the **`box_id`** of the open box, and the **outbox rows**. Without the first two the app
cannot address the endpoints it needs to replay to.

| Device dies at this moment | Held on the server | Held on the device | Actually lost |
|---|---|---|---|
| Before opening a picklist | — | — | nothing |
| After `POST /jobs` | the request row | `request_id` | nothing |
| After `POST /boxes` (tare captured) | box row + `tare_weight_kg` | `box_id` | nothing |
| Mid-scan, since the last flush | scans up to the last flush | **all** scans, on disk | **nothing** — the worker replays them |
| Mid-scan, batch sent but response never arrived | the batch, applied | the batch, still queued | nothing — replayed, then deduped |
| After `POST /close` | everything | — | nothing |
| Mid-scan, **device destroyed or wiped** | scans up to the last flush | gone with the device | ≤ one batch of scans — see below |

**Replay is safe by construction.** Every queued operation carries its `Idempotency-Key` and
every scan its `device_scan_uid`; a batch that was applied before the response was lost comes
back as `duplicate` per scan and writes nothing. The app can drain its outbox blindly without
reasoning about what did or did not land.

**On restart the app reconciles against the server, then against the scale.** After flushing
the outbox it calls `GET /packing/jobs/{request_id}`, which returns the open box with its tare
and its per-SKU quantities. The physical box is still sitting on the scale — so the app can
compare the live reading against `tare + Σ(unit × qty)` and tell the packer, in one line,
whether what is in the carton matches what the system thinks is in it. **The scale is the
recovery mechanism**, which is the one real advantage of a weight-verified flow: correctness
after a crash does not depend on the device having remembered anything.

**The destroyed-device case is an operational recovery, not a data one.** A packer picks the
picklist back up from the pool, sees the box still `open`, and re-weighs it. The variance
against the recorded quantities says exactly how many units are unaccounted for. They can
reconcile or empty the box and start it again — and because the close payload carries the
full item list, nothing that was previously flushed constrains what they declare.

> **Sizing note.** `scan_batch_size` and `scan_flush_ms` (§3.1) are the exposure window for
> that last case only — every other row in the table above is covered by the durable outbox.
> They are served from config precisely so this can be tuned against real behaviour rather
> than guessed now.

### 16.4 Stale boxes are a real leak

A box left in `setup` or `open` — packer walked away, device never came back — blocks its job:
`/save` and `/submit` both 409 while a box is open, and the picklist cannot be finished by
anyone. Nothing currently clears it.

Two mitigations, neither built:

- **The resume screen forces a decision.** `GET /packing/jobs/{id}` already returns the open
  box; the app should refuse to start a new one until the packer either closes or abandons it.
  This handles every case where a human comes back.
- **A sweep for the cases where nobody does.** Boxes untouched for N hours get
  `status='abandoned'` with `abandoned_reason='stale'`. Cheap to add and it stops one dead
  handset stranding a picklist indefinitely.

**Open — `PACKING_DESIGN.md` §9 Q9:** is the resume-screen prompt enough for v1, or is the
sweep needed from day one?

---

## 17 — Table write matrix

Every table this module touches, and which endpoint touches it how.

| Table | New? | Read by | Inserted by | Updated by |
|---|---|---|---|---|
| `users`, `roles`, `permissions`, `role_permissions`, `user_roles` | no | every authenticated call | — | — |
| `user_warehouse_company` | no | every authenticated call | — | — |
| `refresh_tokens` | no | `auth/refresh` | `auth/login`, `auth/refresh` | `auth/refresh`, `auth/logout` |
| `company` | no | `GET /companies` | — | — |
| `dealer` | no | `/picklists`, `/picklists/{id}`, `/jobs/{id}` | — | — |
| `product` | no | `/picklists*`, `/jobs`, `/scans`, `/close` | — | — |
| `potential_order` | no | `/picklists*`, `/jobs` | — | **`/jobs/{id}/submit`** |
| `potential_order_product` | no | `/picklists*`, `/jobs`, `/scans`, `/close`, `/submit` | — | **`/jobs/{id}/submit`** |
| `order_state` | no | `/jobs/{id}/submit` | — | — |
| `order_state_history` | no | — | **`/jobs/{id}/submit`** | — |
| `understack_reason` | no | `/short-reasons` | — | — |
| `idempotency_keys` | no | every packing write | every packing write | every packing write |
| **`entity_movement_request`** | no | `/picklists*`, `/jobs*`, `/boxes/*` | **`POST /jobs`** | `/boxes`, `/close`, `/save`, `/submit`, `/abandon` |
| **`entity_movement_details`** | no | `/picklists*`, `/jobs/{id}`, `/boxes/*` | **`/jobs/{id}/boxes`** (box row), **`/scans`** + **`/close`** (sku rows), **`/submit`** (short rows) | `/bind`, `/scans`, `/close`, `/abandon` |

**No new tables. No packing endpoint deletes a row.** The only deletes in the whole flow are
`idempotency_keys` claim-release and the existing `refresh_tokens` purge job.

### The three EMD row kinds, at a glance

| | `entity_type` | `entity_id` *(VARCHAR)* | `source_bin_id` | `picked_quantity` | `tare_weight_kg` | `weight_kg` | `expected_weight_kg` | `variance_g` | Created by |
|---|---|---|---|---|---|---|---|---|---|
| **Built box** | `'box'` | the warehouse QR label | `0` | units in box | **weighed** empty | **sealed wt** | tare + Σ | sealed − expected | `POST /jobs/{id}/boxes` |
| **Intact carton** | `'box'` | **the carton's own code** | `0` | units in carton | **read** from `product_uom.pack_tare_kg` | measured wt | tare + Σ | measured − expected | `POST /jobs/{id}/cartons` |
| **SKU in box** | `'sku'` | `'90114'` | **box row's `id`** | qty in that box | — | unit wt | — | — | `/scans` or `/cartons` |
| **Short** | `'sku'` | `'90121'` | `0` | `0` | — | — | — | — | `POST /jobs/{id}/submit` |

A **built** box row is written three times: inserted with `entity_id=''` and a weighed
`tare_weight_kg`, then `entity_id` set to the label at bind, then the weight columns filled at
close. An **intact carton** row is written once, complete, and is already `sealed`.

`tare_weight_kg` means the same thing in both — the weight of packaging that is not stock. Only
its source differs, which is what lets every downstream consumer treat the two kinds
identically.

---

## 18 — Open questions

| # | Question | Recommendation |
|---|---|---|
| **Q1** | **`product.weight` coverage per company** (`PACKING_DESIGN.md` §6.5 has the query). | Run it first. It can invalidate the module for a company. |
| **Q2** | `request_status` — existing `created/in_progress/saved/completed/cancelled`, or the literal `started`? | Existing vocabulary; `started` maps to `in_progress`. |
| **Q3** | Login: Packer ID + PIN (demo) vs email + password (backend). | Email + password for v1. |
| **Q4** | `GET /companies` returns no `warehouse_id`, which every packing endpoint needs. | Add `warehouses[]` to the existing response — additive. |
| **Q5** | Fully-offline packing from a cold start? | Not possible as specified (§16.2). If required, box identity must be client-generated — a schema change. **Decide before build.** |
| **Q6** | On abandon, is the label spent forever (§14.1) or released for reuse? | Spent. Releasing reopens the ambiguity D6 closed. |
| **Q7** | **Max carton label length.** `entity_id` is sized `VARCHAR(64)` on the assumption of `WH1-000148213`. | Confirm the printed format before the ALTER — re-sizing later is a second full-table rebuild. |
| **Q8** | Merge the two setup calls (§6.2 tare, §7.1 bind) into one carrying both? | Removes the transient `entity_id=''`, one round trip and one UPDATE. Changes a reviewed API surface, so it is your call. |
| **Q9** | **Confirm the barcode field map** — 7 of 11 fields are inferred or unknown (`PACKING_DESIGN.md` §6.7). | Get the printing spec before writing the parser. |
| **Q10** | **`product_uom.pack_weight_kg`** — a box-scanned SKU's inner packaging has no weight anywhere, and it is larger than the whole tolerance. | Add the column. It gates weight verification for every box-scanned SKU. |
| **Q11** | **Must serials be queryable across boxes?** | If yes, the scan trail cannot stay JSON-only — the one question that could still add a table. |

---

## 19 — Build order

1. **Answer Q1 and Q5.** Either can change the plan.
2. Register the movement tables in `PARTITION_COLUMN` (`PACKING_DESIGN.md` §6.3) — one line,
   fixes existing picking/stacking queries too.
3. **Run the `entity_movement_details` ALTER while the table is still empty** — retype
   `entity_id` to `VARCHAR(64)`, add the four weight columns and the two indexes
   (`PACKING_DESIGN.md` §4.6) — and fix `modules/inventory/router_v1.py:351` in the same
   change. Once picking writes to this table the ALTER becomes an outage.
4. Create a `packer` role and grant it `inventory:pack`.
5. `service.py` + `router_v1.py` under `modules/fulfillment/packing/`. **No `schema.py`** —
   this module registers no tables.
6. Reads: `/config`, `/picklists`, `/picklists/{id}`, `/short-reasons`. Screens 1–5 build
   against these alone.
7. `POST /jobs`, `GET /jobs/{id}`, `/jobs/{id}/boxes`, `/boxes/{id}/bind` — Screens 6–7.
8. `/scans` (batched) and `/close`, **with the server-side tolerance check in the first
   commit**. The flow working without it is the bug.
9. `/save`, `/submit`, `/abandon`, plus the `order.service` write-back.
10. Update `AI_CONTEXT.md`: packing is a `fulfillment`-cluster module that owns **no tables**
    and rides the inventory-owned movement engine.
