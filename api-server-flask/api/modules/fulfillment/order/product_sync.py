# -*- encoding: utf-8 -*-
"""Create or enrich catalogue products from an upload that carries product detail.

The spreadsheet order upload only ever knew a part number and a description, so a product
auto-created by it was a stub: a code and a name, nothing else. An Order Challan prints
considerably more per line — HSN, GST rate and selling unit — and that detail is worth
keeping, because it is the same detail the product master upload would otherwise have to
supply by hand later.

What is deliberately NOT copied here is the price. The challan prints a rate alongside a
discount and an SD percentage that are negotiated per dealer, so the rate on any one
document is that dealer's terms on that day, not a catalogue list price. Writing it to the
shared product row would let whichever dealer's challan happened to arrive first set the
price every other dealer is quoted. The money belongs to the order line, which is where
the deal actually happened — see potential_order_product.unit_price and its discount
columns. Only genuinely product-level facts are synced here: HSN, GST rate and unit are
properties of the goods and do not change with who is buying them.

Two rules, and they differ on purpose:

  * A product that does NOT exist is created with everything the document carries.
  * A product that DOES exist is only FILLED IN — a field already set is never
    overwritten. A challan is one order on one day; the product master is the considered
    record. Letting a document rewrite an existing price or UOM would mean the catalogue
    silently tracks whatever was ordered last, and an operator's correction would be
    undone by the next upload.

Which optional columns exist is discovered at runtime rather than assumed. `gst_percent`
is added by a migration that has not reached every deployment, and writing it
unconditionally would break the upload on any database that predates it.
"""

from datetime import datetime

from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)


# Upload column -> product column. Only columns the challan actually carries; the
# spreadsheet feeds simply do not have these keys and are unaffected.
_FIELD_MAP = (
    ('Part Description', 'name'),
    ('Part Description', 'description'),
    ('HSN Code',         'hsn_code'),
    ('GST %',            'gst_percent'),
    ('UOM',              'uom'),
)

# Columns that may be absent on an older database. Checked once per upload.
_OPTIONAL = ('hsn_code', 'gst_percent', 'uom', 'description')


def _existing_columns():
    rows = mysql_manager.execute_query(
        """SELECT COLUMN_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'product'""") or []
    return {r['COLUMN_NAME'] for r in rows}


def _text(v, limit=None):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return None
    return s[:limit] if limit else s


def _decimal(v):
    s = _text(v)
    if s is None:
        return None
    s = s.replace(',', '').replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _row_values(row, available):
    """The product columns this upload row can supply, coerced and length-capped."""
    out = {}
    for src, col in _FIELD_MAP:
        if col not in available or col in out:
            continue
        raw = row.get(src)
        if col in ('gst_percent', 'price'):
            val = _decimal(raw)
        elif col == 'hsn_code':
            val = _text(raw, 20)
        elif col == 'uom':
            val = _text(raw, 20)
        elif col == 'name':
            val = _text(raw, 255)
        else:
            val = _text(raw)
        if val is not None:
            out[col] = val
    return out


def sync_products(df, company_id):
    """Create missing products and fill blanks on existing ones.

    Returns {'created': n, 'enriched': n, 'unchanged': n}. Nothing is deleted, and no
    already-populated field is overwritten.
    """
    if 'Part #' not in df.columns:
        return {'created': 0, 'enriched': 0, 'unchanged': 0}

    available = _existing_columns()
    now = datetime.utcnow()

    # One row per part: a challan can list the same part twice, and the later row's
    # detail merges into the earlier rather than issuing two writes for one product.
    wanted = {}
    for _, row in df.iterrows():
        part = _text(row.get('Part #'), 100)
        if not part:
            continue
        wanted.setdefault(part, {}).update(_row_values(row, available))
    if not wanted:
        return {'created': 0, 'enriched': 0, 'unchanged': 0}

    parts = list(wanted)
    ph = ','.join(['%s'] * len(parts))
    cols = ['product_id', 'product_string'] + [c for c in _OPTIONAL if c in available] + ['name']
    existing = {r['product_string']: r for r in (mysql_manager.execute_query(
        f"SELECT {', '.join(sorted(set(cols)))} FROM product WHERE product_string IN ({ph})",
        tuple(parts)) or [])}

    created = enriched = unchanged = 0
    with mysql_manager.get_cursor() as cursor:
        for part, values in wanted.items():
            prior = existing.get(part)
            if prior is None:
                # name is NOT NULL; fall back to the part number when the document had
                # no description rather than failing the whole upload on one blank cell.
                values.setdefault('name', part)
                columns = ['product_string', 'company_id', 'created_at', 'updated_at'] + list(values)
                placeholders = ','.join(['%s'] * len(columns))
                cursor.execute(
                    f"INSERT IGNORE INTO product ({', '.join(columns)}) VALUES ({placeholders})",
                    (part, company_id, now, now, *values.values()))
                created += 1
                continue

            # Fill blanks only. A value already on the product stays as it is.
            fill = {c: v for c, v in values.items()
                    if prior.get(c) in (None, '') and c in available}
            if not fill:
                unchanged += 1
                continue
            assignments = ', '.join(f"{c} = %s" for c in fill)
            cursor.execute(
                f"UPDATE product SET {assignments}, updated_at = %s WHERE product_id = %s",
                (*fill.values(), now, prior['product_id']))
            enriched += 1

    # Prefixed keys: 'created' is a reserved LogRecord attribute (the record's own
    # timestamp) and logging raises KeyError rather than shadowing it, which fails the
    # whole upload from inside a log call.
    logger.info("products synced from upload", extra={
        'company_id': company_id, 'products_created': created,
        'products_enriched': enriched, 'products_unchanged': unchanged})
    return {'created': created, 'enriched': enriched, 'unchanged': unchanged}
