# Packing module — data model on the existing movement engine (DRAFT v2)

**Status: DRAFT for review. Nothing created, nothing dropped.**

Backend design for the Zebra TC21 packing app (`wms-app`, Android). Behaviour comes from
`Packing-Requirements.txt`; the HTML demo is a UI reference only.

**v2 supersedes v1.** v1 proposed nine new packing-owned tables. That is rejected. Packing
runs on the **existing movement engine** — `entity_movement_request` +
`entity_movement_details` — exactly as picking and stacking do.

> ### Total schema change in this design
> **Zero new tables.** One `ALTER TABLE entity_movement_details`: retype `entity_id` to
> `VARCHAR(64)` so the scanned label *is* the box id, plus four nullable weight columns so
> box weight is a column read, never a JSON parse (§4.6). One one-line fix to an existing
> helper (§6.3).

Companion: [`PACKING_SCREEN_API_CONTRACTS.md`](./PACKING_SCREEN_API_CONTRACTS.md) — the
screen-by-screen endpoint contracts and per-table write matrix.

---

## 1. Decisions taken (settled, not open)

| # | Decision |
|---|---|
| D1 | **There is no picklist entity.** A picklist *is* a `potential_order`. `PL-4821` is a display rendering of `potential_order_id`. No new id space. |
| D2 | **The packing job is an `entity_movement_request`** with `movement_type='packing'`, `request_identifier=potential_order_id`, `reference_type='ORDER'` — the same shape picking already uses. |
| D3 | **A box is an `entity_movement_details` row** with `entity_type='box'`, and **`entity_id` holds the scanned carton label** (`'WH1-000148213'`). Its row `id` is the internal link target. |
| D4 | **The SKUs in a box are EMD rows** with `entity_type='sku'`, `entity_id=product_id`, and **`source_bin_id` = the box row's id**. |
| D5 | **Carton labels are alphanumeric with a prefix**, so `entity_id` is **retyped from `BIGINT UNSIGNED` to `VARCHAR(64)`** rather than adding a separate label column. §4.6. |
| D6 | **Labels are single-use forever.** One code maps to exactly one box row, for all time. |
| D7 | **Weights are real columns, not JSON.** `tare_weight_kg`, `weight_kg`, `expected_weight_kg`, `variance_g` on the EMD row — so box weight is a column read and the close-time recompute is one SQL aggregate. §4.6. |
| D8 | **The scan trail and weight events go in the box row's `source_stock_info` JSON**, written once at box close. Nothing queryable lives there. See §5. |
| D9 | **Dispatch re-weigh needs no request of its own.** The orders leaving are already known; query that order's box rows and compare weights. **Not built in v1** — §7. |
| D10 | **No `packing_station` table.** Bluetooth pairing is OS-level device bonding; tolerance and thresholds come from app config, not a table. §6.4. |

---

## 2. What already exists and is reused unchanged

| Need | Where |
|---|---|
| Login / refresh / logout / me | `POST /api/v1/auth/*` — built |
| Company select | `GET /api/v1/companies` — built |
| Company scoping | `shared/auth_v1.py::company_filter`; **EMR-header and EMD both already carry `company_id`** (added via the `_COMPANY_ID_TABLES` manifest in `db_manager.py`) |
| Packer permission | `rbac.P.INVENTORY_PACK = "inventory:pack"` — code exists, granted to no role yet |
| The picklist | `potential_order` + `potential_order_product` (`quantity_packed`, `quantity_remaining`) |
| SKU name / barcode / **unit weight** | `product.name`, `product.barcode`, `product.product_string` (= sku_code), `product.weight DECIMAL(10,3)` |
| The job engine | `entity_movement_request` / `entity_movement_details` |
| Shortfall reasons | `understack_reason` — one shared list; `entity_movement_details.underpick_reason_id` already points at it |
| Retry-safe writes | `shared/idempotency.py`, `Idempotency-Key` header |
| Order lifecycle | `Open → Picking → Packed → …`; `Picking → Packed` is already legal in `OrderStateMachine` |

**Not reused: `entity_movement_recommendation`.** It was considered for per-SKU acks and
rejected — see §8.

---

## 3. The shape

```
potential_order (status = 'Picking')          ← the picklist. Unchanged, no new columns.
        │  request_identifier = potential_order_id, reference_type = 'ORDER'
        ▼
entity_movement_request                        movement_type = 'packing'
        │                                      request_status = created|in_progress|saved|completed|cancelled
        │                                      metadata JSON  = tolerance, box_seq, totals
        │  request_id
        ▼
entity_movement_details ────────────────────────────────────────────────────────────
        │
        ├── BOX row      entity_type='box'  entity_id='WH1-000148213'  ← the scanned label
        │                id = 8801                     ← what the sku rows point at
        │                source_bin_id      = 0
        │                picked_quantity    = 10       (units in the box)
        │                tare_weight_kg     = 0.400
        │                weight_kg          = 3.962    ← THE box weight. one column.
        │                expected_weight_kg = 3.960
        │                variance_g         = 2
        │                source_stock_info  = JSON {status, box_no, timestamps,
        │                                           scans[], weight_events[], flags{}}
        │
        ├── SKU row      entity_type='sku'  entity_id='90114'  source_bin_id=8801
        │                picked_quantity = 4
        │                weight_kg       = 0.620       ← unit weight snapshot
        │
        ├── SKU row      entity_type='sku'  entity_id='90119'  source_bin_id=8801
        │                picked_quantity = 6
        │                weight_kg       = 0.180
        │
        └── SHORT row    entity_type='sku'  entity_id='90121'  source_bin_id=0  ← 0 = in no box
                         picked_quantity = 0
                         underpick_reason_id = 5       ('Stock not found in bin')
```

**`source_bin_id = 0` means "belongs to no box"** — which is exactly what a not-found
shortfall is. That reuses the column's existing "no bin" convention rather than inventing a
flag, and it makes "everything in box 8801" and "everything short on this order" two
variations of the same query.

**Index alignment.** The two queries the app runs constantly are already served by keys that
exist on the table today:

| Query | Index used | New? |
|---|---|---|
| all boxes on this job | `request_id (request_id)` + `entity_type='box'` | exists |
| the SKUs inside box 8801 | **`idx_request_source (request_id, source_bin_id)`** | exists |
| this SKU across all boxes | `request_id_2 (request_id, entity_id, entity_type)` | exists |
| has label `WH1-…` ever been used? | `idx_emd_entity (entity_id, entity_type)` | added by §4.6 |
| boxes sealed outside tolerance | `idx_emd_variance (variance_g)` | added by §4.6 |

`idx_request_source` was built for stacking's "which bin did this come from". It fits
"which box is this in" with no change, because a box *is* a bin in the movement engine's
grammar.

---

## 4. Field-by-field mapping

### 4.1 `entity_movement_request` — the packing job

| Column | Packing value |
|---|---|
| `id` | the job id |
| `planogram_id` | warehouse id (`planogram_for_warehouse()`, defaults 1) |
| `company_id` | the order's company — already on the table |
| `movement_type` | `'packing'` |
| `request_status` | `created` → `in_progress` → `saved` ⇄ `in_progress` → `completed` \| `cancelled` |
| `request_identifier` | **`potential_order_id`** |
| `reference_type` | `'ORDER'` |
| `metadata` (JSON) | §4.3 |
| `meta_info` | `''` |
| `created_by_id` / `updated_by_id` | the packer's `users.id` |

**One open naming point:** you said *"status as started"*. `RequestStatus` in
`modules/inventory/service.py` already defines `created / in_progress / completed /
cancelled`, and picking will use them. This design uses that vocabulary and adds `saved` for
the pause state, so `started` maps to `in_progress`. **Say if you want the literal string
`started` instead** — it is a constant change, nothing structural.

**One behavioural point to confirm:** you said the request is created *"when a user clicks on
the packing tile"*. A request needs `request_identifier = potential_order_id`, which does not
exist until a picklist is chosen. This design therefore creates it when the packer **opens a
picklist**, not when they tap the tile. Tapping the tile only lists the pool.

### 4.2 `entity_movement_details` — boxes, SKUs and shorts

| Column | BOX row | SKU-in-box row | SHORT row |
|---|---|---|---|
| `id` | **the internal box id** — what SKU rows point at | — | — |
| `request_id` | the job id | the job id | the job id |
| `company_id` | order's company | same | same |
| `entity_type` | `'box'` | `'sku'` | `'sku'` |
| `entity_id` *(now VARCHAR)* | **the scanned label** `'WH1-000148213'` | `'90114'` (product_id as text) | `'90121'` |
| `source_bin_id` | `0` | **the box row's `id`** | `0` |
| `source_location_id` | `Location.DELIVERY` (6) | `Location.DELIVERY` (6) | `Location.DELIVERY` (6) |
| `picked_quantity` | total units in the box | qty of this SKU in this box | `0` |
| `tare_weight_kg` *(new)* | empty box weight | `NULL` | `NULL` |
| `weight_kg` *(new)* | **sealed weight of the box** | unit weight snapshot | `NULL` |
| `expected_weight_kg` *(new)* | tare + Σ(unit × qty) | `NULL` | `NULL` |
| `variance_g` *(new)* | sealed − expected, in grams | `NULL` | `NULL` |
| `underpick_reason_id` | `0` | `0` | **`understack_reason.id`** |
| `source_stock_info` | §4.4 box JSON | `'{}'` | `'{}'` |

**A box has two identifiers, and they do different jobs.** `entity_id` is the label — the
identity the physical world knows, scanned at the bench and at the dispatch gate.
`id` is the internal link target that `source_bin_id` points at. They are separate because
the row exists before the label is scanned (§4.7) and because a 64-character string is a
poor thing to repeat on every SKU row.

**`entity_id` is `''` between insert and bind.** The box row is created when the empty box is
weighed; the label arrives one call later. `entity_id` is `NOT NULL`, so it is written as the
empty string and replaced at bind. The single-use check ignores `''`. If you would rather not
have that transient state, the two setup calls can be merged into one that carries both tare
and label — one INSERT instead of INSERT+UPDATE, and one less round trip on the handheld. It
changes the API surface, so it is Q8 in §9 rather than a silent choice.

### 4.3 `entity_movement_request.metadata` (JSON, real JSON column)

```jsonc
{ "v": 1,
  "display_id": "PL-4821",
  "dealer_id": 88,
  "tolerance_g": 50,               // SNAPSHOT of the rule in force when the job started
  "weight_verify_floor_g": 30,
  "box_seq": 2,                    // last box number issued — survives save/resume
  "station": "TC21-07",
  "totals": { "required": 18, "packed": 17, "short": 1 },
  "saved_at": null,
  "submitted_at": "2026-08-16T09:43:10" }
```

`tolerance_g` is snapshotted, not read live, so an audit months later can answer
"was this box within tolerance *by the rule that applied that day*".

`box_seq` replaces the per-session counter — it is what keeps box numbering continuous
across a save-and-resume (requirements §7).

### 4.4 Box row `source_stock_info` (TEXT holding JSON)

**Nothing queryable lives here any more.** Every weight is a column (§4.6); this document
holds only what is read *after* you already have the box.

```jsonc
{ "v": 1,
  "box_no": 2,
  "status": "sealed",              // setup | open | sealed | abandoned
  "tolerance_g": 50,               // the rule that applied, for the audit
  "within_tolerance": true,
  "unverifiable_kg": 0.000,        // expected weight contributed by SKUs under the floor
  "packed_by": 42,
  "tare_at":   "2026-08-16T09:38:02.140",
  "bound_at":  "2026-08-16T09:38:20.512",
  "sealed_at": "2026-08-16T09:41:22.310",

  "flags": { "reject_scans": 1, "seal_attempts": 2, "max_variance_g": 620,
             "scans_truncated": 0 },

  "scans": [
    {"t":"09:39:01.220","bc":"8901234500011","sku":90114,"r":"ok","w":1.022},
    {"t":"09:39:07.110","bc":"8901234599999","r":"unknown_sku"} ],

  "weight_events": [
    {"t":"09:38:02.140","e":"tare","w":0.400},
    {"t":"09:39:04.900","e":"settle","w":1.642,"x":1.642},
    {"t":"09:41:20.100","e":"seal_rejected","w":4.580,"x":3.960,"d":620} ] }
```

`"v"` is a schema version. A JSON document in a `TEXT` column will change shape over its
life, and without a version marker the reader has to guess which shape it is holding.

`flags` is a deliberate summary block: it is the part a future reporting job can extract
cheaply without parsing every `scans` array. See §5.

### 4.5 SKU row — no JSON needed

The SKU row's only packing-specific datum is its unit weight, and that is now the
`weight_kg` column. `source_stock_info` stays `'{}'`.

**`weight_kg` on a SKU row is a snapshot, not a join.** The expected weight is the evidence a
fraud accusation rests on. If `product.weight` is corrected next month — a routine
master-data fix — every historical box would silently re-derive a different expected weight,
and boxes that passed would start reading as mismatches. The snapshot makes each box's
arithmetic reproducible from its own rows.

**And it makes the close-time check one query instead of N JSON parses:**

```sql
SELECT b.tare_weight_kg + COALESCE(SUM(s.weight_kg * s.picked_quantity), 0) AS expected_kg
FROM       entity_movement_details b
LEFT JOIN  entity_movement_details s
       ON  s.request_id = b.request_id AND s.source_bin_id = b.id AND s.entity_type = 'sku'
WHERE b.id = %s AND b.created_on >= %s
GROUP BY b.id, b.tare_weight_kg;
```

### 4.6 The one schema change

```sql
ALTER TABLE entity_movement_details
  MODIFY COLUMN entity_id          VARCHAR(64)   NOT NULL,
  ADD    COLUMN tare_weight_kg     DECIMAL(12,3) NULL AFTER picked_quantity,
  ADD    COLUMN weight_kg          DECIMAL(12,3) NULL AFTER tare_weight_kg,
  ADD    COLUMN expected_weight_kg DECIMAL(12,3) NULL AFTER weight_kg,
  ADD    COLUMN variance_g         INT           NULL AFTER expected_weight_kg,
  ADD    KEY idx_emd_entity   (entity_id, entity_type),
  ADD    KEY idx_emd_variance (variance_g);
```

Applied through the `_add_col` pattern `db_manager.py` already uses, so a fresh database and
an existing one converge on the same shape.

#### Retyping `entity_id` — what it costs, checked against the code

`entity_id` is polymorphic by design (`'sku' | 'CONTAINER'`, now `'box'`). Making it a string
lets the scanned label live in it directly instead of needing a parallel column, and it
preserves leading zeros and prefixes that a `BIGINT` would silently destroy. The precedent is
in this module already: `transferin_info.transferin_id` was made `VARCHAR(64)` for exactly
this reason — *"these are alphanumeric and the series prefix is meaningful."*

| Concern | Finding |
|---|---|
| Existing queries filtering EMD by `entity_id` | **None.** It is only SELECTed and INSERTed today (`_details_for`, `create_picking_request`, `router_v1.py`). No index degrades. |
| Known break | **`modules/inventory/router_v1.py:351`** — `codes_for_sku_ids([d['entity_id'] for d in details])` keys on ints and would silently return no SKU codes. Needs `int(d['entity_id'])` for `entity_type='sku'` rows. **This is the one code change the retype forces.** |
| Future joins to `product.product_id` | A `VARCHAR` ↔ `INT` comparison stops MySQL using the index on the *other* table. Every such join must cast explicitly: `p.product_id = CAST(d.entity_id AS UNSIGNED)`, or bind the SKU id as a string. Worth a comment on the column. |
| The other five `entity_id` columns | `transferin_info`, `fc_entity_stock`, `fc_entity_stock_ledger`, `fc_entity_recommendation`, `fc_sku_price_details` are **left as integers**. Only EMD carries boxes, so only EMD needs strings. Cross-table comparisons between them and EMD must cast — see above. |
| Migration cost | `BIGINT → VARCHAR` is `ALGORITHM=COPY`: a full rebuild of every partition under a metadata lock. |

> **Do this now, not later.** The movement write flows are still `NotImplementedError`, so
> `entity_movement_details` is near-empty and the ALTER is effectively instant. Once picking
> starts writing to it, the same statement becomes an outage-shaped migration on a
> partitioned table.

**`VARCHAR(64)` assumes labels fit in 64 characters.** Fine for `WH1-000148213`; not fine for
a QR carrying a URL or a full GS1 payload. **Confirm the label format before the ALTER** — it
is far cheaper to size the column right the first time.

**It cannot be a `UNIQUE` key.** `entity_movement_details` is partitioned by `created_on`, and
MySQL requires the partition column in every unique index — so a global
`UNIQUE(entity_id)` is impossible, and adding `created_on` would make it unique only *per
month*, which is not a constraint worth having. The single-use rule (D6) is therefore an
application check over `idx_emd_entity`. That is sufficient: there is exactly one physical
sticker, so two packers cannot bind the same label at the same instant.

#### Why the weights are columns

Reading a box's weight out of `source_stock_info` means `JSON_EXTRACT` over a `TEXT` column —
unindexable, and a full scan for anything that filters on it. Three queries make that
unacceptable:

```sql
-- 1. what did this box weigh?
SELECT weight_kg FROM entity_movement_details WHERE id = %s AND created_on >= %s;

-- 2. the dispatch check (D9) — every sealed box on an order, no JSON at all
SELECT d.id, d.entity_id AS label, d.weight_kg
FROM  entity_movement_request r
JOIN  entity_movement_details d ON d.request_id = r.id
WHERE r.movement_type = 'packing' AND r.reference_type = 'ORDER'
  AND r.request_identifier = %s AND d.entity_type = 'box';

-- 3. fraud reporting — served by idx_emd_variance + partition pruning
SELECT id, entity_id, variance_g FROM entity_movement_details
WHERE variance_g > 50 AND created_on >= %s;
```

Query 2 is the one that settles it. `weight_kg` on the box row is *the* number the gate
compares against, and it now costs one index seek per order.

All four columns are `NULL` for every other movement type, so stacking and picking are
untouched.

---

## 5. The scan trail and weight events — recommended design

You asked for the best design here. This is it, with its cost stated plainly.

**Recommendation: one JSON document on the box row, written once at box close.**

**Why not a per-scan table.** It would be the only new table in the design, and it would buy
searchability that the actual investigation pattern does not need. A fraud investigation
starts from a *specific* carton — a held dispatch, a dealer short-claim, a supervisor's
report. You already have the box id at that point, so the trail only has to be readable
*per box*, which JSON does perfectly.

**Why not written per scan.** Writing the trail as scanning happens means an API call per
scan. §6.2 quantifies what that costs. The trail is uploaded as part of the close call, which
happens anyway — so the audit trail costs **zero additional API calls**.

**Why not `entity_movement_recommendation`.** §8.

### What it costs — the honest version

**1. You cannot query across boxes.** "Every packer who attempted an out-of-tolerance seal
last month" is not a query; it is a scan of every box row's JSON. This is the real
trade-off, and it is why `flags` exists as a top-level summary block: if that report becomes
a genuine need, a nightly job extracts `flags` into a small reporting table without touching
the packing flow or re-parsing scan arrays. That is when a table earns its place — not
before.

**2. `TEXT` caps at 65,535 bytes.** Budget:

| Content | Per entry | 100-unit box |
|---|---|---|
| scan entry | ~60 B | 6 KB |
| weight event | ~45 B | 9 KB (≈2× scan count) |
| header + flags | — | 0.6 KB |
| **total** | | **≈16 KB** |

Comfortable to roughly **350 units in one box**. Beyond that the server **truncates the
`scans` array oldest-first and sets `flags.scans_truncated`** — it must never fail the close.
A packer blocked from sealing a physically correct box because an audit field overflowed is
a worse outcome than a shortened trail. `weight_events` and `flags` are never truncated;
they carry the fraud signal.

**3. Do not store the raw 500 ms stream.** Requirements §6.3 mentions a rolling series
sampled every 500 ms. A five-minute box is ~600 samples ≈ 15 KB on its own, and it adds
nothing over the settle/excess events already captured. Store **significant events only**:
`tare`, `settle` (after each scan burst), `excess_detected`, `excess_cleared`, `freeze`,
`seal`, `seal_rejected`.

---

## 6. Rules that must live on the server

### 6.1 The tolerance check is server-side or it is nothing

The demo enforces the fraud lock by disabling a button. On a real device that is a
suggestion: a modified APK, a replayed request or a hand-rolled HTTP call seals any box.
The close endpoint **recomputes**

```
expected_kg = tare_kg + Σ (sku_row.source_stock_info.unit_weight_kg × picked_quantity)
```

from the snapshotted weights, ignores any client-supplied expected value, and rejects
outside tolerance with 409. The client-side lock stays — it gives instant feedback — but it
is the convenience copy of the rule, not the rule.

### 6.2 Batch the scans — the sizing that decides the API shape

If each SKU ack is one HTTP call, the cost is not the write. It is auth.
`shared/auth_v1.py::_resolve_current_user` runs **7 queries before the endpoint executes a
single statement**:

```
SELECT users                                                              1
get_user_warehouse_ids → get_user_permission_codes + user_warehouse_company  2
get_user_company_ids   → get_user_permission_codes + user_warehouse_company  2   ← both repeated
get_user_roles                                                            1
```

The permission and grant lookups run **twice** because the two helpers each call
`get_user_permission_codes` independently.

| Design | Requests for a 100-unit picklist | Auth queries |
|---|---|---|
| one call per ack | 100 | 700 |
| batched, 20 acks per flush | 5 | 35 |

Ten packers scanning ~1/sec at one-call-per-ack is ~70 auth queries/sec sustained, against a
single-process API on an RDS instance capped at 60 connections. **Batching is not an
optimisation here; it is what keeps the module inside its connection budget** — and it is
also what makes the app work in a dead zone at all, which requirements §2 demands anyway.

If auth cost still matters afterwards, caching `get_user_permission_codes` per user for ~60 s
removes 6 of the 7 queries for **every** mobile endpoint, not just packing. Out of scope
here; worth its own ticket.

> **Batching only survives a crash if the queue is on disk.** Every trigger pull must be a
> synchronous local SQLite/Room insert; the flush is a background worker draining that table.
> An in-memory buffer loses every scan since the last flush when the app is killed or the
> battery goes — and the packer has no way to tell which ones. The full durability matrix,
> and why the scale itself is the recovery mechanism, is in
> `PACKING_SCREEN_API_CONTRACTS.md` §16.3.

### 6.2b Where each check runs — and why the live one is not a server call

The obvious objection to batching is that the weight check has to be live: an item slipped in
without a scan must turn the screen red *now*, not four seconds from now. That is correct, and
it is exactly what the design does. **The live check runs on the device, and it is faster than
any API could make it.**

The reason is that the server has *less* information than the handset at that moment, not
more. The Bluetooth scale is paired to the Zebra; its stream never touches the backend. The
expected weight is `tare + Σ(unit_weight × qty)`, and every unit weight was delivered in the
job payload when the picklist was opened. Both inputs are already on the device. A round trip
adds a network hop to an arithmetic comparison and returns an answer the app had before it
asked.

The timing settles it independently:

- **If the UI waits for the response,** the packer is gated on network latency — and the
  requirements already rule out gating per scan, because the scale takes ~1 s to settle and a
  packer scans faster than that (§6.3 of the requirements). You would be making the app slower
  than the physics.
- **If the UI does not wait for the response,** the call is not part of the real-time loop by
  definition. It is telemetry with extra steps.

There is no third option where a per-scan HTTP call makes the red/green feedback arrive
sooner than the local computation already does.

| Check | Runs where | Why there |
|---|---|---|
| Live weight vs expected — the red/green hero | **Device**, on every scale sample | Both inputs are on the device. The scale is not connected to the server. |
| Gross-overage freeze (expected + 2× heaviest SKU) | **Device** | Same inputs, and it must fire mid-scan without waiting for anything. |
| `over_quantity` — more units than the line needs | **Device**, re-checked at close | Picklist quantities arrive in the job payload. |
| `unknown_sku` / `not_in_picklist` | **Device**, recorded server-side | The SKU list arrives in the job payload. |
| **The authoritative seal check** | **Server, at close** | The only check that must survive a modified client. See §6.1. |

**A per-scan call would not add tamper resistance either.** The client controls what it
reports either way — sending 100 claims instead of 5 does not make any of them more true. What
makes the rule enforceable is that the server recomputes from its own snapshotted unit weights
at close and refuses to seal. That is why the authoritative check sits at the moment the
contents become final, and why it does not need to sit anywhere else.

#### The add-then-remove case, step by step

This is the scenario worth tracing, because it is the one the module exists for.

```
09:39:04   4 brake pads scanned      expected 2.880   scale 2.880   Δ 0 g       green
09:39:12   unscanned item goes in    expected 2.880   scale 3.500   Δ +620 g    RED, close locked
                                     └─ local, off the scale stream. no network involved.
                                     └─ weight_event {e:'excess_detected', w:3.500, d:620}
09:39:41   item taken back out       expected 2.880   scale 2.880   Δ 0 g       green, close unlocked
                                     └─ weight_event {e:'excess_cleared', w:2.880}
09:39:58   close                     server recomputes 2.880 vs 2.880  →  sealed
```

The box seals, correctly — nothing unbilled left the warehouse, which is the point. **And the
whole episode survives in the audit trail.** `excess_detected` and `excess_cleared` are both
recorded with device timestamps, so the box's history reads "at 09:39:12 the weight rose 620 g
with no matching scan; 29 seconds later it came back down". A packer who produces that pattern
across many boxes is visible in the data even though every one of their boxes sealed clean.

> **Flush weight anomalies immediately, not on the batch timer.** Ordinary scans can wait for
> the 20-scan / 4-second window; `excess_detected`, `excess_cleared` and `freeze` should flush
> the moment they occur. That gives the server a near-real-time fraud signal — within a second,
> not a batch — while keeping the scan traffic batched. It is the one place where "send it now"
> earns its round trip, because the event is rare and it is the one ops would want to see live.

#### Removing an item the packer *did* scan

Distinct from the sneak case, and it needs a control. If a packer scans an item and then takes
it physically out of the box, the scan count and the weight diverge and the box can never
close. The app therefore needs an explicit correction — the demo's "Remove last", or a minus on
the line — which emits a scan row with `delta = -1` and `result = 'undo'`.

This does **not** violate the "no on-screen scan buttons" rule in requirements §6.1. That rule
exists so that every *addition* is evidenced by a hardware decode. An undo is a correction, it
reduces the count rather than inflating it, and it is recorded as its own auditable event.

### 6.3 Every write to EMD/EMR-header must carry `created_on`

Both tables are `PARTITION BY RANGE COLUMNS(created_on)` with PK `(id, created_on)`. An
`UPDATE … WHERE id = %s` **cannot prune partitions** — MySQL probes every monthly partition,
~13 with the current window.

**Latent gap found while designing this:** neither movement table is registered in
`PARTITION_COLUMN` in `shared/db_manager.py`, even though both are partitioned. So
`partition_filter('entity_movement_details')` returns `('1=1', ())` and prunes **nothing**
— every existing query on them scans all partitions today. Fix, required by this design and
beneficial to picking and stacking too:

```python
PARTITION_COLUMN: dict = {
    ...
    'entity_movement_request':        'created_on',
    'entity_movement_details':        'created_on',
    'entity_movement_recommendation': 'created_on',
    'fc_entity_stock_ledger':         'created_on',
    'fc_entity_recommendation':       'created_on',
    'transferin_info':                'created_on',
}
```

Better still, the packing service holds each row's exact `created_on` in memory after
insert and passes it on every update — an exact partition hit rather than a window scan.

### 6.4 No station table — where the scale settings come from

Bluetooth pairing is an OS-level bond on the Zebra, done once by IT. The app opens SPP to
whatever `iScale-BT` device the handset is bonded to; it does not need a server-side MAC
registry. Tolerance, the gross-overage multiplier, the settle window and the weight-verify
floor come from a **config endpoint reading app config** (env vars), not a table — so tuning
tolerance is a redeploy of config, not a schema change or an APK release.

### 6.5 SKUs too light to weigh must be declared, not silently wrong

Requirements §2: at 10 g scale precision, single-unit detection needs items above ~20–30 g.
`weight_verifiable` is computed per SKU at job start (`unit_weight_kg × 1000 >=
weight_verify_floor_g`) and stored on the SKU row's JSON. The close response reports
`unverifiable_kg` — how much of the expected weight came from SKUs that cannot be
individually verified. A box of 5 g hinges passes a weight check that proves nothing; saying
so beats letting everyone downstream believe it was verified.

> **`product.weight` is nullable and its coverage is unknown. This is the one hard
> prerequisite for the module** — a picklist containing a SKU with no unit weight cannot be
> weight-reconciled at all. Run this before building:
>
> ```sql
> SELECT company_id,
>        COUNT(*)                           AS skus,
>        SUM(weight IS NULL OR weight <= 0) AS missing_weight,
>        SUM(weight > 0 AND weight < 0.030) AS below_verify_floor
> FROM product GROUP BY company_id;
> ```
>
> If coverage is poor the options are: hide those picklists from the pool, degrade the
> affected lines to scan-count-only, or capture unit weight during packing and write it back
> to `product.weight`. **This can invalidate the module for a given company** — §9 Q1.

### 6.7 The scanned code is a structured record, not a SKU

The two samples supplied:

```
single pc   D/GFSG0000604934/FCGS2T438AVJ/14610086000RS     /000001/0000100.00/ABH/1/G/000/00
full box    D/KH6G0000000344/DCGKM4WNNA4Z/14610086000RS/000200/0095.00/ABF/1/G/000/00HSVGHDEHCFGBWJHDCBGDCFHBICFHBEICFHEW
```

Eleven `/`-delimited fields in both. **Five of them are now confirmed against the printed
labels** (Hero MotoCorp retail pack and wholesale pack for part `14610086000RS`, *Roller Comp
Cam Chain*):

| # | single pc | full box | Reading | Evidence |
|---|---|---|---|---|
| 1 | `D` | `D` | format / record-type marker | constant; meaning unknown |
| 2 | `GFSG0000604934` | `KH6G0000000344` | **unique serial** — 4 alpha + 10 digits, not printed on the label | high, not confirmed |
| 3 | `FCGS2T438AVJ` | `DCGKM4WNNA4Z` | **UPI Code** — Hero's anti-counterfeit code | ✅ **printed**: "UPI Code: FCGS2T438AVJ" / "For Genuineness, SMS UPI Code DCGKM4WNNA4Z" |
| 4 | `14610086000RS·····` | `14610086000RS` | **part number** | ✅ **printed** on both labels, byte-identical |
| 5 | `000001` | `000200` | **net quantity** | ✅ **printed**: "NET QUANTITY: 1 NUMBER" / "NET QUANTITY: 200 NUMBER" |
| 6 | `0000100.00` | `0095.00` | **MRP** | ✅ **printed**: "MRP ₹100.00 INCL. OF ALL TAXES" on the retail pack |
| 7 | `ABH` | `ABF` | **batch number** | ✅ **printed**: "B. NO.: ABH" / "B.NO.: ABF" |
| 8–10 | `1` / `G` / `000` | `1` / `G` / `000` | constant across both | unknown |
| 11 | `00` | `00` + 38 more chars | trailer; only the wholesale code carries a payload | unknown |

**Correction to the earlier reading.** I had field 7 down as "batch, *or a pack-level
indicator*". The labels settle it: `B. NO.` is the batch number, on both packs. **There is no
pack-level field in the code** — nothing says "this is a wholesale pack". The only thing
distinguishing a box scan from a piece scan is the quantity in field 5. §6.7.3 depends on
this.

**And the differing MRP is explained, not anomalous.** ₹100.00 on batch `ABH` versus ₹95.00 on
batch `ABF` — two batches, two prices. That is exactly the rule the GRN design states for
`sku_batch`: *"MRP is part of batch identity… two MRPs mean two batches."* The scan carries
both the batch number and its MRP, so packing could populate `batch_id` per box rather than
leaving it at 0 — a real gain for FEFO and traceability, and free once the parse exists.

**Quantity is already in base units.** The wholesale label reads "NUMBER OF RETAIL PACKS
INSIDE: 200" and "NET QUANTITY: 200 NUMBER **(200 PACKS X 1 NUMBER)**" — 200 retail packs of 1
each. So field 5 is the base-unit count directly, and no `factor_to_base` multiplication is
needed *for this product*. A part packed "10 PACKS X 5 NUMBER" would still read 50 in field 5,
so the rule holds generally: **field 5 is base units, always.**

> **Neither sample is a mixed carton.** Both are single-SKU: one part number, one batch. So the
> multi-SKU carton case (§6.7.4 Gap 3) is still entirely unevidenced — nothing here shows what
> such a code looks like or whether Hero produces one at all.

> **The format is NOT fixed-width.** Field 4 is space-padded to 18 in the piece code and
> unpadded at 13 in the box code; field 6 is 10 characters in one and 7 in the other. **Split on
> `/` and trim every field — never slice by byte offset.** A parser written against the piece
> sample's offsets silently mis-reads every box code.

#### 6.7.1 Parse in both places; the server's answer is the one that counts

Same rule as the weight check (§6.2b), for the same reason.

- **The app parses locally** because it must. The live weight comparison needs to know a scan
  just added 200 units, not 1, and it has to know that on the next scale sample with no network.
- **The server re-parses from the raw string** because quantity is now attacker-supplied. A
  client that reports "this scan = 200 units" can be modified to report 2000, and the box would
  seal against an expected weight it chose for itself. **The server must never accept a
  client-declared quantity** — it derives it from `raw`, which it stores anyway.
- **The parse rules are served, not compiled in** — delivered per company through
  `/packing/config` (delimiter, field count, and the index of the product / quantity / serial /
  batch fields). One definition, and a format change for a new company is a config push rather
  than an APK release. Hero, Castrol and Ebco will not share Cadila's layout.

#### 6.7.2 What this changes in the design

| Change | Detail |
|---|---|
| **A scan is no longer worth 1 unit** | `picked_quantity` advances by the parsed quantity. `delta` becomes a signed quantity, not ±1. Requirements §6.1's "increments its packed count by one" holds only for piece codes. |
| **Scan volume collapses** | 200 units in one trigger pull. The batching pressure in §6.2 largely disappears for these SKUs — a 1,000-unit picklist can be five scans. Batching stays for the piece-code case. |
| **SKU resolution is extract-then-seek** | Never search for the scanned string in `product` — the composite code equals no `barcode` value, so a `LIKE '%…%'` or a scan of the catalogue is the only way it could ever "work", and on 60k rows that is exactly the expensive search to avoid. Extract field 4, trim, then do a plain equality lookup. Both target columns are already indexed — `uq_product_barcode (barcode)` and `idx_product_string (product_string)` — so it is an index seek. Costs and resolution caching are in §6.7.6. |
| **The weight-verify floor moves** | It should apply to `quantity × unit_weight` **per scan**, not to the unit weight alone. 200 × 5 g is a kilogram — highly verifiable — even though one 5 g item is not. This makes box-scanned SKUs verifiable that piece-scanning could not verify. |
| **Serials become the real duplicate check** | Field 2 uniquely identifies a physical pack. Scanning it twice is a duplicate with certainty, which `device_scan_uid` only approximates. |

#### 6.7.3 Two gaps this opens — both need answers before build

> **Gap 1 — weigh the thing that was scanned, not the units inside it.**
>
> The labels change how this should work. `expected = Σ(base_qty × product.weight)` is wrong the
> moment a wholesale pack is scanned: what physically goes into the shipping carton is **one
> cardboard box containing 200 polybagged retail packs**, not 200 bare rollers. The outer carton,
> the 200 polybags and the leaflet are all real mass that no per-unit figure accounts for. At
> 200 units, even a 2 g polybag is 400 g — eight times the entire ±50 g tolerance.
>
> The fix is to stop multiplying and start weighing the rung:
>
> ```
> expected  =  tare  +  Σ over scans ( gross weight of the rung scanned )
> base_qty  =  Σ over scans ( field 5 )
> ```
>
> Scan one wholesale pack → add **one** gross wholesale-pack weight. Scan four retail packs →
> add **four** gross retail-pack weights. Quantity and weight come from different properties of
> the same rung, and neither is derived from the other.
>
> `product_uom` is exactly the right home — it already models the ladder per product
> (`uom_code`, `factor_to_base`, `level_no`) — but it has **no weight column**:
>
> ```sql
> ALTER TABLE product_uom ADD COLUMN pack_gross_weight_kg DECIMAL(12,3) NULL;
> ```
>
> **And the ladder also tells you which rung was scanned**, with no new field in the barcode
> needed — which matters, because §6.7 establishes there *is* no pack-level field:
>
> ```sql
> SELECT uom_code, factor_to_base, pack_gross_weight_kg
> FROM product_uom
> WHERE product_id = %s AND factor_to_base = %s;   -- %s = field 5, e.g. 1 or 200
> ```
>
> Field 5 = `000001` matches the retail rung; `000200` matches the wholesale rung. The data we
> need for the quantity maths is the same data that identifies the rung for the weight maths.
>
> **Two things this leaves open.** Is `product.weight` today the *bare part* or the *packed
> retail unit*? At four units the polybag difference is a few grams and irrelevant; at 200 it is
> not — Q11. And two rungs sharing a `factor_to_base` would make the match ambiguous, though
> that would be an odd ladder.
>
> **Until `pack_gross_weight_kg` exists and is populated, weight verification cannot be switched
> on for any SKU scanned above the retail rung.**

> **Gap 2 — does serial-level traceability have to be queryable?**
> For pharma this is often regulatory: *which serials went to which dealer*. The current design
> keeps the scan trail in the box row's `source_stock_info` JSON, which is readable per box but
> **not searchable across boxes** — so "where did serial `KH6G0000000344` go?" would be a full
> scan of every packing JSON.
>
> If that question has to be answerable, the trail cannot stay JSON-only and this is where a
> table finally earns its place. If it does not, JSON is fine and nothing changes. **This is the
> one open question that could still add a table to the design.**

#### 6.7.4 A scan resolves to a *list* of (SKU, base quantity) — not to a SKU

A packer may scan a loose piece, a full box of one SKU, or **a carton holding several SKUs**.
So the primitive is not "which SKU did this scan add, and how many". It is:

```
resolve(raw)  →  [ {product_id, base_qty}, … ]  +  {packs: [{product_id, uom_code, count}]}
```

| What was scanned | Resolves to | Needs |
|---|---|---|
| loose piece | `[(P, 1)]` | parse only |
| full box, one SKU | `[(P, 200)]` | parse only |
| **mixed carton** | `[(P1, n1), (P2, n2), …]` | parse **+ a manifest lookup** |

Everything downstream then works on the resolved list, and nothing else in the design has to
know which of the three kinds it was:

- `picked_quantity` on each SKU row advances by that SKU's `base_qty`.
- `expected_weight` grows by `Σ(base_qty × unit_weight)` **plus** the `pack_weight_kg` of each
  physical pack scanned (Gap 1 below) — one carton's packaging, not one per SKU inside it.
- `over_quantity` is evaluated **for the whole list atomically**: if any line in a mixed carton
  would exceed its picklist quantity, the entire scan is rejected. A carton cannot be
  half-accepted, because the physical object either goes in the box or it does not.

**"Base quantity" is doing real work here.** The code's quantity field is expressed in whatever
unit the pack is, and `product_uom.factor_to_base` is what converts it. A code reading `000200`
means 200 *of that pack's unit* — which is 200 pieces if the pack is pieces, but 200 strips
(= 2,000 tablets) if the base unit is a tablet. **The resolver must convert to base units
before anything compares it to the picklist**, and it must know which UOM level the code's
quantity refers to. Field 7 (`ABH` vs `ABF`) is the candidate for that indicator — see Q10.

> **Gap 3 — where does a mixed carton's manifest come from?**
> A barcode cannot carry an arbitrary contents list; 38 trailing characters is not a manifest.
> So a mixed-carton code must be a **key**, and the system has to already know what is inside
> it before the packer scans it.
>
> **I have not found a table in this codebase that holds carton → contents.** `entity_type =
> 'CONTAINER'` exists in the production movement model (the GRN design records a CONTAINER
> being moved 11 → 6), but nothing maps a container to the SKUs and quantities within it.
>
> That manifest has to be written by whatever *builds* the carton — inbound (supplier ASN /
> aggregation data captured at GRN), or the picking flow if the warehouse picks into labelled
> cartons. **Picking is not built.** So if mixed cartons are picked-to-carton rather than
> received pre-mixed, this part of packing has a hard dependency on a flow that does not exist
> yet. **Q15 — this is the largest open item in the design.**
>
> If in practice a mixed carton is always *opened* at the bench and its contents scanned as
> pieces or single-SKU boxes, then no manifest is needed and this gap closes entirely. That is
> a question about how the warehouse actually works, not about the software.

#### 6.7.6 "Specific position" means field index, not byte offset — and the lookup is a seek

Two different things get called "a fixed position", and only one of them is safe here.

| | Works? | Why |
|---|---|---|
| **Field index** — split on `/`, take element 4 | ✅ **This is the design** | Both samples have 11 fields, and field 4 is the product in both |
| **Byte offset** — take characters 20–37 | ❌ | Field 4 is space-padded to 18 in the piece code and 13 in the box code; field 6 is 10 characters vs 7. A parser built on the piece sample's offsets silently mis-reads every box code — and mis-reading the *quantity* field means a box seals against the wrong expected weight. |

So `barcode_format` in `/packing/config` carries **field indexes**, not offsets, and the parser
splits and trims. That is what makes the resolution cheap: one `=` against an indexed column.

**And in the common case there is no lookup at all.**

- **On the device:** the job payload already contains every SKU on the picklist with its
  product code and unit weight. The app resolves the extracted code against that in-memory list
  — no query, no network, which is what lets the live weight check keep up with the trigger.
- **On the server:** resolve once per *distinct product code per batch*, not once per scan. A
  batch of 20 scans of the same SKU is one seek. The picklist's product codes can also be
  loaded once when the job is opened and held for the request, making the steady state zero
  lookups.

The only case that needs a real query is a code whose product is **not** on this picklist — and
that resolves to `not_in_picklist` or `unknown_sku`, both of which are rejections. Rejections
are rare by definition, so the expensive path is the one that almost never runs.

#### 6.7.5 Partial boxes

A picklist needing 150 units and a box code declaring 200 has no good automatic answer. Either
the packer opens the box and scans pieces, or packing needs a "scan the box, declare fewer"
path — which is a hole an anti-fraud module should be very careful about, since it lets a
packer assert a quantity the barcode contradicts. **Q12.** My recommendation is to reject the
box code with `over_quantity` and require piece scans for the remainder, so every declared
quantity always traces to a scanned code.

### 6.8 Two kinds of box: one the packer builds, one that arrives already built

An intact OEM wholesale carton **is a shipping box**. It never goes inside another carton, so
it must never be scanned *into* the open box — it becomes a box of its own, and the app must
create it automatically rather than making the packer run carton setup for something that is
already a sealed, labelled, known-contents unit.

| | **Built box** | **Intact carton** |
|---|---|---|
| Origin | packer assembles it at the bench | arrives sealed from the supplier |
| Identity (`entity_id`) | a pre-printed warehouse QR | **the carton's own code — field 2**, e.g. `KH6G0000000344` |
| Tare | **weighed** — empty carton on the scale | **read from master data** — the carton's own packaging weight |
| Contents | one SKU row per trigger pull | known from the scan, written in one go |
| Setup | tare → bind label → scan → close | **one scan creates it** |
| Consumes a warehouse label | yes | **no** |

Both are `entity_movement_details` rows with `entity_type = 'box'`. The kind is recorded in the
box JSON as `"kind": "built" | "intact"`. Everything downstream — the weight check, `box_count`,
the dispatch read, the submit write-back — treats them identically, which is the point.

> **`tare_weight_kg` means the same thing in both cases**, and that is what makes them
> interchangeable downstream: the weight of the packaging that is not stock. A built box weighs
> it on the scale because nobody knows it in advance; an intact carton reads it from master data
> because you cannot empty a sealed carton to find out. Same column, same arithmetic.

#### 6.8.1 The weight sum

Per your data — carton weight and SKU weight held separately — the expectation decomposes as:

```
expected  =  carton packaging weight  +  ( units × unit weight )
```

which is exactly `tare_weight_kg + Σ(base_qty × weight_kg)` — **the identical formula the built
box already uses** (§4.5). Nothing in the close path changes; only where `tare_weight_kg` comes
from changes.

This supersedes the "one gross weight per rung" model in §6.7.3 Gap 1. Your decomposition is
better for the same reason it is better for a built box: the packaging and the stock are
separately knowable, and separating them means a discrepancy tells you *which* of the two is
wrong.

The packaging weight belongs on the packaging ladder, which already exists per product:

```sql
ALTER TABLE product_uom ADD COLUMN pack_tare_kg DECIMAL(12,3) NULL;
```

and the rung is identified without any new barcode field — matching the scanned quantity
against the ladder, which works precisely because §6.7 established there *is* no pack-level
field in the code:

```sql
SELECT uom_code, factor_to_base, pack_tare_kg
FROM product_uom
WHERE product_id = %s AND factor_to_base = %s;    -- %s = field 5, e.g. 200
```

**An intact carton is still weighed.** The scan says what should be inside; the scale confirms
nothing was taken out before it reached the bench. That is the whole anti-fraud premise, and a
sealed carton is not exempt from it — a carton opened in transit and resealed is exactly the
case a weight check catches and a trusted OEM seal does not.

#### 6.8.2 Intact only when the whole carton is needed

A 200-unit carton cannot ship intact against a line needing 150. So:

```
carton quantity  ≤  remaining need for that SKU   →  ship intact, auto-create the box
carton quantity  >  remaining need                →  reject; the packer opens it and scans retail packs
```

**This also settles Q12** (partial boxes). There is no "scan the carton, declare fewer" path,
so every declared quantity still traces to a scanned code — the property an anti-fraud flow
cannot give up.

#### 6.8.3 Which endpoint gets the scan, and who decides

Two endpoints, each of which **rejects the other's input**:

| Endpoint | Accepts | Rejects |
|---|---|---|
| `POST /packing/jobs/{request_id}/cartons` | an intact carton code | a retail-pack code → `422 not_an_intact_carton` |
| `POST /packing/boxes/{box_id}/scans` | retail packs, loose pieces, undos | a carton code → `result: 'intact_carton'` with the hint to use `/cartons` |

The app routes locally off its own parse — it must, for the live display — but **the server
validates the routing on both sides**, so a modified client cannot post a carton code to
`/scans` and have 200 units absorbed into a hand-built box whose weight it then controls. The
mutual rejection is the enforcement; the app's routing is a convenience.

#### 6.8.4 One call, one box, already closed

There is nothing to add to an intact carton, so it does not pass through `setup` → `open` →
`sealed`. `POST /jobs/{request_id}/cartons` does the whole thing in one transaction: allocates
the next `box_no`, inserts the box row with `entity_id` = the carton's code, inserts one SKU row
per line of its contents, writes `tare_weight_kg` from the ladder and `expected_weight_kg` from
the sum, compares the supplied scale reading, and seals — or refuses with the same 409
`weight_mismatch` a built box gets.

**A built box may be open at the same time**, and is untouched. The packer can be halfway
through assembling box 3 when a full carton arrives; it becomes box 4 and box 3 stays open.

### 6.9 Audible and haptic feedback

The packer's eyes are on the carton and the parts, not on the handset. Sound is therefore not
decoration — for most of the packing loop it is the **only** channel actually being monitored.
Four rules follow from that, and one of them is a bug waiting to happen.

> ### ⚠️ Disable the Zebra's own decode beep first
> DataWedge beeps on **decode** — the instant the scanner reads a barcode, before the app has
> decided anything. That beep sounds positive and it fires on rejected scans too. A packer
> trains on the first sound they hear, so a "not in this picklist" scan produces a confident
> chirp and they move on; the app's rejection tone arrives afterwards, or is never noticed at
> all.
>
> **Turn the DataWedge beeper off and let the app be the only thing that makes a noise.** The
> hardware knows the barcode was read; only the app knows whether it counted. Those are
> different facts and they must not share a sound.

#### 6.9.1 Distinguish by rhythm, not by pitch

A warehouse floor runs 70–85 dB, much of it low-frequency machinery, and packers may be wearing
hearing protection. Two cues that differ only in pitch are indistinguishable in that
environment. **Humans discriminate temporal patterns far better than pitch under noise**, so
the count and spacing of pulses carries the meaning and pitch only reinforces it.

| Event | Sound | Haptic | Screen |
|---|---|---|---|
| **Scan accepted** | **1 ×** 40 ms @ 2.8 kHz | 30 ms tick | count increments, line flashes |
| **Intact carton accepted** | **2 ×** 40 ms rising, 2.4 → 3.0 kHz | 2 × 30 ms | a new sealed box card appears |
| **Scan rejected** — unknown SKU, not on picklist, over quantity | **2 ×** 70 ms @ 1.1 kHz | 200 ms buzz | red toast naming the reason |
| **Duplicate** | 1 × 70 ms @ 1.1 kHz, quieter | 100 ms | toast "already scanned" |
| **Excess weight — fraud lock** | **3 ×** 150 ms alternating 1.0 / 1.4 kHz, **repeating every 1.5 s until cleared** | 500 ms pulse each cycle | hero red, close disabled |
| **Excess cleared** | 1 × descending 1.2 → 0.8 kHz | 50 ms | hero returns to green |
| **Box sealed** | 3-note rising chime | 2 × 60 ms | confirmation screen |
| **Seal refused** | the excess pattern once, then the lock resumes | 400 ms | the 409 reason |

One blip means yes. Two means no. Three, over and over, means stop.

#### 6.9.2 The fraud alert is a state, not an event

This is the substantive difference between the third sound and the other two, and it is worth
building deliberately.

A scan verdict is an **event** — it happened, it gets one sound, it is over. Excess weight is a
**condition** that persists until someone fixes it. So its alert **repeats on a cycle while the
weight is out of tolerance and stops the instant it comes back in.**

That gives the packer something genuinely useful: they can pull items out of the carton and
**hear the moment it is correct again, without looking at the screen at all.** The silence is
the feedback. A one-shot alert cannot do that — it fires once, and then the packer is back to
guessing whether the thing they just removed was the right one.

It also means the alert must never be dismissible. There is no acknowledge button; the only way
to stop the sound is to fix the carton.

#### 6.9.3 Every cue fires on the local decision, never on the API response

Same rule as §6.2b, and for the same reason. The accepted tone must land within ~50 ms of the
decode, while a packer scanning twice a second is still holding the part. Waiting for the
`/scans` batch response would put the confirmation for one item somewhere after the next two
have already been scanned — worse than no sound, because it would be attributed to the wrong
item.

So the app plays every cue off its own local parse and its own weight comparison. The server's
verdict arrives later, in the batch response.

**Which creates one case that needs its own cue.** If the server's `result` disagrees with what
the app already signalled — it says `over_quantity` for a scan the app accepted and chimed for
— the packed count changes underneath a packer who has already been told it was fine. That
needs a **correction** cue (a distinct two-tone, 300 ms double-buzz, and a toast naming what
changed) rather than silently adjusting the number. Rare, but silent disagreement between what
someone was told and what was recorded is exactly the kind of thing that surfaces later as a
dispute.

#### 6.9.4 Practicalities

- **Sound and haptic always fire together.** Where hearing protection is worn, the vibration is
  the primary channel; where the handset is on a bench, the sound is. Neither is sufficient
  alone.
- **The fraud lock uses all three channels** — red screen, repeating tone, repeating vibration.
  It is the one cue that must not be missed.
- **Hold audio focus and pin the stream volume.** Android will otherwise duck the app for
  notifications, and a ducked fraud alert is an absent one.
- **Alert volume and repeat interval belong in `/packing/config`**, not in the APK — floors
  differ, and a tone that carries in one warehouse is inaudible in the next.
- **Nothing here needs a new endpoint.** The cues map onto the `result` values `/scans` already
  returns and onto the local weight state; the only server-side addition is the two config
  values above.

### 6.10 Closing an order short — the packer confirms, the server computes

Picking does not always deliver the full line. When it doesn't, packing cannot complete the
order, and the packer needs to close it anyway with the shortfall recorded as **not found**.

#### 6.10.1 The packer must not have to enumerate the shortfall

The shortfall is already known: `quantity_required − quantity_packed`, per SKU, from rows the
job itself wrote. Asking the packer to re-declare it is redundant typing at the end of a job
and a chance for the declaration to disagree with the packing record.

So `/submit` **derives** the shortfall. The packer's only input is an acknowledgement.

#### 6.10.2 The rejection is the confirmation dialog

Rather than a separate preview endpoint, an un-acknowledged submit against an incomplete order
**fails with the shortfall in the body**:

```jsonc
POST /packing/jobs/7701/submit   { }

409 { "code": "shortfall_requires_ack",
      "detail": "3 SKUs short. 12 units will be marked NOT FOUND and the order closed.",
      "shortfall": [
        { "sku_code": "14610086000RS", "name": "Roller Comp Cam Chain",
          "required": 200, "packed": 195, "short": 5 } ],
      "totals": { "required": 350, "packed": 338, "short": 12 } }
```

The app renders its confirmation from that body. Then:

```jsonc
POST /packing/jobs/7701/submit
  { "acknowledge_short": true, "reason_id": 5, "note": "picking short — bin A-12 empty" }
→ 200
```

**Three properties this shape buys, all of which matter for a record that closes an order:**

- **What the packer sees is what gets written.** The dialog is populated from the server's own
  computation, so the numbers they acknowledge are literally the numbers that will be recorded
  — not a client-side recalculation that could drift.
- **An accidental submit cannot close an order short.** Without `acknowledge_short` the call
  refuses, so a mis-tap at the end of a shift cannot mark fifty units not found.
- **No preview endpoint, and no window between preview and commit** in which the packed
  quantities could change.

A complete order needs no acknowledgement — the first call just succeeds.

**Reason is optional and applies to the whole submit** (`reason_id` against
`understack_reason`), with an optional per-SKU override. A packer finishing a job should not
face a form; one reason covers the usual case, which is that picking came up short.

#### 6.10.3 Status stays `Packed` — no new state

A short-packed order still goes to `Packed`. The state machine allows `Picking → Packed` and
nothing else from there, and `potential_order.short_pack_reason` already exists for exactly
this. **No state machine change, no new status** — resist the temptation to invent
"Packed Short", because every downstream consumer of the lifecycle would have to learn it.

What records the shortfall is: `quantity_packed < quantity` on the line, a **short EMD row**
(`source_bin_id = 0`, `underpick_reason_id` set), and `short_pack_reason` on the order.

> #### ⚠️ Gap 4 — marking units "not found" currently has no effect on the invoice
>
> Both invoicing paths copy the **ordered** quantity into the invoice, not the packed one:
>
> ```python
> # modules/fulfillment/invoice/repository.py:147 and :186
> SELECT potential_order_id, product_id, quantity, mrp, total_price, batch_id
> FROM potential_order_product …
> ```
>
> `quantity_packed` is never read. So a packer can mark 12 units not found, the order closes,
> and **the dealer is still invoiced for all 350** — billed for parts that never left the
> warehouse. That turns this feature from a control into paperwork, and it is a billing error
> in the customer's favour to notice, not ours.
>
> **The fix is in the invoice module, not this one**, so it needs that owner's agreement rather
> than a unilateral change here. The care needed: `quantity_packed` defaults to `0`, so an
> order that never passed through this app would zero out if the column were used blindly. The
> switch has to be conditional on a completed packing job existing for that order.
>
> **Do not treat this as out of scope.** Shipping the short-close flow without it produces
> confidently-recorded shortfalls that change nothing downstream — Q18.

#### 6.10.4 Zero packed is not a submit

If picking delivered nothing and the packer has packed no units at all, closing the order as
100% not found is almost certainly wrong: that is a picking failure, not a packing outcome, and
an order closed that way still flows to invoicing as an empty shipment.

**Recommendation:** block a submit with zero sealed boxes and route the picklist back to the
pool or to a supervisor instead. **Q19** — confirm this is the desired behaviour rather than
something the floor genuinely needs to do.

### 6.6 Job completion writes back to the order

On submit, in one transaction, **through `order.service` — never direct SQL** (the
cross-module boundary rule):

1. `potential_order_product.quantity_packed` per line; `quantity_remaining` = required − packed.
2. `potential_order.box_count` = number of sealed box rows. **Not decoration** — it is read
   when the invoice and the `order` row are created
   (`modules/fulfillment/invoice/repository.py:95`); a box count that never reaches it ships
   the default of `1` onto every invoice regardless of how many boxes physically exist.
3. `potential_order.status` → `Packed` + an `order_state_history` row.
   `Picking → Packed` is already legal in `OrderStateMachine.SINGLE_ORDER_TRANSITIONS` —
   no state-machine change, no new status.
4. `entity_movement_request.request_status` → `completed`.

---

## 7. Dispatch re-weigh — the read model (not built in v1)

Per D9: no request, no new table, nothing to create at the gate. The orders leaving the
warehouse are already known, so the check is a read against what packing already wrote:

```sql
-- every box on an order, with its sealed weight. no JSON anywhere.
SELECT d.id             AS box_id,
       d.entity_id      AS label_code,
       d.weight_kg      AS sealed_kg,
       d.expected_weight_kg,
       d.variance_g
FROM entity_movement_request r
JOIN entity_movement_details d ON d.request_id = r.id
WHERE r.movement_type    = 'packing'
  AND r.reference_type   = 'ORDER'
  AND r.request_identifier = %s          -- the order going out
  AND d.entity_type      = 'box'
  AND d.weight_kg IS NOT NULL            -- sealed boxes only
  AND d.created_on >= %s;                -- partition pruning
```

Compare the gate's measured weight against `weight_kg` within the same tolerance. Every value
the gate needs is a column — one index seek per order, no JSON parsing, which is what D7
buys.

**Scanning a label at the gate** resolves through `idx_emd_entity`:
`WHERE entity_id = 'WH1-000148213' AND entity_type = 'box'` — the same index the bind-time
single-use check uses.

**Two things to keep in mind when it is built.** Whether the verdict is *recorded* anywhere
is still open; today this design only reads. And if a held box needs an audit record, the
natural home is another `weight_events` entry appended to that box's JSON — no new table
either.

---

## 8. Why `entity_movement_recommendation` is not used

It was proposed for per-SKU acks (one row per SKU, updated as scanning proceeds, collapsed
into EMD at close). Rejected on three counts:

**It cannot hold the audit trail.** EMR's complete column list is `id, request_detail_id,
core_recommendation_id, parent_recommendation_id, understack_reason_id, recommendation_type
VARCHAR(32), sequence, quantity, created_by_id/on, updated_by_id/on`. There is **no text or
JSON column on it at all** — a raw barcode has nowhere to go, and there is no result column
to separate an accepted scan from a rejected one. The two things the trail must capture have
no home.

**It duplicates EMD.** The SKU rows are already EMD rows with `source_bin_id = box id`. A
parallel per-SKU quantity on EMR stores the same fact twice and needs reconciling at close.
Upserting the EMD SKU row directly during scanning is the same write count, one less table,
and no reconciliation step.

**It would carry a pointer to nothing.** `core_recommendation_id BIGINT UNSIGNED NOT NULL`
points at `fc_entity_recommendation`, the source→destination bin instruction. Packing has
none, so every packing row would store `0` — and every future reader of that table has to
know packing is the exception.

Packing generates no recommendations. Nothing is recommended to a packer: they are told what
the picklist needs and they scan it.

---

## 9. Open questions

Down from nine to five. Q1 is the only one that can invalidate the module.

| # | Question | Recommendation |
|---|---|---|
| **Q1** | **`product.weight` coverage per company.** | Run the §6.5 query **first**. It decides whether packing can go live per company at all. |
| **Q2** | `request_status`: use the existing `created / in_progress / saved / completed / cancelled`, or the literal `started` you named? | Existing vocabulary — picking and stacking share it. Constant change either way. |
| **Q3** | The demo logs in with **Packer ID + PIN**; this backend authenticates **email + password**. | Email + password for v1. A PIN needs its own lockout and rotation design; if shop-floor speed demands it, design it as a device-bound credential, not a shortened password. |
| **Q4** | `GET /api/v1/companies` returns no warehouse/location, but every packing endpoint needs `warehouse_id` and the company card shows a location. | Add `warehouses[]` to the existing response — additive, breaks no client. |
| **Q5** | Must a packer pack a **whole picklist from a cold start with no signal**? | Creating the job and opening a box both mint server-side ids, so today the answer is no. If yes is required, box identity must become a client-generated value — a schema change. **Decide before build.** |
| **Q6** | **Max carton label length** — `VARCHAR(64)` is sized on the assumption of `WH1-000148213`. A QR carrying a URL or GS1 payload would not fit. | Confirm the printed format before the ALTER. Re-sizing later is a second `ALGORITHM=COPY` rebuild. |
| **Q7** | Retyping `entity_id` fixes `router_v1.py:351` but leaves a standing rule: any join to `product.product_id` must cast. | Accept, and add a column comment. The alternative — retyping `entity_id` on all six inventory tables — is a much larger migration for no packing benefit. |
| **Q8** | Merge the two setup calls (tare, then bind) into one carrying both? | Merging removes the transient `entity_id=''`, one round trip and one UPDATE. It changes an API surface you have already reviewed, so it is your call. The two-call flow is what the contracts doc currently specifies. |
| **Q9** | **Stale boxes strand a picklist.** A box left `open` by a dead handset blocks `/save` and `/submit` for everyone. Is a resume-screen prompt enough for v1, or is a timeout sweep needed from day one? | Prompt for v1, sweep soon after. One dead device should not be able to freeze an order indefinitely. |
| **Q10** | **Barcode field map** — fields 3, 4, 5, 6, 7 are now **confirmed against the printed labels** (§6.7). Still unknown: field 1, field 2, fields 8–10, and the wholesale code's 38-character trailer. Is that trailer part of field 11, or a 12th field with a missing delimiter? | Enough is confirmed to build the parser. The trailer is the one piece that could still surprise us — get the printing spec for it. |
| **Q11** | **`product_uom.pack_tare_kg`** (§6.8.1) — you hold carton weight and SKU weight; this is where the carton weight lands, per packaging rung. Plus: is `product.weight` today the **bare part** or the **packed retail unit**? | Add the column and populate it. The `product.weight` question is a rounding error at 4 units and decisive at 200 — it needs an answer either way. |
| ~~Q12~~ | ~~Partial boxes~~ | **Resolved by §6.8.2.** A carton ships intact only when its full quantity is still needed; otherwise it is opened and scanned as retail packs. No "declare fewer" path. |
| **Q13** | **Must serial-level traceability be queryable** ("where did serial X go?"), or is per-box readability enough? | If queryable is required, the scan trail cannot stay JSON-only — this is the one question that could still add a table. |
| **Q14** | **Is `potential_order_product.quantity` in base units or order units?** The column has no UOM, but `product_uom` allows ordering by BOX or CASE. A scan resolving to 200 base units cannot be reconciled against a line meaning "2 cases" without `factor_to_base`. | Confirm before the quantity maths is written; it decides whether packing converts or compares directly. |
| **Q15** | **Where does a mixed carton's manifest come from?** (§6.7.4 Gap 3.) Nothing in this codebase maps a carton to the SKUs and quantities inside it. Neither supplied sample is a mixed carton — both are single-SKU. | If every intact carton is single-SKU (as both Hero samples are), §6.8 covers the whole flow and this gap never opens. Confirm that before designing for it. |
| **Q16** | **Does an intact carton get a warehouse QR label as well** (§6.8), or does the dispatch gate scan the OEM code on the box? | Use the OEM code — it is already unique, already printed, already on the carton, and it saves a label. Only needs settling if the gate hardware expects one label format. |
| **Q17** | **Is an intact carton physically weighable at the bench?** A 200-unit carton on a 400×400 mm, 100 kg platform. | Confirm with the station. If a full carton cannot go on the scale, the intact-carton weight check is unenforceable and §6.8.1 needs a different answer — this is a floor-plan question, not a software one. |
| **Q18** | **Invoicing bills the ordered quantity, not the packed one** (§6.10.3 Gap 4). Marking units not found currently changes nothing on the invoice. | Must be fixed with the short-close flow, in the invoice module, conditional on a completed packing job so orders that never used this app are unaffected. Without it the feature is paperwork. |
| **Q19** | **Should a submit with zero packed units be allowed?** Picking delivered nothing; closing the order 100% not found sends an empty shipment to invoicing. | Block it and route back to the pool or a supervisor. Confirm the floor does not genuinely need it. |

---

## 10. Build order

1. **Answer Q1, Q5 and Q6.** Q1 can kill the module for a company, Q5 can change box identity,
   Q6 sizes a column that is expensive to resize later.
2. Register the movement tables in `PARTITION_COLUMN` (§6.3). One line, helps picking too.
3. **Run the §4.6 ALTER while `entity_movement_details` is still empty**, and fix
   `modules/inventory/router_v1.py:351` in the same change.
4. Grant `inventory:pack` to a new `packer` role.
5. `service.py` + `router_v1.py` in `modules/fulfillment/packing/`. **No `schema.py`** — this
   module registers no tables.
6. Reads first: config, pool, picklist detail. Screens 1–5 build against these alone.
7. Job + box setup: create request, create box row, bind label.
8. Batched `/scans` and `/close` — **with the server-side tolerance check in the first
   commit**, not added later. The flow working without it is the bug.
9. `/save`, `/submit`, `/abandon`, plus the `order.service` write-back.
10. Update `AI_CONTEXT.md`: packing is a new module in the `fulfillment` cluster that owns
    **no tables** and rides the inventory-owned movement engine.
