# -*- encoding: utf-8 -*-
"""
inventory module — table DDL (registered with the schema registry).

Implements the bin- and batch-level model described in GRN_STACKING_DESIGN.md:

  topology      racktype -> rack_variant -> rack_shelf -> rack_shelf_bin   (templates)
                fc_planogram -> fc_floor -> fc_aisle -> fc_rack
                             -> fc_rack_shelf -> fc_rack_shelf_bin          (instances)
  lookups       planogram_locations, stacking_group, transferin_type, understack_reason
  inbound       transferin_info                    (immutable GRN lines)
  stock         fc_entity_stock                    (live, row deleted when a bin empties)
                fc_entity_stock_ledger             (append-only audit)
  movement      entity_movement_request            (stacking | picking | moves)
                entity_movement_details
                entity_movement_recommendation  -> fc_entity_recommendation

Conventions
-----------
* `planogram_id` is the warehouse (1:1 with an FC). Defaults to 1 for now.
* `entity_id` + `entity_type` is polymorphic ('sku' | 'CONTAINER'); `entity_id` is the
  NUMERIC sku id (== product.product_id), not the sku_code string.
* Column names/types mirror production so the app can point here unchanged.
* FKs exist only WITHIN this module's topology (as in production). Nothing references
  another module's tables — `batch_id`, `entity_id`, `created_by_id` are plain columns.
* `order=` controls creation sequence: templates and parents must precede children.

The simplified v2-port tables (stock, inventory_transactions, picklists, picklist_items)
have been replaced by this model and dropped — see migration_drop_legacy_inventory.sql.
"""

from api.shared.db_manager import _generate_monthly_partitions
from api.shared.schema_registry import register_table

# Partitioned tables all range on created_on (see design doc §4).
_PARTS = _generate_monthly_partitions('created_on')


# ── Location master ──────────────────────────────────────────────────────────
# Semantic ids — seeded below, never renumbered. 7 and 10 are retired in production.
class Location:
    PRIMARY = 1
    SECONDARY = 2
    MISCELLANEOUS = 3          # bulk storage
    RETURN = 4
    LOST_AND_FOUND = 5
    DELIVERY = 6
    UNSTACKED = 8              # GRN lands here; also directly pickable
    IN_PROCESSING = 9          # in-flight during stacking
    IN_PROCESSING_PICKING = 11  # in-flight during picking
    SKU_CONVERSION = 12
    PRN_PROCESSING = 13


# Seeded with production's exact ids — 7 and 10 are retired there, so the gaps stay.
LOCATION_SEED = [
    (1,  'primary',               1, 0, 'bins where picking is enabled'),
    (2,  'secondary',             0, 0, 'bins to store more stock'),
    (3,  'miscellaneous',         0, 1, 'bulk storage for stock'),
    (4,  'return',                0, 1, 'stock which is going to be sent out of wh'),
    (5,  'lost_and_found',        0, 0, 'lost and found stock'),
    (6,  'delivery',              0, 1, 'bins where delivery is enabled'),
    (8,  'unstacked',             1, 1, 'bulk location where transferin lands'),
    (9,  'in_processing',         0, 1, 'in-processing location for stacking'),
    (11, 'in_processing_picking', 0, 1, 'in-processing location for picking'),
    (12, 'sku_conversion',        0, 1, 'bulk storage for sku conversion'),
    (13, 'prn_processing',        0, 1, 'location for PRN transfer-in stock awaiting initiation'),
]


register_table("planogram_locations", """
CREATE TABLE IF NOT EXISTS planogram_locations (
    id                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    location_type        VARCHAR(255) NOT NULL,
    is_picking_enabled   TINYINT(1) DEFAULT 0,
    is_bulk_location     TINYINT(1) DEFAULT 0,
    location_description VARCHAR(2048) NOT NULL,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY location_type (location_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=20)


# ── Rack templates (defined once, reused by every physical rack) ─────────────
register_table("racktype", """
CREATE TABLE IF NOT EXISTS racktype (
    id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
    racktype_name      VARCHAR(5) NOT NULL,
    is_active          TINYINT(1) DEFAULT 1,
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    planogram_location VARCHAR(20) DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY racktype_name (racktype_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=21)

register_table("rack_variant", """
CREATE TABLE IF NOT EXISTS rack_variant (
    id                     INT UNSIGNED NOT NULL AUTO_INCREMENT,
    racktype_id            INT UNSIGNED NOT NULL,
    rack_variant_name      VARCHAR(5) NOT NULL,
    rack_len               DECIMAL(12,4) NOT NULL,
    rack_width             DECIMAL(12,4) NOT NULL,
    rack_height            DECIMAL(12,4) NOT NULL,
    num_of_shelves         TINYINT UNSIGNED NOT NULL,
    num_of_picking_shelves TINYINT UNSIGNED NOT NULL,
    is_active              TINYINT(1) DEFAULT 1,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY rack_variant_name (rack_variant_name),
    KEY fk_racktype (racktype_id),
    CONSTRAINT fk_racktype FOREIGN KEY (racktype_id) REFERENCES racktype (id),
    CONSTRAINT rack_variant_chk_1 CHECK ((rack_len > 0)),
    CONSTRAINT rack_variant_chk_2 CHECK ((rack_width > 0)),
    CONSTRAINT rack_variant_chk_3 CHECK ((rack_height > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=22)

register_table("rack_shelf", """
CREATE TABLE IF NOT EXISTS rack_shelf (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    rack_variant_id INT UNSIGNED NOT NULL,
    shelf_name      VARCHAR(1) NOT NULL,
    shelf_seq       TINYINT UNSIGNED NOT NULL,
    shelf_length    DECIMAL(12,4) NOT NULL,
    shelf_width     DECIMAL(12,4) NOT NULL,
    shelf_height    DECIMAL(12,4) NOT NULL,
    is_hole         TINYINT(1) DEFAULT 0,
    num_of_bins     TINYINT UNSIGNED NOT NULL,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY rack_variant_shelf_unique (rack_variant_id, shelf_name),
    CONSTRAINT fk_rack_variant_shelf FOREIGN KEY (rack_variant_id) REFERENCES rack_variant (id),
    CONSTRAINT rack_shelf_chk_1 CHECK ((shelf_length > 0)),
    CONSTRAINT rack_shelf_chk_2 CHECK ((shelf_width > 0)),
    CONSTRAINT rack_shelf_chk_3 CHECK ((shelf_height > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=23)

register_table("rack_shelf_bin", """
CREATE TABLE IF NOT EXISTS rack_shelf_bin (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    rack_shelf_id   INT UNSIGNED NOT NULL,
    bin_seq         TINYINT UNSIGNED NOT NULL,
    bin_len         DECIMAL(12,4) NOT NULL,
    bin_width       DECIMAL(12,4) NOT NULL,
    bin_height      DECIMAL(12,4) NOT NULL,
    bin_volume      DECIMAL(20,4) GENERATED ALWAYS AS (((bin_len * bin_width) * bin_height)) STORED,
    max_sku_allowed TINYINT UNSIGNED NOT NULL,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY rack_shelf_bin_unique (rack_shelf_id, bin_seq),
    CONSTRAINT fk_rack_shelf FOREIGN KEY (rack_shelf_id) REFERENCES rack_shelf (id),
    CONSTRAINT rack_shelf_bin_chk_1 CHECK ((bin_len > 0)),
    CONSTRAINT rack_shelf_bin_chk_2 CHECK ((bin_width > 0)),
    CONSTRAINT rack_shelf_bin_chk_3 CHECK ((bin_height > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=24)


# ── Physical topology (this warehouse) ───────────────────────────────────────
register_table("fc_planogram", """
CREATE TABLE IF NOT EXISTS fc_planogram (
    id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
    wh_code            VARCHAR(16) NOT NULL,
    fc_id              INT UNSIGNED DEFAULT 0,
    dc_id              INT UNSIGNED NOT NULL,
    num_of_floors      TINYINT NOT NULL,
    is_active          TINYINT(1) DEFAULT 1,
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    planogram_mode_id  INT UNSIGNED NOT NULL DEFAULT 1,
    dispatch_bin_floor TINYINT UNSIGNED DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY unique_fc_id (fc_id),
    KEY idx_dc_id (dc_id),
    KEY idx_fc_id_is_active (fc_id, is_active),
    KEY idx_wh_code (wh_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=25)

register_table("fc_floor", """
CREATE TABLE IF NOT EXISTS fc_floor (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    fc_planogram_id INT UNSIGNED NOT NULL,
    floor_seq       TINYINT UNSIGNED NOT NULL,
    num_of_aisles   MEDIUMINT UNSIGNED NOT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    floor_capacity  INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY planogram_floor_unique (fc_planogram_id, floor_seq),
    CONSTRAINT fk_planogram FOREIGN KEY (fc_planogram_id) REFERENCES fc_planogram (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=26)

register_table("fc_aisle", """
CREATE TABLE IF NOT EXISTS fc_aisle (
    id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
    fc_floor_id        INT UNSIGNED NOT NULL,
    aisle_name         VARCHAR(4) NOT NULL,
    aisle_facing_group VARCHAR(2) NOT NULL,
    aisle_facing       VARCHAR(2) NOT NULL,
    aisle_seq          TINYINT UNSIGNED NOT NULL,
    aisle_start_pos    POINT DEFAULT NULL,
    aisle_end_pos      POINT DEFAULT NULL,
    is_active          TINYINT(1) DEFAULT 1,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY floor_aisle_unique (fc_floor_id, aisle_name),
    CONSTRAINT fk_fc_floor FOREIGN KEY (fc_floor_id) REFERENCES fc_floor (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=27)

register_table("fc_rack", """
CREATE TABLE IF NOT EXISTS fc_rack (
    id                     INT UNSIGNED NOT NULL AUTO_INCREMENT,
    fc_aisle_id            INT UNSIGNED NOT NULL,
    rack_variant_id        INT UNSIGNED DEFAULT 0,
    rack_seq               DECIMAL(12,4) DEFAULT NULL,
    gap_length             DECIMAL(12,4) DEFAULT 0,
    num_of_picking_shelves INT UNSIGNED NOT NULL,
    start_pos              POINT DEFAULT NULL,
    end_pos                POINT DEFAULT NULL,
    is_active              TINYINT(1) DEFAULT 1,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY fc_aisle_id (fc_aisle_id, rack_seq),
    CONSTRAINT fc_rack_chk_1 CHECK ((gap_length >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=28)

register_table("fc_rack_shelf", """
CREATE TABLE IF NOT EXISTS fc_rack_shelf (
    id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
    fc_rack_id    INT UNSIGNED NOT NULL,
    shelf_level   VARCHAR(16) NOT NULL,
    rack_shelf_id INT UNSIGNED NOT NULL,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    KEY fk_fc_rack (fc_rack_id),
    KEY fk_rack_shelf_fc_rack_shelf (rack_shelf_id),
    CONSTRAINT fk_fc_rack FOREIGN KEY (fc_rack_id) REFERENCES fc_rack (id),
    CONSTRAINT fk_rack_shelf_fc_rack_shelf FOREIGN KEY (rack_shelf_id) REFERENCES rack_shelf (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=29)

# fc_rack_shelf_bin.id IS the bin_id used across stock, ledger and recommendations.
# A virtual bin is a row here with bin_type='vbin' (fc_rack_shelf_id = 0).
register_table("fc_rack_shelf_bin", """
CREATE TABLE IF NOT EXISTS fc_rack_shelf_bin (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    fc_rack_shelf_id  INT UNSIGNED NOT NULL DEFAULT 0,
    planogram_id      INT UNSIGNED NOT NULL,
    location_id       TINYINT UNSIGNED NOT NULL,
    rack_shelf_bin_id INT UNSIGNED NOT NULL DEFAULT 0,
    available_volume  DECIMAL(12,4) NOT NULL DEFAULT 0,
    max_sku_allowed   TINYINT UNSIGNED DEFAULT NULL,
    stacking_group_id INT UNSIGNED NOT NULL DEFAULT 0,
    is_static         TINYINT(1) DEFAULT 0,
    is_active         TINYINT(1) DEFAULT 1,
    binloc            VARCHAR(32) NOT NULL DEFAULT '',
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    bin_metainfo JSON DEFAULT NULL,
    bin_type     VARCHAR(255) DEFAULT 'bin',
    PRIMARY KEY (id),
    KEY fk_fc_rack_shelf (fc_rack_shelf_id),
    KEY planogram_id_idx (planogram_id),
    KEY idx_binloc_planogram_id_location_id (binloc, planogram_id, location_id),
    KEY idx_id_planogram_id (id, planogram_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=30)


# ── Lookups ──────────────────────────────────────────────────────────────────
register_table("stacking_group", """
CREATE TABLE IF NOT EXISTS stacking_group (
    id                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    sg_name             VARCHAR(255) NOT NULL,
    is_active           TINYINT(1) DEFAULT 0,
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    capacity_group_name VARCHAR(100) NOT NULL DEFAULT '',
    PRIMARY KEY (id),
    UNIQUE KEY unique_stacking_capacity (sg_name, capacity_group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=31)

register_table("transferin_type", """
CREATE TABLE IF NOT EXISTS transferin_type (
    id                   SMALLINT NOT NULL AUTO_INCREMENT,
    transferin_type_name VARCHAR(255) DEFAULT NULL,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY transferin_type_name (transferin_type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=32)

# One shared shortfall-reason list: BOTH entity_movement_details.underpick_reason_id and
# entity_movement_recommendation.understack_reason_id resolve against this table.
register_table("understack_reason", """
CREATE TABLE IF NOT EXISTS understack_reason (
    id        TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reason    VARCHAR(1024) DEFAULT NULL,
    is_active TINYINT(1) DEFAULT 0,
    created_by VARCHAR(32) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(32) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    KEY idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=33)


# ── Inbound (GRN) ────────────────────────────────────────────────────────────
# Never deleted. `quantity` is what arrived; `unstacked_quantity` decrements as stacking
# consumes it.
#
# INVARIANT: unstacked stock is ALSO held as an fc_entity_stock row at location_id = 8.
# The two must stay in sync — every stacking / pick-from-unstacked decrements BOTH, in one
# transaction. transferin_info gives the per-inbound breakdown (FIFO, traceability);
# fc_entity_stock @ 8 gives the per-sku+batch total. On-hand is read from fc_entity_stock
# alone — summing unstacked_quantity on top of it would double-count.
register_table("transferin_info", f"""
CREATE TABLE IF NOT EXISTS transferin_info (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planogram_id        BIGINT UNSIGNED NOT NULL,
    transferin_id       BIGINT UNSIGNED NOT NULL,
    transferin_type_id  BIGINT UNSIGNED NOT NULL,
    entity_id           BIGINT UNSIGNED NOT NULL,
    entity_type         VARCHAR(32) NOT NULL,
    batch_id            BIGINT UNSIGNED NOT NULL,
    quantity            DECIMAL(16,4) NOT NULL,
    unstacked_quantity  DECIMAL(12,4) NOT NULL,
    vbin_id             BIGINT UNSIGNED NOT NULL DEFAULT 0,
    cost_price          DECIMAL(12,4) NOT NULL DEFAULT 0,
    mrp                 DECIMAL(12,4) NOT NULL DEFAULT 0,
    transferin_status   VARCHAR(32) NOT NULL,
    meta_info           VARCHAR(500) NOT NULL DEFAULT '',
    created_by_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_on          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (id, created_on),
    KEY planogram_id_3 (planogram_id, transferin_type_id, transferin_id),
    KEY planogram_id_5 (planogram_id, transferin_type_id, transferin_id, entity_id, entity_type),
    KEY idx_planogram_entity_etype (planogram_id, entity_id, entity_type),
    KEY idx_tid_entity_vbin (transferin_id, entity_id, vbin_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=40)


# ── Stock ────────────────────────────────────────────────────────────────────
# Live working set only: the row is DELETED when a bin empties. Not partitioned.
# Holds a row for UNSTACKED stock too (location_id = 8, bin_id = 0), so this table is the
# complete on-hand picture:  total on hand = SUM(quantity).  See transferin_info above.
register_table("fc_entity_stock", """
CREATE TABLE IF NOT EXISTS fc_entity_stock (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planogram_id       INT UNSIGNED NOT NULL,
    location_id        TINYINT UNSIGNED NOT NULL,
    bin_id             BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bin_location       VARCHAR(255) NOT NULL DEFAULT '',
    entity_id          INT UNSIGNED NOT NULL,
    entity_type        VARCHAR(255) NOT NULL,
    batch_id           BIGINT UNSIGNED NOT NULL,
    bin_priority_order BIGINT UNSIGNED NOT NULL DEFAULT 0,
    quantity           DECIMAL(12,4) NOT NULL,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(255) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id),
    UNIQUE KEY planogram_id_new (planogram_id, location_id, bin_id, entity_id, entity_type, batch_id),
    KEY planogram_id_2 (planogram_id, location_id, bin_id, entity_id),
    KEY planogram_id_3 (planogram_id, location_id, entity_id),
    KEY planogram_id_4 (planogram_id, entity_id),
    KEY idx_planogram_bin (planogram_id, bin_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=41)

# Append-only. Never updated or deleted — the audit trail behind fc_entity_stock.
register_table("fc_entity_stock_ledger", f"""
CREATE TABLE IF NOT EXISTS fc_entity_stock_ledger (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planogram_id          INT UNSIGNED NOT NULL,
    location_id           TINYINT UNSIGNED NOT NULL,
    bin_id                BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bin_location          VARCHAR(255) NOT NULL DEFAULT '',
    entity_id             INT UNSIGNED NOT NULL,
    entity_type           VARCHAR(255) NOT NULL,
    batch_id              BIGINT UNSIGNED NOT NULL,
    quantity_changed      DECIMAL(12,4) NOT NULL,
    quantity_after_change DECIMAL(12,4) NOT NULL,
    reference_id          BIGINT UNSIGNED NOT NULL,
    reference_type        VARCHAR(255) NOT NULL,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(255) NOT NULL DEFAULT 'system',
    cost_price            DECIMAL(12,4) DEFAULT NULL,
    created_on_epoch      BIGINT UNSIGNED DEFAULT NULL,
    PRIMARY KEY (id, created_on),
    KEY idx_planogram_entity_reference (planogram_id, entity_id, reference_id),
    KEY idx_created_planogram_entity (updated_on, planogram_id, entity_id),
    KEY idx_partition_filter (planogram_id, entity_id, entity_type, bin_id, location_id, batch_id, created_on)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=42)


# ── Movement engine (stacking | picking | stock moves) ───────────────────────
# For picking: reference_type='ORDER', request_identifier=potential_order_id.
register_table("entity_movement_request", f"""
CREATE TABLE IF NOT EXISTS entity_movement_request (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planogram_id       INT UNSIGNED NOT NULL,
    movement_type      VARCHAR(32) NOT NULL,
    request_status     VARCHAR(32) NOT NULL,
    meta_info          VARCHAR(500) NOT NULL DEFAULT '',
    created_by_id      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_on         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by_id      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    metadata           JSON DEFAULT NULL,
    request_identifier BIGINT DEFAULT NULL,
    reference_type     VARCHAR(500) DEFAULT '',
    PRIMARY KEY (id, created_on),
    KEY planogram_id (planogram_id, movement_type),
    KEY planogram_id_2 (planogram_id, movement_type, request_status),
    KEY planogram_reqid_reftype (planogram_id, request_identifier, reference_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=43)

# source_stock_info is JSON recording which transferin_info rows / bins the qty came from.
register_table("entity_movement_details", f"""
CREATE TABLE IF NOT EXISTS entity_movement_details (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_id          BIGINT UNSIGNED NOT NULL,
    entity_id           BIGINT UNSIGNED NOT NULL,
    entity_type         VARCHAR(32) NOT NULL,
    source_bin_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    source_location_id  BIGINT UNSIGNED NOT NULL,
    picked_quantity     DECIMAL(16,4) NOT NULL,
    underpick_reason_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
    source_stock_info   TEXT NOT NULL,
    created_by_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_on          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (id, created_on),
    KEY request_id (request_id),
    KEY request_id_2 (request_id, entity_id, entity_type),
    KEY idx_request_source (request_id, source_bin_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=44)

# The core source->destination instruction, shared by stacking, binning and picking.
register_table("fc_entity_recommendation", f"""
CREATE TABLE IF NOT EXISTS fc_entity_recommendation (
    id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    planogram_id             INT UNSIGNED NOT NULL,
    entity_id                INT UNSIGNED NOT NULL,
    entity_type              VARCHAR(255) NOT NULL,
    source_location_id       INT UNSIGNED NOT NULL,
    destination_location_id  INT UNSIGNED NOT NULL,
    source_bin_id            BIGINT UNSIGNED NOT NULL DEFAULT 0,
    destination_bin_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    source_bin_location      VARCHAR(255) NOT NULL DEFAULT '',
    destination_bin_location VARCHAR(255) NOT NULL DEFAULT '',
    request_id               BIGINT UNSIGNED NOT NULL,
    request_type             VARCHAR(255) NOT NULL,
    operation                VARCHAR(255) NOT NULL,
    batch_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0,
    bin_priority_order       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    qty_to_process           DECIMAL(12,4) NOT NULL,
    qty_processed            DECIMAL(12,4) NOT NULL DEFAULT 0,
    status                   VARCHAR(255) NOT NULL,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',
    created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by VARCHAR(255) NOT NULL DEFAULT 'system',
    PRIMARY KEY (id, created_on),
    KEY idx_planogram_entity_source_bin (planogram_id, entity_id, source_bin_id),
    KEY idx_status (status),
    KEY idx_planogram_request_type (planogram_id, request_id, request_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=45)

# Links a request detail to its core recommendation(s).
register_table("entity_movement_recommendation", f"""
CREATE TABLE IF NOT EXISTS entity_movement_recommendation (
    id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_detail_id        BIGINT UNSIGNED NOT NULL,
    core_recommendation_id   BIGINT UNSIGNED NOT NULL,
    parent_recommendation_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
    understack_reason_id     BIGINT UNSIGNED NOT NULL DEFAULT 0,
    recommendation_type      VARCHAR(32) NOT NULL,
    sequence                 BIGINT DEFAULT 0,
    created_by_id            BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_on               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_on               DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    updated_by_id            BIGINT UNSIGNED NOT NULL DEFAULT 0,
    quantity                 DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
    PRIMARY KEY (id, created_on),
    KEY request_detail_id (request_detail_id),
    KEY request_detail_id_2 (request_detail_id, recommendation_type),
    KEY idx_parent_recommendation_id (parent_recommendation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
{_PARTS};
""", order=46)

# The v2-port tables (stock, inventory_transactions, picklists, picklist_items) were
# dropped once this model replaced them — see migration_drop_legacy_inventory.sql.
# Picking is now entity_movement_request(movement_type='picking'); on-hand is
# fc_entity_stock; the ledger is fc_entity_stock_ledger.
