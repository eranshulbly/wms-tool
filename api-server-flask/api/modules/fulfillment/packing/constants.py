# -*- encoding: utf-8 -*-
"""
Packing vocabulary and the operational thresholds served by `/packing/config`.

Every threshold here is an env var rather than a table column. Tolerance is the
number an anti-fraud rule is measured against, and tuning it must be a config
redeploy that leaves an audit trail in the deployment history — not a row someone
can UPDATE at 2am. The same reasoning applies to the barcode layout: Hero,
Castrol, Ebco and Cadila do not share a code format, and serving it means a new
company is a config push rather than an APK release (PACKING_DESIGN.md §6.4, §6.7).

Read once at import, exactly like `user_auth/tokens.py` reads its TTLs.
"""

import os

# ── Movement engine vocabulary ───────────────────────────────────────────────


class MovementType:
    """`entity_movement_request.movement_type` for a packing job."""
    PACKING = "packing"


class RequestStatus:
    """`entity_movement_request.request_status` through a packing job's life.

    Deliberately the same words `inventory.service.RequestStatus` already uses —
    picking and stacking share this column, and a second vocabulary on one column
    means every reader has to learn which flow wrote the row before it can read it.
    `saved` and `submitted_short` are the two packing adds:

        created -> in_progress -> saved <-> in_progress
                                     -> completed | submitted_short | cancelled
    """
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    SAVED = "saved"
    COMPLETED = "completed"
    SUBMITTED_SHORT = "submitted_short"
    CANCELLED = "cancelled"

    #: Statuses a job may still be written to. `saved` is included — resuming is
    #: the normal path, and it is `/jobs` that flips it back to in_progress.
    OPEN_STATUSES = (CREATED, IN_PROGRESS, SAVED)

    #: Statuses past which nothing may be written. Submit is final.
    TERMINAL_STATUSES = (COMPLETED, SUBMITTED_SHORT, CANCELLED)


class EntityType:
    """`entity_movement_details.entity_type`.

    `BOX` rows hold the scanned carton label in `entity_id` (which is why that
    column is VARCHAR(64)); `SKU` rows hold the numeric product id as text and
    point at their box through `source_bin_id`.
    """
    BOX = "box"
    SKU = "sku"


class BoxStatus:
    """`source_stock_info.status` on a box row.

    Not a column: nothing queries across boxes by status, and the states are only
    ever read once you already hold the box (PACKING_DESIGN.md §5).
    """
    SETUP = "setup"          # tare captured, label not yet bound
    OPEN = "open"            # bound and accepting scans
    SEALED = "sealed"        # weight-verified and closed; immutable
    ABANDONED = "abandoned"  # never deleted — an abandoned box is evidence


class BoxKind:
    """How the box came to exist. Everything downstream treats them identically.

    The only difference is where `tare_weight_kg` comes from: a BUILT box is
    weighed empty on the bench, an INTACT supplier carton cannot be emptied so its
    packaging weight is read from `product_uom.pack_tare_kg` (PACKING_DESIGN.md §6.8).
    """
    BUILT = "built"
    INTACT = "intact"


class Result:
    """Per-scan verdicts returned by `POST /boxes/{id}/scans`.

    The handheld plays a different cue per verdict, so these strings are part of
    the client contract and must not be reworded.
    """
    ACCEPTED = "accepted"
    UNPARSEABLE = "unparseable"          # not this company's code format
    UNKNOWN_SKU = "unknown_sku"          # product field resolves to no product row
    NOT_IN_PICKLIST = "not_in_picklist"  # real SKU, not on this order
    OVER_QUANTITY = "over_quantity"      # would exceed the line's required quantity
    DUPLICATE = "duplicate"              # this uid, or this serial, already applied
    UNDO = "undo"                        # an explicit negative correction
    INTACT_CARTON = "intact_carton"      # belongs at /jobs/{id}/cartons, never in a built box


class WeightEvent:
    """Significant scale events kept on the box row. Never the raw 500 ms stream —
    a five-minute box is ~600 samples that add nothing over these (design §5)."""
    TARE = "tare"
    SETTLE = "settle"
    EXCESS_DETECTED = "excess_detected"
    EXCESS_CLEARED = "excess_cleared"
    FREEZE = "freeze"
    SEAL = "seal"
    SEAL_REJECTED = "seal_rejected"


class ErrorCode:
    """Machine-readable `code` on business rejections. The app switches on this
    and displays `detail`; only these strings are contractual."""
    JOB_IN_USE = "job_in_use"
    ORDER_NOT_PACKABLE = "order_not_packable"
    BOX_ALREADY_OPEN = "box_already_open"
    BELOW_SCALE_MINIMUM = "below_scale_minimum"
    LABEL_ALREADY_USED = "label_already_used"
    TARE_MISSING = "tare_missing"
    BOX_NOT_OPEN = "box_not_open"
    BOX_EMPTY = "box_empty"
    OVER_QUANTITY = "over_quantity"
    WEIGHT_MISMATCH = "weight_mismatch"
    CARTON_EXCEEDS_NEED = "carton_exceeds_need"
    DUPLICATE_CARTON = "duplicate_carton"
    NOT_AN_INTACT_CARTON = "not_an_intact_carton"
    PACK_TARE_MISSING = "pack_tare_missing"
    BOX_STILL_OPEN = "box_still_open"
    NOTHING_PACKED = "nothing_packed"
    SHORTFALL_REQUIRES_ACK = "shortfall_requires_ack"
    JOB_ALREADY_SUBMITTED = "job_already_submitted"


class AbandonReason:
    """Why a box was abandoned. Free text is rejected — this is reporting input."""
    PACKER_EXIT = "packer_exit"
    WRONG_LABEL = "wrong_label"
    DAMAGED_BOX = "damaged_box"
    STALE = "stale"          # written by a sweep, never by the handheld

    ALL = (PACKER_EXIT, WRONG_LABEL, DAMAGED_BOX, STALE)


# ── Structural constants ─────────────────────────────────────────────────────

#: `source_bin_id = 0` means "belongs to no box". A shortfall row is exactly that,
#: so it reuses the column's existing "no bin" convention instead of a new flag.
NO_BOX = 0

#: Schema version stamped into both JSON documents. A JSON document in a TEXT
#: column changes shape over its life, and without this the reader has to guess
#: which shape it is holding.
JSON_SCHEMA_VERSION = 1

#: `source_stock_info` is TEXT — 65,535 bytes. We truncate `scans[]` oldest-first
#: past this and set `flags.scans_truncated`, leaving headroom for the header,
#: `flags` and `weight_events` which are NEVER truncated: they carry the fraud
#: signal. A close is never failed because an audit field overflowed.
SOURCE_STOCK_INFO_MAX_BYTES = 60_000

#: Grams per kilogram — variance is stored in grams because a DECIMAL(12,3) kg
#: difference of 0.002 reads as noise while "2 g" reads as a measurement.
G_PER_KG = 1000

#: How many of `product.weight`'s units make one kilogram.
#:
#: **`product.weight` is stored in GRAMS.** Nothing in the schema says so — the
#: column is `DECIMAL(10,3)` fed straight from a "Net Weight" spreadsheet column —
#: and packing is its first numeric consumer, so the unit had never had to be
#: pinned down before. The production catalogue settles it beyond doubt:
#:
#:   * `14610086000RS` ROLLAR COMP CAM CHAIN -> 23.000. The retail label for that
#:     exact part reads NET QUANTITY: 1, and a cam chain roller is 23 g. 23 kg is
#:     not a thing you post to a dealer.
#:   * The heaviest rows are 55-gallon oil drums at 250000.000 — 250 kg in grams,
#:     which is what a full drum weighs. As kilograms it would be 250 tonnes.
#:
#: Read as kilograms, every expected weight came out 1000x high, so no carton
#: could ever have closed. Converted here, in one place, rather than at each call
#: site — and configurable because a future company may upload kilograms, in which
#: case set PACKING_PRODUCT_WEIGHT_PER_KG=1.
PRODUCT_WEIGHT_PER_KG = float(os.environ.get('PACKING_PRODUCT_WEIGHT_PER_KG', 1000))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Operational thresholds (served by GET /packing/config) ───────────────────

#: The whole module's reason to exist. A box sealing more than this away from its
#: computed expected weight is refused. Snapshotted onto the job at creation so an
#: audit months later answers "was this within tolerance BY THE RULE OF THAT DAY".
TOLERANCE_G = _env_int('PACKING_TOLERANCE_G', 50)

#: Device-side mid-scan freeze at expected + N x the heaviest SKU on the picklist.
GROSS_OVERAGE_MULTIPLIER = _env_float('PACKING_GROSS_OVERAGE_MULTIPLIER', 2.0)

#: How long the scale reading must hold still before the app treats it as settled.
SETTLE_WINDOW_MS = _env_int('PACKING_SETTLE_WINDOW_MS', 1000)

#: At 10 g scale precision, anything under this cannot be individually verified.
#: Applied to quantity x unit weight PER SCAN, not to the unit weight alone — 200
#: units of a 5 g part is a kilogram, and highly verifiable (design §6.7.2).
WEIGHT_VERIFY_FLOOR_G = _env_int('PACKING_WEIGHT_VERIFY_FLOOR_G', 30)

#: Scan batching. Load-bearing, not an optimisation: one call per ack costs 7 auth
#: queries before the endpoint runs, which at ten packers is ~70 queries/sec against
#: an RDS instance capped at 60 connections (design §6.2).
SCAN_BATCH_SIZE = _env_int('PACKING_SCAN_BATCH_SIZE', 20)
SCAN_FLUSH_MS = _env_int('PACKING_SCAN_FLUSH_MS', 4000)

MAX_BOXES_PER_PICKLIST = _env_int('PACKING_MAX_BOXES_PER_PICKLIST', 50)

#: How long another packer's `in_progress` job blocks this one. Without a window a
#: single dead handset strands a picklist for everyone, forever — §16.4 calls that
#: out as a real leak. With it, the picklist returns to the floor on its own.
JOB_TAKEOVER_MINUTES = _env_int('PACKING_JOB_TAKEOVER_MINUTES', 30)

#: A scale that cannot resolve below this is not measuring an empty box, it is
#: reporting drift. Rejecting the tare here beats every later box on that bench
#: having a baseline of noise.
MIN_TARE_KG = _env_float('PACKING_MIN_TARE_KG', 0.100)

#: Audible feedback. Served rather than baked into the APK because warehouse floors
#: differ — a tone that carries in one is inaudible in the next (design §6.9).
ALERT_VOLUME = _env_float('PACKING_ALERT_VOLUME', 1.0)
ALERT_REPEAT_MS = _env_int('PACKING_ALERT_REPEAT_MS', 1500)

#: Fallback tare offered on the picklist card before a box is weighed. A hint for
#: the UI only — the real tare is always the scale reading.
DEFAULT_BOX_TARE_KG = _env_float('PACKING_DEFAULT_BOX_TARE_KG', 0.400)


# ── Barcode layout (served, never compiled in) ───────────────────────────────
# Field numbers are 1-BASED FIELD INDEXES, not byte offsets. The two confirmed
# samples are 11 `/`-delimited fields each, but field 4 is space-padded to 18 in
# the piece code and unpadded at 13 in the box code, and field 6 is 10 characters
# vs 7. A parser written against either sample's offsets silently mis-reads the
# other — and mis-reading the quantity field seals a box against the wrong
# expected weight. See PACKING_DESIGN.md §6.7.6.

BARCODE_DELIMITER = os.environ.get('PACKING_BARCODE_DELIMITER', '/')
BARCODE_FIELD_COUNT = _env_int('PACKING_BARCODE_FIELD_COUNT', 11)
BARCODE_TRIM_FIELDS = os.environ.get('PACKING_BARCODE_TRIM_FIELDS', '1') not in ('0', 'false', 'False')
BARCODE_PRODUCT_FIELD = _env_int('PACKING_BARCODE_PRODUCT_FIELD', 4)   # printed part number
BARCODE_QUANTITY_FIELD = _env_int('PACKING_BARCODE_QUANTITY_FIELD', 5)  # NET QUANTITY, base units
BARCODE_UPI_FIELD = _env_int('PACKING_BARCODE_UPI_FIELD', 3)            # anti-counterfeit code
BARCODE_SERIAL_FIELD = _env_int('PACKING_BARCODE_SERIAL_FIELD', 2)      # unique per physical pack
BARCODE_BATCH_FIELD = _env_int('PACKING_BARCODE_BATCH_FIELD', 7)        # B. NO. on the label
BARCODE_MRP_FIELD = _env_int('PACKING_BARCODE_MRP_FIELD', 6)            # varies BY BATCH

#: A code declaring more than one base unit is a supplier pack, not a loose piece.
#: There is no pack-level field in the code — §6.7 established that the printed
#: labels carry none — so the quantity is the only thing that distinguishes them,
#: and it is what routes a scan to /cartons rather than /scans.
INTACT_CARTON_MIN_QUANTITY = _env_int('PACKING_INTACT_CARTON_MIN_QUANTITY', 2)
