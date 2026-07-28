# Inventory — GRN, Stacking and Picking on the movement engine (DRAFT)

**Status: DRAFT for review. Nothing has been created or dropped yet.**

Two flows run on one engine:

- **GRN → stacking** — an invoice is scanned, stock lands unstacked, a stacking job puts
  it into primary/secondary/bulk bins.
- **Order → picking** — an order generates one picking job; the user follows
  recommendations, picks from bins, and completes.

Both are `entity_movement_request` + `entity_movement_details` + recommendations. Only
`movement_type` and the direction of stock differ.

**Hard constraint:** the existing order-tracking lifecycle
(`Open → Picking → Packed → Invoiced → Dispatch Ready → Completed`) must not change.
Picking becomes execution detail *underneath* the `Picking` state, not a replacement for it.

Column names and types are kept **identical to the production tables** so the app can
point at this backend without a client change.

---

## 1. GRN flow (inbound)

### 1.1 Scan the invoice (catalog)
The app scans an invoice. Its line items go to **catalog** first, which checks the **MRP**
and creates/resolves a **batch** per SKU, returning a `batch_id`.
> Batch tables are owned by catalog and will be supplied separately.

### 1.2 Receive into unstacked (inventory)
Inventory is handed the **invoice id as `transferin_id`**, plus per line `entity_id` (sku),
`entity_type`, `batch_id`, `quantity`, `cost_price`, `mrp`.

Receiving writes **two** things, in one transaction:

1. One **`transferin_info`** row per line:
   - `quantity` = received qty (never changes)
   - `unstacked_quantity` = still waiting to be stacked (decrements)
   - `transferin_status` = `received`, `vbin_id` = virtual bin (`0` when none)
2. An **`fc_entity_stock`** row at **`location_id = 8` (unstacked)**, upserted per
   sku + batch — so the stock is immediately visible as on-hand and pickable.

Nothing is ever deleted from `transferin_info` — it is the permanent record of what
arrived. The location-8 stock row *is* deleted once fully stacked. See the sync invariant
in §4.2.

### 1.3 Stacking job
An **`entity_movement_request`** is created (`movement_type = 'sku-stacking'`,
`request_status = 'created'`), `metadata` carrying priority/stacking groups and
`request_identifier` + `reference_type` pointing at the external job (e.g. `HERMES_JOB_ID`).

The user scans a SKU and adds quantity → an **`entity_movement_details`** (EMD) row:
`source_location_id` = unstacked, `source_bin_id` = 0, `picked_quantity`, and
`source_stock_info` (JSON) recording which `transferin_info` rows it drew from.

That qty moves **unstacked → in-process**, and `transferin_info.unstacked_quantity` drops.

### 1.4 Recommend and acknowledge
Per EMD and quantity, the system generates:
- **`fc_entity_recommendation`** — the *core* instruction: source → destination
  location/bin, `operation` (`add`/`remove`), `batch_id`, `qty_to_process`,
  `qty_processed`, `status`. Shared across request types.
- **`entity_movement_recommendation`** (EMR) — links `request_detail_id` →
  `core_recommendation_id`, plus `parent_recommendation_id`, `recommendation_type`,
  `sequence`, `quantity`.

The user acknowledges each quantity → stock lands in a **primary / secondary / bulk** bin.

```
invoice scan ──► catalog (MRP + batch)
                     │ batch_id
                     ▼
              transferin_info              (unstacked · immutable · qty vs unstacked_quantity)
                     │ stacking job
                     ▼
        entity_movement_request ──► entity_movement_details      (unstacked → in-process)
                                              │
                                              ▼
                            entity_movement_recommendation ──► fc_entity_recommendation
                                                                    │ user acks qty
                                                                    ▼
                                                          primary / secondary / bulk bin
```

---

## 2. Picking flow (outbound, order-driven)

**One order → one picking job.** The order module owns *when* a picking job exists; the
inventory module owns the tables and the stock movement.

1. An order needs picking (web order moves to `Picking`; an app order after approval).
   `order.service` calls `inventory.service.create_picking_request(...)`.
2. An **`entity_movement_request`** is created with `movement_type = 'picking'` and the
   order carried on the columns already built for exactly this:
   - `reference_type = 'ORDER'`
   - `request_identifier = potential_order_id`

   No join table is needed, and no column is added to the order tables.
3. One **`entity_movement_details`** row per order line — what has to be picked.
4. Recommendations tell the user **which bin to pick from**: a **`fc_entity_recommendation`**
   per source (`operation = 'remove'`, `request_type = 'picking'`), linked to the EMD
   through **`entity_movement_recommendation`**.

   **Picking has two possible sources**, since `unstacked` is picking-enabled alongside
   `primary`. Both are read from `fc_entity_stock` — see the invariant in §4.2:

   | Source | Read from | Ordered by |
   |---|---|---|
   | `primary` (1) | `fc_entity_stock` rows in pick-face bins | `bin_priority_order`, then batch expiry (FEFO) |
   | `unstacked` (8) | `fc_entity_stock` rows at location 8; `transferin_info` gives the per-inbound breakdown | `bin_priority_order` — FIFO by inbound |

   Batch params drive the choice: expiry gives FEFO, so the recommendation engine reads
   `sku_batch` when ranking candidates.
5. The user follows each recommendation and acknowledges the picked quantity →
   `qty_processed` rises, `fc_entity_stock` is decremented at that bin (**row deleted when
   the bin empties**), and `fc_entity_stock_ledger` gets an entry with
   `reference_type = 'picking'`.
6. On completion, inventory calls back into `order.service.apply_fulfillment(...)` — the
   existing function — which writes `quantity_fulfilled` / `item_status` on the order lines
   and advances the order. **This is the only touch-point with order tracking, and it is
   the same call that exists today.**

```
order (Picking) ──► entity_movement_request  movement_type='picking'
                    reference_type='ORDER', request_identifier=potential_order_id
                              │
                              ▼
                    entity_movement_details          (one per order line)
                              │
                              ▼
            entity_movement_recommendation ──► fc_entity_recommendation  (which bin)
                              │ user picks + acks
                              ▼
                    fc_entity_stock  ▼qty   +   fc_entity_stock_ledger
                              │
                              ▼
              order.service.apply_fulfillment()  →  order lines + status
```

### Why the tables stay in `inventory` even though the flow belongs to `order`
`entity_movement_request` and its details/recommendations are **shared** by stacking,
picking and stock moves. If they moved into the order module, the stacking flow — which has
nothing to do with orders — would be reaching into order-owned tables, breaking the
own-your-tables rule the rest of this codebase follows.

So: **tables owned by `inventory`; the picking flow orchestrated from `order`**, through
`inventory.service`. That is the same shape already used today (order approval calls
`inventory.generate_picklist`, picking completion calls back `order.apply_fulfillment`).
If you'd rather the tables physically live in `modules/order/`, say so — it's a one-line
change to where the DDL is registered, but stacking then crosses the boundary.

---

## 3. Table-by-table verdict

Applying your rule — *replace where it's the same thing, keep both where it isn't*:

### Replace and drop the old (same concept, finer grain)
| Old table | Replaced by | Note |
|---|---|---|
| `stock` | `fc_entity_stock` | Same idea at bin + batch level instead of warehouse + sku. |
| `inventory_transactions` | `fc_entity_stock_ledger` | Both are the append-only ledger. |
| `picklists` | `entity_movement_request` (`movement_type='picking'`) | The picking job header. |
| `picklist_items` | `entity_movement_details` + `entity_movement_recommendation` + `fc_entity_recommendation` | Old table had no concept of *which bin*; that's the whole point of the new one. |

### Keep unchanged (different concept — demand vs execution)
| Table | Why it stays |
|---|---|
| `potential_order`, `potential_order_product` | The order itself — what the customer wants. The movement engine records how it was executed. Untouched. |
| `order`, `order_product` | Confirmed order records written at invoicing. Untouched. |
| `order_state`, `order_state_history` | The tracking lifecycle and its audit trail. **Unchanged — no new statuses.** |
| `warehouse` | Stays; `planogram_id` = `warehouse.warehouse_id` (default 1). |
| `invoice`, `company`, `dealer`, `product` | Unrelated to movement. |

### Recommend dropping (redundant scaffold)
| Table | Why |
|---|---|
| `jobs`, `job_status_history`, `worker_availability`, `allocation_policies` | The `assignment` module was scaffolded but never implemented; `entity_movement_request` **is** the warehouse job queue. Keeping both would mean two competing definitions of "a unit of work". Your call — worker availability may still be worth keeping if you want auto-assignment later. |

### What this does *not* touch
The web order-tracking screens, the bulk status upload, the state machine, and the
`Open → Picking → Packed → …` chain all keep working exactly as they do now. The picking
job hangs off the order by `request_identifier`; the order tables gain no columns.

---

## 4. Tables

### 4.1 `transferin_info` — inbound GRN lines (never deleted)
```sql
CREATE TABLE transferin_info (
  id                  bigint unsigned NOT NULL AUTO_INCREMENT,
  planogram_id        bigint unsigned NOT NULL,
  transferin_id       bigint unsigned NOT NULL,   -- the scanned invoice id
  transferin_type_id  bigint unsigned NOT NULL,
  entity_id           bigint unsigned NOT NULL,
  entity_type         varchar(32)     NOT NULL,   -- 'sku'
  batch_id            bigint unsigned NOT NULL,   -- from catalog
  quantity            decimal(16,4)   NOT NULL,   -- received (immutable)
  unstacked_quantity  decimal(12,4)   NOT NULL,   -- still to stack (decrements)
  vbin_id             bigint unsigned NOT NULL,
  cost_price          decimal(12,4)   NOT NULL,
  mrp                 decimal(12,4)   NOT NULL,
  transferin_status   varchar(32)     NOT NULL,   -- 'received'
  meta_info           varchar(500)    NOT NULL,
  created_by_id       bigint unsigned NOT NULL,
  created_on          datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on          datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by_id       bigint unsigned NOT NULL,
  PRIMARY KEY (id, created_on),
  KEY planogram_id_3 (planogram_id, transferin_type_id, transferin_id),
  KEY planogram_id_5 (planogram_id, transferin_type_id, transferin_id, entity_id, entity_type),
  KEY idx_planogram_entity_etype (planogram_id, entity_id, entity_type),
  KEY idx_tid_entity_vbin (transferin_id, entity_id, vbin_id)
) ENGINE=InnoDB;
```

### 4.2 `fc_entity_stock` — live stock per bin + batch (row deleted when empty)
```sql
CREATE TABLE fc_entity_stock (
  id                 bigint unsigned NOT NULL AUTO_INCREMENT,
  planogram_id       int unsigned     NOT NULL,
  location_id        tinyint unsigned NOT NULL,
  bin_id             bigint unsigned  NOT NULL DEFAULT 0,
  bin_location       varchar(255)     NOT NULL,
  entity_id          int unsigned     NOT NULL,
  entity_type        varchar(255)     NOT NULL,
  batch_id           bigint unsigned  NOT NULL,
  bin_priority_order bigint unsigned  NOT NULL,
  quantity           decimal(12,4)    NOT NULL,
  created_by         varchar(255)     NOT NULL,
  created_on         datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on         datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by         varchar(255)     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY planogram_id_new (planogram_id, location_id, bin_id, entity_id, entity_type, batch_id),
  KEY planogram_id_2 (planogram_id, location_id, bin_id, entity_id),
  KEY planogram_id_3 (planogram_id, location_id, entity_id),
  KEY planogram_id_4 (planogram_id, entity_id),
  KEY idx_planogram_bin (planogram_id, bin_id)
) ENGINE=InnoDB;
```
Not partitioned — a live working set, kept small by deleting empty rows. The unique key is
what makes upsert-or-create safe under concurrency.

> ### ⚠️ Invariant: unstacked stock lives in *both* places, and they must stay in sync
>
> `fc_entity_stock` holds a row at **`location_id = 8` (unstacked)** as well as the
> stacked bins. So it is the **complete** picture of on-hand:
>
> ```
> total on hand  =  SUM(fc_entity_stock.quantity)      -- unstacked included
> ```
>
> **Never add `transferin_info.unstacked_quantity` to that — it would double-count.**
> The two describe the same physical stock from different angles:
>
> | | Grain | Answers |
> |---|---|---|
> | `fc_entity_stock` @ 8 | per sku + batch | *how much* unstacked stock exists |
> | `transferin_info.unstacked_quantity` | per inbound line | *which GRN* it came from (FIFO, traceability) |
>
> **Every stacking (or pick-from-unstacked) must decrement both**, in the same
> transaction: reduce `transferin_info.unstacked_quantity` on the source inbound line(s),
> and reduce the location-8 `fc_entity_stock` row — deleting that row once it reaches
> zero. If the two ever diverge, on-hand is wrong; a reconciliation check
> (`SUM(unstacked_quantity)` per sku+batch vs the location-8 row) is worth having.

### 4.3 `fc_entity_stock_ledger` — append-only audit of every change
```sql
CREATE TABLE fc_entity_stock_ledger (
  id                    bigint unsigned NOT NULL AUTO_INCREMENT,
  planogram_id          int unsigned     NOT NULL,
  location_id           tinyint unsigned NOT NULL,
  bin_id                bigint unsigned  NOT NULL DEFAULT 0,
  bin_location          varchar(255)     NOT NULL,
  entity_id             int unsigned     NOT NULL,
  entity_type           varchar(255)     NOT NULL,
  batch_id              bigint unsigned  NOT NULL,
  quantity_changed      decimal(12,4)    NOT NULL,   -- signed
  quantity_after_change decimal(12,4)    NOT NULL,
  reference_id          bigint unsigned  NOT NULL,
  reference_type        varchar(255)     NOT NULL,   -- 'picking' | 'stacking' | ...
  created_by            varchar(255)     NOT NULL,
  created_on            datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on            datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by            varchar(255)     NOT NULL,
  cost_price            decimal(12,4)    DEFAULT NULL,
  created_on_epoch      bigint unsigned  DEFAULT NULL,
  PRIMARY KEY (id, created_on),
  KEY idx_planogram_entity_reference (planogram_id, entity_id, reference_id),
  KEY idx_created_planogram_entity (updated_on, planogram_id, entity_id),
  KEY idx_partition_filter (planogram_id, entity_id, entity_type, bin_id, location_id, bin_location, batch_id, created_on)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(created_on) (...);
```

### 4.4 `entity_movement_request` — the job header (stacking, picking, moves)
```sql
CREATE TABLE entity_movement_request (
  id                 bigint unsigned NOT NULL AUTO_INCREMENT,
  planogram_id       int unsigned    NOT NULL,
  movement_type      varchar(32)     NOT NULL,   -- 'sku-stacking' | 'picking' | ...
  request_status     varchar(32)     NOT NULL,   -- 'created' | ...
  meta_info          varchar(500)    NOT NULL,
  created_by_id      bigint unsigned NOT NULL,
  created_on         datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on         datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by_id      bigint unsigned NOT NULL,
  metadata           json DEFAULT NULL,
  request_identifier bigint DEFAULT NULL,        -- picking: potential_order_id
  reference_type     varchar(500) DEFAULT '',    -- picking: 'ORDER'
  PRIMARY KEY (id, created_on),
  KEY planogram_id (planogram_id, movement_type),
  KEY planogram_id_2 (planogram_id, movement_type, request_status),
  KEY planogram_reqid_reftype (planogram_id, request_identifier, reference_type)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(created_on) (...);
```
`planogram_reqid_reftype` is exactly the index needed for "the picking job for order X".

### 4.5 `entity_movement_details` — lines within a request
```sql
CREATE TABLE entity_movement_details (
  id                  bigint unsigned NOT NULL AUTO_INCREMENT,
  request_id          bigint unsigned NOT NULL,
  entity_id           bigint unsigned NOT NULL,
  entity_type         varchar(32)     NOT NULL,
  source_bin_id       bigint unsigned NOT NULL,   -- 0 when from unstacked
  source_location_id  bigint unsigned NOT NULL,
  picked_quantity     decimal(16,4)   NOT NULL,
  underpick_reason_id bigint unsigned NOT NULL,
  source_stock_info   text            NOT NULL,   -- JSON, see below
  created_by_id       bigint unsigned NOT NULL,
  created_on          datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on          datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by_id       bigint unsigned NOT NULL,
  PRIMARY KEY (id, created_on),
  KEY request_id (request_id),
  KEY request_id_2 (request_id, entity_id, entity_type),
  KEY idx_request_source (request_id, source_bin_id)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(created_on) (...);
```
`source_stock_info` as seen in production:
```json
{ "request_identifier_list": ["..."],
  "source_stock_list": [
    { "bin_id": 0, "bin_loc": "", "batch_id": 3579, "quantity": 4,
      "picked_quantity": 4, "bin_priority_order": 59406912,
      "transferin_info_id": 2625898775 }
  ],
  "total_unstacked_quantity": 4 }
```

### 4.6 `entity_movement_recommendation` — per-detail recommendation links
```sql
CREATE TABLE entity_movement_recommendation (
  id                       bigint unsigned NOT NULL AUTO_INCREMENT,
  request_detail_id        bigint unsigned NOT NULL,   -- -> entity_movement_details.id
  core_recommendation_id   bigint unsigned NOT NULL,   -- -> fc_entity_recommendation.id
  parent_recommendation_id bigint unsigned NOT NULL,   -- chained moves, 0 if root
  understack_reason_id     bigint unsigned NOT NULL,
  recommendation_type      varchar(32)     NOT NULL,   -- 'regular'
  sequence                 bigint DEFAULT 0,
  created_by_id            bigint unsigned NOT NULL,
  created_on               datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on               datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by_id            bigint unsigned NOT NULL,
  quantity                 decimal(12,4) NOT NULL DEFAULT 0.0000,
  PRIMARY KEY (id, created_on),
  KEY request_detail_id (request_detail_id),
  KEY request_detail_id_2 (request_detail_id, recommendation_type),
  KEY idx_parent_recommendation_id (parent_recommendation_id)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(created_on) (...);
```

### 4.7 `fc_entity_recommendation` — the core source→destination instruction
```sql
CREATE TABLE fc_entity_recommendation (
  id                       bigint unsigned NOT NULL AUTO_INCREMENT,
  planogram_id             int unsigned    NOT NULL,
  entity_id                int unsigned    NOT NULL,
  entity_type              varchar(255)    NOT NULL,   -- 'sku' | 'CONTAINER'
  source_location_id       int unsigned    NOT NULL,
  destination_location_id  int unsigned    NOT NULL,
  source_bin_id            bigint unsigned NOT NULL,
  destination_bin_id       bigint unsigned NOT NULL,
  source_bin_location      varchar(255)    NOT NULL,
  destination_bin_location varchar(255)    NOT NULL,   -- e.g. 'Z-03-C-2'
  request_id               bigint unsigned NOT NULL,
  request_type             varchar(255)    NOT NULL,   -- 'binning' | 'picking' | ...
  operation                varchar(255)    NOT NULL,   -- 'add' | 'remove'
  batch_id                 bigint unsigned NOT NULL,
  bin_priority_order       bigint unsigned NOT NULL,
  qty_to_process           decimal(12,4)   NOT NULL,
  qty_processed            decimal(12,4)   NOT NULL,
  status                   varchar(255)    NOT NULL,
  created_by               varchar(255)    NOT NULL,
  created_on               datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_on               datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by               varchar(255)    NOT NULL,
  PRIMARY KEY (id, created_on),
  KEY idx_planogram_entity_source_bin (planogram_id, entity_id, source_bin_id),
  KEY idx_status (status),
  KEY idx_planogram_request_type (planogram_id, request_id, request_type)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(created_on) (...);
```

### 4.8 Warehouse topology — where `bin_id` comes from

The topology is a **template / instance** split. Templates describe a *kind* of rack once;
the `fc_*` tables are the physical instances standing in a warehouse.

```
TEMPLATES (reusable definitions)          INSTANCES (this warehouse, physical)
────────────────────────────────          ────────────────────────────────────
racktype                                  fc_planogram        (1:1 with an FC)
   └─► rack_variant  ──────────────────►     └─► fc_floor
          └─► rack_shelf  ─────────────►          └─► fc_aisle
                 └─► rack_shelf_bin ───►               └─► fc_rack        →rack_variant
                                                            └─► fc_rack_shelf   →rack_shelf
                                                                 └─► fc_rack_shelf_bin →rack_shelf_bin
                                                                        │
                                                               id = the bin_id
                                                               binloc = 'Z-03-C-2'
```

So a bin's *dimensions and capacity* come from the template (`rack_shelf_bin`), while its
*identity, location and contents* come from the instance (`fc_rack_shelf_bin`).

**`fc_rack_shelf_bin.id` *is* the `bin_id`** used by `fc_entity_stock`,
`fc_entity_stock_ledger`, `fc_entity_recommendation` and `entity_movement_details`.
Its `binloc` is the `bin_location` string carried on those rows.

Two things this settles:
- **Virtual bins are not a separate table.** A vbin is a row here with
  `bin_type = 'vbin'` (your sample had `fc_rack_shelf_id = 0`, `binloc = ''`, so it hangs
  off no physical shelf). `transferin_info.vbin_id` therefore also points at
  `fc_rack_shelf_bin.id`.
- **`location_id` lives on the bin**, as well as being denormalised onto every stock,
  ledger and recommendation row. The bin is the authority; the copies make queries cheap.

Also note `stacking_group_id` on the bin — it pairs with the `stacking_group_list` carried
in `entity_movement_request.metadata`, which is how a stacking job knows which bins it may
put stock into.

```sql
CREATE TABLE fc_planogram (
  id                 int unsigned NOT NULL AUTO_INCREMENT,
  wh_code            varchar(16) NOT NULL,
  fc_id              int unsigned DEFAULT 0,
  dc_id              int unsigned NOT NULL,
  num_of_floors      tinyint NOT NULL,
  is_active          tinyint(1) DEFAULT 1,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_by varchar(32) NOT NULL,
  updated_by varchar(32) NOT NULL,
  planogram_mode_id  int unsigned NOT NULL DEFAULT 1,
  dispatch_bin_floor tinyint unsigned DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY unique_fc_id (fc_id),          -- one planogram per FC
  KEY idx_dc_id (dc_id),
  KEY idx_fc_id_is_active (fc_id, is_active),
  KEY idx_wh_code (wh_code)
) ENGINE=InnoDB;

CREATE TABLE fc_floor (
  id              int unsigned NOT NULL AUTO_INCREMENT,
  fc_planogram_id int unsigned NOT NULL,
  floor_seq       tinyint unsigned NOT NULL,
  num_of_aisles   mediumint unsigned NOT NULL,
  is_active       tinyint(1) NOT NULL DEFAULT (true),
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  floor_capacity  int NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY planogram_floor_unique (fc_planogram_id, floor_seq),
  CONSTRAINT fk_planogram FOREIGN KEY (fc_planogram_id) REFERENCES fc_planogram (id)
) ENGINE=InnoDB;

CREATE TABLE fc_aisle (
  id                 int unsigned NOT NULL AUTO_INCREMENT,
  fc_floor_id        int unsigned NOT NULL,
  aisle_name         varchar(4)  NOT NULL,
  aisle_facing_group varchar(2)  NOT NULL,
  aisle_facing       varchar(2)  NOT NULL,
  aisle_seq          tinyint unsigned NOT NULL,
  aisle_start_pos    point DEFAULT NULL,
  aisle_end_pos      point DEFAULT NULL,
  is_active          tinyint(1) DEFAULT 1,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY floor_aisle_unique (fc_floor_id, aisle_name),
  CONSTRAINT fk_fc_floor FOREIGN KEY (fc_floor_id) REFERENCES fc_floor (id)
) ENGINE=InnoDB;

CREATE TABLE fc_rack (
  id                     int unsigned NOT NULL AUTO_INCREMENT,
  fc_aisle_id            int unsigned NOT NULL,
  rack_variant_id        int unsigned DEFAULT 0,
  rack_seq               decimal(12,4) DEFAULT NULL,
  gap_length             decimal(12,4) DEFAULT (0),
  num_of_picking_shelves int unsigned NOT NULL,
  start_pos              point DEFAULT NULL,
  end_pos                point DEFAULT NULL,
  is_active              tinyint(1) DEFAULT 1,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY fc_aisle_id (fc_aisle_id, rack_seq),
  CONSTRAINT fc_rack_chk_1 CHECK ((gap_length >= 0))
) ENGINE=InnoDB;

CREATE TABLE fc_rack_shelf (
  id            int unsigned NOT NULL AUTO_INCREMENT,
  fc_rack_id    int unsigned NOT NULL,
  shelf_level   varchar(16)  NOT NULL,     -- 'Upper', ...
  rack_shelf_id int unsigned NOT NULL,     -- -> rack_shelf template
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  KEY fk_fc_rack (fc_rack_id),
  KEY fk_rack_shelf_fc_rack_shelf (rack_shelf_id),
  CONSTRAINT fk_fc_rack FOREIGN KEY (fc_rack_id) REFERENCES fc_rack (id),
  CONSTRAINT fk_rack_shelf_fc_rack_shelf FOREIGN KEY (rack_shelf_id) REFERENCES rack_shelf (id)
) ENGINE=InnoDB;

CREATE TABLE fc_rack_shelf_bin (
  id                bigint unsigned NOT NULL AUTO_INCREMENT,   -- == bin_id
  fc_rack_shelf_id  int unsigned     NOT NULL,                 -- 0 for a vbin
  planogram_id      int unsigned     NOT NULL,
  location_id       tinyint unsigned NOT NULL,
  rack_shelf_bin_id int unsigned     NOT NULL,                 -- -> rack_shelf_bin template
  available_volume  decimal(12,4)    NOT NULL,
  max_sku_allowed   tinyint unsigned DEFAULT NULL,
  stacking_group_id int unsigned     NOT NULL DEFAULT (0),
  is_static         tinyint(1) DEFAULT 0,
  is_active         tinyint(1) DEFAULT 1,
  binloc            varchar(32) NOT NULL,                      -- == bin_location
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  bin_metainfo json DEFAULT NULL,
  bin_type     varchar(255) DEFAULT 'bin',                     -- 'bin' | 'vbin'
  PRIMARY KEY (id),
  KEY fk_fc_rack_shelf (fc_rack_shelf_id),
  KEY planogram_id_idx (planogram_id),
  KEY idx_binloc_planogram_id_location_id (binloc, planogram_id, location_id),
  KEY idx_id_planogram_id (id, planogram_id)
) ENGINE=InnoDB;
```

**Rack templates** — the reusable definitions the `fc_*` instances point at:

```sql
CREATE TABLE racktype (
  id                 int unsigned NOT NULL AUTO_INCREMENT,
  racktype_name      varchar(5) NOT NULL,        -- 'S1A'
  is_active          tinyint(1) DEFAULT 1,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_by varchar(32) NOT NULL,
  updated_by varchar(32) NOT NULL,
  planogram_location varchar(20) DEFAULT NULL,   -- -> planogram_locations.location_type
  PRIMARY KEY (id),
  UNIQUE KEY racktype_name (racktype_name)
) ENGINE=InnoDB;

CREATE TABLE rack_variant (
  id                     int unsigned NOT NULL AUTO_INCREMENT,
  racktype_id            int unsigned NOT NULL,
  rack_variant_name      varchar(5) NOT NULL,        -- 'FB3'
  rack_len               decimal(12,4) NOT NULL,
  rack_width             decimal(12,4) NOT NULL,
  rack_height            decimal(12,4) NOT NULL,
  num_of_shelves         tinyint unsigned NOT NULL,
  num_of_picking_shelves tinyint unsigned NOT NULL,
  is_active              tinyint(1) DEFAULT 1,
  created_by varchar(32) NOT NULL,
  created_on datetime NOT NULL,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY rack_variant_name (rack_variant_name),
  KEY fk_racktype (racktype_id),
  CONSTRAINT fk_racktype FOREIGN KEY (racktype_id) REFERENCES racktype (id),
  CONSTRAINT rack_variant_chk_1 CHECK ((rack_len > 0)),
  CONSTRAINT rack_variant_chk_2 CHECK ((rack_width > 0)),
  CONSTRAINT rack_variant_chk_3 CHECK ((rack_height > 0))
) ENGINE=InnoDB;

CREATE TABLE rack_shelf (
  id              int unsigned NOT NULL AUTO_INCREMENT,
  rack_variant_id int unsigned NOT NULL,
  shelf_name      varchar(1) NOT NULL,          -- 'G'
  shelf_seq       tinyint unsigned NOT NULL,
  shelf_length    decimal(12,4) NOT NULL,
  shelf_width     decimal(12,4) NOT NULL,
  shelf_height    decimal(12,4) NOT NULL,
  is_hole         tinyint(1) DEFAULT 0,
  num_of_bins     tinyint unsigned NOT NULL,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY rack_variant_shelf_unique (rack_variant_id, shelf_name),
  CONSTRAINT fk_rack_variant_shelf FOREIGN KEY (rack_variant_id) REFERENCES rack_variant (id),
  CONSTRAINT rack_shelf_chk_1 CHECK ((shelf_length > 0)),
  CONSTRAINT rack_shelf_chk_2 CHECK ((shelf_width > 0)),
  CONSTRAINT rack_shelf_chk_3 CHECK ((shelf_height > 0))
) ENGINE=InnoDB;

CREATE TABLE rack_shelf_bin (
  id              int unsigned NOT NULL AUTO_INCREMENT,
  rack_shelf_id   int unsigned NOT NULL,
  bin_seq         tinyint unsigned NOT NULL,
  bin_len         decimal(12,4) NOT NULL,
  bin_width       decimal(12,4) NOT NULL,
  bin_height      decimal(12,4) NOT NULL,
  bin_volume      decimal(20,4) DEFAULT (((bin_len * bin_width) * bin_height)),  -- generated
  max_sku_allowed tinyint unsigned NOT NULL,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY rack_shelf_bin_unique (rack_shelf_id, bin_seq),
  CONSTRAINT fk_rack_shelf FOREIGN KEY (rack_shelf_id) REFERENCES rack_shelf (id),
  CONSTRAINT rack_shelf_bin_chk_1 CHECK ((bin_len > 0)),
  CONSTRAINT rack_shelf_bin_chk_2 CHECK ((bin_width > 0)),
  CONSTRAINT rack_shelf_bin_chk_3 CHECK ((bin_height > 0))
) ENGINE=InnoDB;
```

### 4.10 Two lookups the movement engine reads

```sql
CREATE TABLE stacking_group (
  id                  int unsigned NOT NULL AUTO_INCREMENT,
  sg_name             varchar(255) NOT NULL,        -- 'FMCG_OIL_FL_0'
  is_active           tinyint(1) DEFAULT 0,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  created_by varchar(32) NOT NULL,
  capacity_group_name varchar(100) NOT NULL DEFAULT '',   -- 'FMCG'
  PRIMARY KEY (id),
  UNIQUE KEY unique_stacking_capacity (sg_name, capacity_group_name)
) ENGINE=InnoDB;

CREATE TABLE transferin_type (
  id                   smallint NOT NULL AUTO_INCREMENT,
  transferin_type_name varchar(255) DEFAULT NULL,   -- id 6 = 'stacking'
  created_by varchar(32) NOT NULL,
  updated_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY transferin_type_name (transferin_type_name)
) ENGINE=InnoDB;

-- One shared reason list. BOTH entity_movement_details.underpick_reason_id and
-- entity_movement_recommendation.understack_reason_id point here — there is no
-- separate underpick_reason table.
CREATE TABLE understack_reason (
  id        tinyint unsigned NOT NULL AUTO_INCREMENT,
  reason    varchar(1024) DEFAULT NULL,   -- 'SKU not in Saleable Condition'
  is_active tinyint(1) DEFAULT 0,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_is_active (is_active)
) ENGINE=InnoDB;
```

**Shortfall reasons are one list, not two.** `underpick_reason_id` (on the detail, "I
couldn't pick all of it") and `understack_reason_id` (on the recommendation, "I couldn't
stack all of it") both resolve against this single table — the same reason, e.g. *SKU not
in Saleable Condition*, applies to either. The table keeps its production name for parity;
if you'd prefer a neutral one (`movement_reason`) now that it serves both, say so and I'll
rename it in the final DDL.

`racktype.planogram_location` is a **string** reference to
`planogram_locations.location_type` (not an id) — so a rack type carries the location its
bins default to. It was `NULL` in your sample, so I've assumed it's optional and that
`fc_rack_shelf_bin.location_id` is authoritative for a given bin.

`stacking_group` closes the loop on the stacking job's metadata:
`stacking_group_list: ["FV_Bulk", "Bread", ...]` are `sg_name` values, and
`priority_group_name: "FMCG"` is a `capacity_group_name`. A stacking job may only place
stock into bins whose `fc_rack_shelf_bin.stacking_group_id` is in that list.

### 4.11 `sku_batch` — the batch identity (catalog-owned)

Owned by **catalog**, but every inventory table references it, so it is documented here.
**`sku_batch.id` is the `batch_id`** carried by `transferin_info`, `fc_entity_stock`,
`fc_entity_stock_ledger` and `fc_entity_recommendation`.

```sql
CREATE TABLE sku_batch (
  id           bigint unsigned NOT NULL AUTO_INCREMENT,   -- == batch_id
  sku_id       int unsigned NOT NULL,                     -- == entity_id when entity_type='sku'
  batch_hash   char(64) DEFAULT NULL,                     -- sha256 of the batch params
  batch_params json DEFAULT NULL,                         -- {"expiry": "...", "source": "shelf_life"}
  algorithm_id int unsigned NOT NULL DEFAULT 0,
  created_by varchar(32) NOT NULL,
  updated_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_batch_hash (batch_hash),
  KEY idx_sku_id (sku_id)
) ENGINE=InnoDB;
```

Three design points that matter:

- **A batch is get-or-create by hash, not create-always.** `batch_hash` is unique, so batch
  identity is *derived from its parameters*: the same SKU received twice with identical
  params resolves to the **same** `batch_id` rather than a duplicate. That's what makes
  `fc_entity_stock`'s unique key (`…, batch_id`) accumulate correctly across two GRNs of the
  same stock.
- **MRP is part of batch identity.** The batch-creation parameters — MRP included — live in
  the JSON params column, and the hash is computed over them. So **two MRPs mean two
  batches**: a price change on the same SKU produces a new `batch_id` and therefore a
  separate stock row, rather than silently merging stock bought at different prices. This is
  the behaviour to preserve; it's what lets the ledger value stock correctly.
- **Recommendations are generated from these params.** The placement engine reads batch
  metadata (expiry, MRP) to decide bins — which is what makes FEFO possible on picking and
  MRP-aware placement possible on stacking. The params are therefore not decoration; they
  are an input to the movement engine.

> The column is **`batch_params`** (confirmed) — MRP and the other creation parameters go
> in there, and the hash is computed over them.

> **`entity_id` is the numeric SKU id**, matching `sku_batch.sku_id` (both `int unsigned`) —
> *not* the `sku_code` string. See §5 for what that means for the ported API.

> Topology is master data, not movement data — none of it is partitioned, and it changes
> only when the warehouse is re-laid-out.

### 4.9 `planogram_locations` — what every `location_id` means

```sql
CREATE TABLE planogram_locations (
  id                   int unsigned NOT NULL AUTO_INCREMENT,
  location_type        varchar(255) NOT NULL,
  is_picking_enabled   tinyint(1) DEFAULT 0,
  is_bulk_location     tinyint(1) DEFAULT 0,
  location_description varchar(2048) NOT NULL,
  created_by varchar(32) NOT NULL,
  created_on datetime DEFAULT CURRENT_TIMESTAMP,
  updated_on datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by varchar(32) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY location_type (location_type)
) ENGINE=InnoDB;
```

**These ids are semantic constants — seed them with the exact values below, never
renumber.** Ids 7 and 10 are absent in production (retired types); leave the gaps.

| id | location_type | picking | bulk | role in our flows |
|---:|---|:--:|:--:|---|
| 1 | `primary` | ✅ | | pick face — the normal picking source |
| 2 | `secondary` | | | overflow storage feeding primary |
| 3 | `miscellaneous` | | ✅ | bulk storage ("bulk" in the stacking step) |
| 4 | `return` | | ✅ | stock leaving the warehouse |
| 5 | `lost_and_found` | | | |
| 6 | `delivery` | | ✅ | dispatch — picked stock ends up here |
| 8 | `unstacked` | ✅ | ✅ | **GRN lands here**; also directly pickable |
| 9 | `in_processing` | | ✅ | in-flight during **stacking** |
| 11 | `in_processing_picking` | | ✅ | in-flight during **picking** |
| 12 | `sku_conversion` | | ✅ | |
| 13 | `prn_processing` | | ✅ | PRN transfer-in awaiting initiation |

Referenced in code as named constants, not magic numbers:

```python
class Location:
    PRIMARY = 1
    SECONDARY = 2
    MISCELLANEOUS = 3        # bulk
    RETURN = 4
    LOST_AND_FOUND = 5
    DELIVERY = 6
    UNSTACKED = 8
    IN_PROCESSING = 9        # stacking
    IN_PROCESSING_PICKING = 11
    SKU_CONVERSION = 12
    PRN_PROCESSING = 13
```

**The flows now read concretely:**

```
GRN       transferin_info ─────────────────────► unstacked (8)
stacking  unstacked (8) ──► in_processing (9) ──► primary (1) | secondary (2) | miscellaneous (3)
picking   primary (1) or unstacked (8) ──► in_processing_picking (11) ──► delivery (6)
```

Three things this told me that the prose didn't:

1. **You can pick straight from unstacked.** `unstacked` is the only location besides
   `primary` with `is_picking_enabled = 1`, so freshly-received stock is pickable before it
   has ever been stacked. Picking therefore has to consider two possible sources, and
   `bin_priority_order` is what decides between them.
2. **In-processing is a real stock location, not just in-flight bookkeeping** — and there
   are *two* of them, one for stacking (9) and one for picking (11). Your
   `fc_entity_stock` sample sat at location 11 with a real `bin_id`, which settles the
   question I'd raised.
3. **Picked stock ends at `delivery` (6).** Your `fc_entity_recommendation` sample moved a
   `CONTAINER` from 11 → 6 with `request_type='binning'`, which reads as: pick into an
   in-processing container, then bin that container to dispatch.

---

## 5. Conventions

- **`planogram_id` = the warehouse**, and now provably so: `fc_planogram.unique_fc_id`
  makes it one planogram per FC. The bridge to our existing table is
  `fc_planogram.wh_code` ↔ `warehouse.code` (the `code` column added by
  `migration_v2_api.sql`), with `fc_id` as the numeric FC id. Defaulted to `1` for now, and
  present on every movement table so multi-warehouse needs no later migration.
- **`entity_id` + `entity_type`** is polymorphic — `sku` today, `CONTAINER` also seen.
- **`entity_id` is numeric — and our catalog is keyed on a string.** The movement tables use
  `entity_id int unsigned` (= `sku_batch.sku_id`), which maps to `product.product_id`. But
  the mobile API we ported speaks `sku_code` (= `product.product_string`) throughout.
  **So the API layer must translate `sku_code` ↔ `product_id` at the boundary** — the
  service layer works in numeric ids, the wire format stays `sku_code` so the app is
  unaffected. Worth deciding deliberately rather than discovering mid-implementation.
- **Quantities are `decimal`**, not integers: `decimal(16,4)` inbound/picked,
  `decimal(12,4)` stock and ledger.
- **No cross-module foreign keys**, matching the rest of the codebase.
- **Composite PK `(id, created_on)`** on partitioned tables — MySQL requires the partition
  column in every unique key.

---

## 6. What I still need from you

### 6.1 Coming from you
- ✅ `sku_batch` received (§4.11).
- Remaining tables you mentioned are still to come.

### 6.2 Answered so far
- ✅ **Bin master** — `fc_rack_shelf_bin`, whose `id` is the `bin_id` and whose `binloc` is
  the `bin_location` string.
- ✅ **`vbin_id`** — not a separate table; a row in `fc_rack_shelf_bin` with
  `bin_type = 'vbin'`.
- ✅ **Where `location_id` is authoritative** — on the bin, denormalised onto stock/ledger.
- ✅ **Location master** — `planogram_locations` (§4.9). Also settled that in-processing is
  a real stock location, that unstacked is directly pickable, and that picked stock ends at
  `delivery`.
- ✅ **Topology masters — complete.** `fc_planogram`, `fc_floor`, and the full template
  chain `racktype → rack_variant → rack_shelf → rack_shelf_bin`. No unresolved FKs remain
  in the topology.
- ✅ **Lookups** — `stacking_group`, `transferin_type`, and `understack_reason` (one shared
  list serving *both* `underpick_reason_id` and `understack_reason_id`).
- ✅ **Batch** — `sku_batch` (§4.11), resolved get-or-create by `batch_hash`.
- ✅ **Planogram ↔ warehouse is 1:1** — `fc_planogram` has `UNIQUE KEY unique_fc_id (fc_id)`,
  so one planogram per FC. See the bridge in §5.

### 6.3 Still missing
| Missing | Referenced by | Why it matters |
|---|---|---|
| **`transferin_type` rows** | `transferin_type_id` | You showed id 6 = `stacking`, but the GRN sample used **id 3** and the metadata mentioned `rtv-ti`. I need rows 1–5 to know what a GRN transfer-in actually is. **This is the last outstanding item.** |

> `sku_batch.algorithm_id` — **not used, ignore** (per your note). Kept as a column for
> schema parity, never read or written.

### 6.4 Behaviour to confirm
0. **What drives `bin_priority_order`?** It sits on `fc_entity_stock` and
   `fc_entity_recommendation` but *not* on the bin master — so it looks like a property of
   the stock in a bin rather than of the bin itself. In your EMD sample it was `59406912`,
   which has the shape of a `transferin_id`, suggesting unstacked stock is ordered FIFO by
   inbound. Is it the transferin id for unstacked, and something else (pick-path sequence?)
   for real bins?
1. ~~Is unstacked pickable, and where does it live?~~ **Answered.** Unstacked is pickable,
   and `fc_entity_stock` **does** carry a `location_id = 8` row for it. So on-hand is
   `SUM(fc_entity_stock.quantity)` alone, and `transferin_info.unstacked_quantity` must be
   kept in lockstep with it. Written up as the invariant in §4.2.
2. ~~Is in-process a real stock row?~~ **Answered** — locations 9 and 11 exist and your
   `fc_entity_stock` sample sat at 11 with a real bin.
3. **Picking: recommendation before or after the scan?** Stacking is scan-first
   (EMD → recommendations). For picking I've assumed the reverse — the system recommends a
   bin, the user picks and acks. Confirm.
4. **Is the pick→delivery hop always via a container?** Your sample binned a
   `CONTAINER` from 11 → 6. Does every picked order travel as a container, or can loose
   SKUs move 11 → 6 directly?
5. **What drives acknowledgement** — `fc_entity_recommendation.qty_to_process` looks
   authoritative (your EMR sample had `quantity = 0.0000` while the core row had `1.0000`).
6. **`transferin_status`** values beyond `received`, and what closes a transferin
   (`unstacked_quantity` hitting 0?).
7. **GRN header** — is `transferin_id` simply our `invoice.invoice_id`, or is there a
   separate GRN header holding supplier/docket/received-by?
8. ~~Where does MRP live?~~ **Answered** — MRP and the other batch-creation params sit in
   the batch's JSON column and feed both the hash and the recommendation engine, so two MRPs
   mean two batches (§4.11).
9. **What does `is_bulk_location` actually gate?** Every location except `primary`,
   `secondary` and `lost_and_found` has it set, so it doesn't read as "bulk storage" in the
   ordinary sense — more like "holds mixed/unaddressed stock". Does it drive bin selection,
   or is it informational?

---

## 7. Live API surface that must move with this

Eight ported mobile endpoints read or write the four tables being dropped, plus one order
endpoint. They must be re-pointed in the same change or the Android app breaks:

| Endpoint | Re-point to |
|---|---|
| `GET /inventory/stock` | `fc_entity_stock` |
| `GET /inventory/stock/{warehouse_id}/{sku_code}` | `fc_entity_stock`, summed across bins/batches |
| `POST /inventory/stock/receive` | `transferin_info` (the GRN path) |
| `POST /inventory/stock/adjust` | `fc_entity_stock` + `fc_entity_stock_ledger` |
| `GET /inventory/transactions` | `fc_entity_stock_ledger` |
| `GET /inventory/picklists` | `entity_movement_request` where `movement_type='picking'` |
| `POST /inventory/picklists/generate` | create a picking request for the order |
| `POST /inventory/picklists/{id}/complete` | acknowledge recommendations, then `apply_fulfillment` |
| `GET /orders/{id}/fulfillment` | on-hand from `fc_entity_stock` |

Whether these keep their current paths and response shapes (so the app needs no change) or
move to new bin-aware endpoints is a decision to make before implementation — the old
shapes have no concept of bin or batch, so they can only ever return a summed view.

Nothing will be created or dropped until sections 3, 6 and 7 are settled.
