# -*- encoding: utf-8 -*-
"""Ingestion service — a supplier PDF becomes stock in one pass.

    GRN line
     ├─ product                reuse if it exists, create it if it does not
     ├─ sku_batch              reuse the batch if it exists, else create it
     ├─ transferin_info        one row per invoice line, transferin_id = the invoice
     ├─ fc_entity_stock        quantity at location 8 (unstacked)
     ├─ fc_entity_stock_ledger the movement
     └─ fc_sku_price_details   MRP and landing price for that SKU in that batch

The invoice itself is NOT stored. Its lines are the `transferin_info` rows, and everything
the paperwork said beyond product, quantity, MRP and rate is discarded once parsed.

Credit and debit notes move no goods — their printed quantity is the basis a price
correction is charged over, not stock. They resolve the product and batch only so the
adjustment lands on the right one, then write to `fc_sku_price_details` alone.
"""

import hashlib
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal

from api.core.logging import get_logger
from api.shared.db_manager import mysql_manager
from api.modules.inventory.ingestion import parser_cadila as parser

logger = get_logger(__name__)

UNSTACKED_LOCATION_ID = 8      # planogram_locations: 'unstacked', picking enabled
DEFAULT_BIN_ID = 0
ENTITY_TYPE = 'sku'
DEFAULT_UOM = 'strip'          # what Qty (STP) counts, and what the catalogue holds

# The invoice's UOM code mapped onto the catalogue's vocabulary. Only consulted when the
# line has no Qty (STP): where STP is given it is the basis, and the basis is strips.
UOM_CODES = {'STP': 'strip', 'BOX': 'box', 'BT': 'bottle', 'VIA': 'vial', 'TUB': 'tube',
             'NOS': 'nos', 'JAR': 'jar', 'KIT': 'kit', 'AMP': 'ampoule', 'PCS': 'pcs'}

# One transferin_type per document kind, so a receipt and a note are distinguishable even
# where their numbering overlaps.
TRANSFERIN_TYPES = {'GRN': 'CADILA_GRN', 'CREDIT_NOTE': 'CADILA_CN', 'DN': 'CADILA_DN'}

# Optional guard against posting another distributor's invoice into this tenant's stock.
# Cadila prints the buyer's GSTIN on every document; set CADILA_BUYER_GSTIN to have a
# mismatch refused. Left unset the buyer is reported but not enforced, because there is
# no GSTIN on the company record to check against.
EXPECTED_BUYER_GSTIN = (os.environ.get('CADILA_BUYER_GSTIN') or '').strip().upper()

# The effective cost is computed where it is read, not stored:
#
#     final landing price = landing_price - cn_rate
#
# cn_rate holds the note's printed rate as a positive number and is SET, never
# accumulated — writing the same value twice is the same as writing it once, so a
# re-uploaded note is harmless without any extra bookkeeping.


class IngestionError(ValueError):
    """Refused: bad input, or a state that must not be written."""


class MissingProductsError(IngestionError):
    """Refused because the catalogue does not have every product on the document.

    Carries the offending lines so the screen can list exactly what to add to the master,
    rather than making the operator open the PDF and compare it by eye.
    """

    def __init__(self, message, missing=None, doc_number=None, doc_type=None):
        super().__init__(message)
        self.missing = missing or []
        self.doc_number = doc_number
        self.doc_type = doc_type


DOC_TYPE_LABELS = {'GRN': 'Tax invoice', 'CREDIT_NOTE': 'Credit note', 'DN': 'Debit note'}


def doc_type_label(doc_type):
    return DOC_TYPE_LABELS.get(doc_type, doc_type)


# ── Batch identity ───────────────────────────────────────────────────────────
def batch_hash(sku_id, batch_number, expiry_date):
    """Identity of a physical batch: SKU + batch number + expiry. MRP is NOT included.

    Batch number plus expiry is the regulatory identity — one manufacturing lot, one
    recall unit — which is the grain FEFO and returns both need. MRP is commercial: the
    same lot can be re-priced without becoming a different lot, so it lives in
    fc_sku_price_details. Including it would also fork a phantom batch on every credit
    note, since the supplier prints MRP 0.00 on all of them.
    """
    key = f"{int(sku_id)}|{(batch_number or '').strip().upper()}|{expiry_date or ''}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def resolve_batch(cursor, company_id, sku_id, batch_number, expiry_date):
    """Reuse the batch when it already exists, otherwise create it."""
    digest = batch_hash(sku_id, batch_number, expiry_date)
    cursor.execute("SELECT id FROM sku_batch WHERE batch_hash = %s", (digest,))
    row = cursor.fetchone()
    if row:
        return row['id'] if isinstance(row, dict) else row[0]

    cursor.execute(
        """INSERT INTO sku_batch (sku_id, batch_hash, batch_params, company_id,
                                  created_by, updated_by)
           VALUES (%s, %s, %s, %s, 'ingestion', 'ingestion')""",
        (sku_id, digest, json.dumps({
            'batch_number': (batch_number or '').strip().upper(),
            'expiry': str(expiry_date) if expiry_date else None,
            'source': 'cadila_ingestion',
        }), company_id))
    return cursor.lastrowid


# ── Product: reuse or create ─────────────────────────────────────────────────
def _slug(text, limit=40):
    out = re.sub(r'[^A-Za-z0-9]+', '-', (text or '').upper()).strip('-')
    return out[:limit] or 'ITEM'


def _unique_product_string(cursor, prefix, name, pack):
    """A product_string that is free.

    `product.product_string` is UNIQUE across the WHOLE table — not scoped by company — so
    a generated code shares one namespace with every other tenant's. The company prefix
    keeps them apart by construction; the counter closes the remainder.
    """
    base = (f"{prefix}-{_slug(name)}" + (f"-{_slug(pack, 12)}" if pack else ''))[:90]
    candidate, n = base, 1
    while True:
        cursor.execute("SELECT product_id FROM product WHERE product_string = %s",
                       (candidate,))
        if not cursor.fetchone():
            return candidate
        n += 1
        candidate = f"{base[:90 - len(str(n)) - 1]}-{n}"


def resolve_or_create_product(cursor, company_id, prefix, line):
    """The SKU this line refers to, creating it when the catalogue has no such product.

    Cadila prints its own product code on every line (CHC143V, ILD21AB), and the catalogue
    already stores those codes in product_string — they came in with the product master.
    So the code is the identity, matched exactly.

    That is a real improvement over matching on the printed name, which is what the
    previous supplier document forced. The names do not agree between systems
    ("CAMPICILLIN CAPSULES IP (250 mg)" against "CAMPICILLIN 250 CAP"), so name matching
    quietly created a second product for goods that were already in the catalogue.

    Name matching is kept only as a fallback for a line whose code is not yet in the
    master, and creating a product is the last resort.
    """
    product_id = _lookup_product(cursor, company_id, prefix, line)
    if product_id is not None:
        return product_id, 'existing'

    code = (line.get('product_code') or '').strip().upper()
    name = (line['raw_product_name'] or '').strip()
    new_code = code or _unique_product_string(cursor, prefix, name, line['raw_pack'])
    uom = _line_uom(line)
    cursor.execute(
        """INSERT INTO product
             (company_id, product_string, name, description, hsn_code, uom, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, 1)""",
        (company_id, new_code, name or new_code,
         f"{line.get('raw_pack') or ''} · {line.get('manufacturer') or ''}".strip(' ·'),
         line.get('hsn') or None, uom))
    logger.info("created product %s for company %s", new_code, company_id)
    return cursor.lastrowid, 'created'


def _lookup_product(cursor, company_id, prefix, line):
    """The product this line refers to, or None if the master does not have it.

    Pure lookup apart from stamping a code onto a row that was found by name — that write
    only ever fills a slot the master left empty, so it cannot change what the catalogue
    means.
    """
    code = (line.get('product_code') or '').strip().upper()
    name = (line.get('raw_product_name') or '').strip()
    if not code and not name:
        raise IngestionError('line has neither a product code nor a name')

    if code:
        cursor.execute(
            "SELECT product_id FROM product WHERE company_id = %s AND product_string = %s"
            " LIMIT 1", (company_id, code))
        row = cursor.fetchone()
        if row:
            return row['product_id'] if isinstance(row, dict) else row[0]

    if name:
        # Compared with spaces and full stops stripped, because the master's names carry
        # double spaces ('CAMPICILLIN 250  CAP') that the invoice prints singly. Exact
        # matching missed by that one character and created a second product for goods
        # already in the catalogue — the cause of every orphaned CADI- row in the table.
        #
        # A master row wins over a generated one when both somehow match, so this can only
        # ever converge on the catalogue's own entry.
        cursor.execute(
            "SELECT product_id FROM product"
            " WHERE company_id = %s"
            "   AND REPLACE(REPLACE(UPPER(name), ' ', ''), '.', '') = %s"
            " ORDER BY product_string LIKE %s, product_id LIMIT 1",
            (company_id, name.upper().replace(' ', '').replace('.', ''), f'{prefix}-%'))
        row = cursor.fetchone()
        if row:
            product_id = row['product_id'] if isinstance(row, dict) else row[0]
            # Found by name because the code was missing from the master. Stamp the code
            # on so the next document matches on it directly — but only into an empty or
            # generated slot, never over a code the master already set.
            if code:
                cursor.execute(
                    "UPDATE product SET product_string = %s WHERE product_id = %s"
                    "   AND (product_string IS NULL OR product_string LIKE %s)",
                    (code, product_id, f'{prefix}-%'))
            return product_id

    return None


def missing_from_master(cursor, company_id, prefix, lines):
    """The lines whose product the catalogue does not have.

    Run before anything is written. A receipt for a product nobody has set up carries no
    category, no pack and no UOM beyond what one invoice happened to print, and it lands
    in the catalogue looking exactly like a real entry — so the master is corrected first
    and the document re-uploaded, rather than the document quietly extending the master.
    """
    missing, seen = [], set()
    for line in lines:
        code = (line.get('product_code') or '').strip().upper()
        name = (line.get('raw_product_name') or '').strip()
        if (code, name) in seen:
            continue
        seen.add((code, name))
        if _lookup_product(cursor, company_id, prefix, line) is None:
            missing.append({'product_code': code, 'product_name': name,
                            'pack': line.get('raw_pack') or ''})
    return missing


def _line_uom(line):
    """What one unit of this line's quantity is.

    Qty (STP) counts strips, so wherever it is given the unit is a strip regardless of the
    UOM code printed beside the trade pack. Only lines billed in the unit itself — bottles,
    vials, jars — take their UOM from the document.
    """
    if line.get('stp_basis'):
        return DEFAULT_UOM
    return UOM_CODES.get((line.get('uom') or '').strip().upper(), DEFAULT_UOM)


def _transferin_type_id(cursor, doc_type):
    name = TRANSFERIN_TYPES.get(doc_type, 'CADILA_GRN')
    cursor.execute("SELECT id FROM transferin_type WHERE transferin_type_name = %s",
                   (name,))
    row = cursor.fetchone()
    if row:
        return row['id'] if isinstance(row, dict) else row[0]
    cursor.execute("INSERT INTO transferin_type (transferin_type_name) VALUES (%s)",
                   (name,))
    return cursor.lastrowid


def _already_received(planogram_id, type_id, transferin_id, company_id):
    """Has this invoice already been taken in?

    Without an invoice table there is no unique key to lean on, so this is an application
    check against the rows the last run would have written. It is what stops a re-uploaded
    GRN from adding its quantities a second time.
    """
    rows = mysql_manager.execute_query(
        """SELECT 1 FROM transferin_info
            WHERE planogram_id = %s AND transferin_type_id = %s
              AND transferin_id = %s AND company_id = %s LIMIT 1""",
        (planogram_id, type_id, transferin_id, company_id))
    return bool(rows)


# ── Ingest ───────────────────────────────────────────────────────────────────
def ingest_pdf(stream, filename, company_id, warehouse_id, user='system',
               movement_effect=None):
    """Parse one PDF and carry every document in it through to stock and price details.

    Returns a LIST. Cadila batches its credit notes — a single file routinely holds ten
    unrelated notes, each with its own number and IRN — so treating a file as one document
    would silently discard nine real cost adjustments.

    Each document commits in its own transaction. One malformed note therefore cannot
    roll back nine good ones, and a file that fails halfway reports exactly which
    documents landed rather than leaving the caller to guess.
    """
    docs = parser.parse_documents(stream, filename)
    if not docs:
        raise IngestionError('no Cadila document found in this file')

    results, rejected = [], []
    for doc in docs:
        try:
            results.append(_ingest_document(doc, company_id, warehouse_id, user,
                                            movement_effect))
        except IngestionError as e:
            # One refused document does not condemn the rest of the file. Ten credit notes
            # arrive together and only one may name an unknown product; ingesting the nine
            # and naming the tenth is more useful than refusing all ten. Re-uploading the
            # file after the master is fixed is safe — the nine come back as duplicates.
            rejected.append({
                'doc_number': getattr(e, 'doc_number', None) or doc.get('doc_number'),
                'doc_type': getattr(e, 'doc_type', None) or doc.get('doc_type'),
                'error': str(e),
                'missing_products': getattr(e, 'missing', []),
            })
    return results, rejected


def _ingest_document(doc, company_id, warehouse_id, user='system', movement_effect=None):
    """One parsed document -> stock and price details, in ONE transaction.

    A receipt that created a product and a batch but failed before writing stock would
    leave catalogue entries for goods that never arrived, so it all commits or none does.
    """
    if not doc['doc_number']:
        raise IngestionError('document number not found on the file')

    # Cadila prints the buyer on every document. Enforced only when the tenant's GSTIN has
    # been configured — without it there is nothing to compare against, and refusing on a
    # guess would block legitimate receipts.
    buyer = (doc.get('buyer_gstin') or '').strip().upper()
    if EXPECTED_BUYER_GSTIN and buyer and buyer != EXPECTED_BUYER_GSTIN:
        raise IngestionError(
            f"this document is billed to {buyer}, not to this business "
            f"({EXPECTED_BUYER_GSTIN}) — it belongs to another distributor")

    doc_type = doc['doc_type']
    transferin_id = doc['doc_number']          # the invoice / credit note number, verbatim
    effect = movement_effect or ('IN' if doc_type == 'GRN' else 'NONE')
    moves_stock = effect in ('IN', 'OUT')
    direction = -1 if effect == 'OUT' else 1
    planogram_id = int(warehouse_id or 1)

    companies = mysql_manager.execute_query(
        "SELECT name FROM company WHERE company_id = %s", (company_id,))
    prefix = _slug(companies[0]['name'], 4) if companies else 'PROD'

    created_products, received, adjusted, pending = [], 0, 0, 0

    with mysql_manager.get_cursor() as cur:
        # Nothing is written until every line is known to the catalogue. Raising here
        # rolls the transaction back, so a refused document leaves no product, no batch
        # and no stock behind — the operator fixes the master and uploads the same file
        # again, which is why this must come before the first insert rather than after.
        unknown = missing_from_master(cur, company_id, prefix, doc['lines'])
        if unknown:
            listed = '; '.join(
                f"{u['product_code'] or '(no code)'} {u['product_name']}".strip()
                for u in unknown[:8])
            more = f" and {len(unknown) - 8} more" if len(unknown) > 8 else ''
            raise MissingProductsError(
                f"{doc_type_label(doc_type)} {doc['doc_number']} was not ingested: "
                f"{len(unknown)} product(s) are not in the product master — {listed}"
                f"{more}. Add them to the master, then upload this file again.",
                missing=unknown, doc_number=doc['doc_number'], doc_type=doc_type)

        type_id = _transferin_type_id(cur, doc_type)

        # A re-upload must not add stock twice, but it SHOULD still refresh the price
        # details — those are derived, so rewriting them with the same figures is a no-op,
        # and it makes the table self-healing if it is ever lost or wrong. Returning early
        # instead would leave the only copy of the landing price unrecoverable from a file
        # you still hold.
        duplicate = moves_stock and _already_received(planogram_id, type_id,
                                                      transferin_id, company_id)

        for line in doc['lines']:
            sku_id, how = resolve_or_create_product(cur, company_id, prefix, line)
            if how == 'created':
                created_products.append(line['raw_product_name'])
            batch_id = resolve_batch(cur, company_id, sku_id, line['raw_batch'],
                                     line['expiry_date'])

            if moves_stock:
                if not duplicate:
                    _receive_line(cur, doc, line, company_id, planogram_id, type_id,
                                  transferin_id, sku_id, batch_id, direction)
                    received += 1
            else:
                state = _apply_note(cur, doc, line, company_id, planogram_id, sku_id,
                                    batch_id)
                if state == 'pending':
                    pending += 1
                    doc['warnings'].append(
                        f"{line['raw_product_name']} batch {line['raw_batch']}: no receipt "
                        "for this batch yet, so the price difference is held and will "
                        "apply when its invoice is ingested")
                else:
                    adjusted += 1
                continue

            _upsert_price_from_receipt(cur, company_id, planogram_id, sku_id, batch_id,
                                       line, doc['doc_number'], count_qty=not duplicate)

    logger.info("ingested %s %s: %d lines, %d products created, %d received, %d adjusted,"
                " %d pending", doc_type, doc['doc_number'], len(doc['lines']),
                len(created_products), received, adjusted, pending)
    return {'duplicate': duplicate, 'doc_number': doc['doc_number'], 'parsed': doc,
            'created_products': created_products, 'received': received,
            'adjusted': adjusted, 'pending': pending,
            'moved_stock': moves_stock and not duplicate}


def _meta_json(doc, line):
    """The document's identifiers, stored beside the line, as JSON that fits the column.

    meta_info is VARCHAR(500) and the IRN alone is 64 characters, so an unusually long
    pack or product name could overflow. Truncating the string would produce invalid JSON
    and the screen parses this field to show the invoice and batch — so the optional keys
    are dropped one at a time instead, leaving a shorter document that still parses.

    The IRN is kept where it fits: it is the government-registered hash of the invoice,
    unique by construction, so a receipt can be traced to the exact paper that created it
    even after the file itself is gone.
    """
    meta = {'invoice': doc['doc_number'], 'date': str(doc['doc_date'] or ''),
            'pack': line.get('raw_pack') or '', 'batch': line.get('raw_batch') or '',
            'code': line.get('product_code') or '',
            'order': doc.get('order_number') or '',
            'delivery': doc.get('delivery_number') or '',
            'irn': doc.get('irn') or ''}
    for optional in ('irn', 'delivery', 'order', 'code', 'pack'):
        blob = json.dumps(meta)
        if len(blob) <= 500:
            return blob
        meta.pop(optional, None)
    return json.dumps(meta)[:500] if len(json.dumps(meta)) <= 500 else json.dumps(
        {'invoice': doc['doc_number'], 'batch': line.get('raw_batch') or ''})


def _receive_line(cur, doc, line, company_id, planogram_id, type_id, transferin_id,
                  sku_id, batch_id, direction):
    """One invoice line -> transferin_info + fc_entity_stock + ledger."""
    qty = float(line['quantity']) * direction

    # unstacked_quantity starts equal to quantity: nothing has been put away yet. The
    # fc_entity_stock row at location 8 below is the same stock seen from the other side,
    # and a stacking job later decrements both together. On-hand is read from
    # fc_entity_stock alone — summing unstacked_quantity on top would double-count.
    cur.execute(
        """INSERT INTO transferin_info
             (planogram_id, transferin_id, transferin_type_id, entity_id, entity_type,
              batch_id, quantity, unstacked_quantity, vbin_id, cost_price, mrp,
              transferin_status, meta_info, company_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,'received',%s,%s)""",
        (planogram_id, transferin_id, type_id, sku_id, ENTITY_TYPE, batch_id,
         abs(qty), abs(qty), line['rate'], line['mrp'],
         _meta_json(doc, line),
         company_id))
    transferin_row_id = cur.lastrowid

    cur.execute(
        """INSERT INTO fc_entity_stock
             (planogram_id, location_id, bin_id, bin_location, entity_id, entity_type,
              batch_id, bin_priority_order, quantity, company_id, created_by, updated_by)
           VALUES (%s,%s,%s,'',%s,%s,%s,0,%s,%s,'ingestion','ingestion')
           ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity),
                                   company_id = VALUES(company_id)""",
        (planogram_id, UNSTACKED_LOCATION_ID, DEFAULT_BIN_ID, sku_id, ENTITY_TYPE,
         batch_id, qty, company_id))

    cur.execute(
        """SELECT quantity FROM fc_entity_stock
            WHERE planogram_id=%s AND location_id=%s AND bin_id=%s AND entity_id=%s
              AND entity_type=%s AND batch_id=%s""",
        (planogram_id, UNSTACKED_LOCATION_ID, DEFAULT_BIN_ID, sku_id, ENTITY_TYPE,
         batch_id))
    after = cur.fetchone()
    after_qty = (after['quantity'] if isinstance(after, dict) else after[0]) if after else qty

    cur.execute(
        """INSERT INTO fc_entity_stock_ledger
             (planogram_id, location_id, bin_id, entity_id, entity_type, batch_id,
              quantity_changed, quantity_after_change, reference_id, reference_type,
              cost_price, company_id, created_by, updated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ingestion','ingestion')""",
        (planogram_id, UNSTACKED_LOCATION_ID, DEFAULT_BIN_ID, sku_id, ENTITY_TYPE,
         batch_id, qty, after_qty, transferin_row_id, doc['doc_type'], line['rate'],
         company_id))


# ── Price details ────────────────────────────────────────────────────────────
def _upsert_price_from_receipt(cur, company_id, planogram_id, sku_id, batch_id, line,
                               invoice_ref, count_qty=True):
    """A receipt sets MRP, landing price and the GST rate for this SKU in this batch."""
    # However the supplier split it between CGST/SGST and IGST — which depends on which
    # Cadila depot shipped — the total is what grosses the cost up, so the parser hands
    # over one combined rate derived from the tax actually charged.
    gst_rate = float(line.get('gst_rate') or 0)
    cur.execute(
        """INSERT INTO fc_sku_price_details
             (company_id, planogram_id, entity_id, entity_type, batch_id, mrp,
              landing_price, gst_rate, uom, quantity_received, grn_reference,
              created_by, updated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ingestion','ingestion')
           ON DUPLICATE KEY UPDATE mrp = VALUES(mrp),
                                   landing_price = VALUES(landing_price),
                                   gst_rate = VALUES(gst_rate),
                                   quantity_received = IF(%s, quantity_received
                                                             + VALUES(quantity_received),
                                                          quantity_received),
                                   grn_reference = VALUES(grn_reference),
                                   updated_by = 'ingestion'""",
        (company_id, planogram_id, sku_id, ENTITY_TYPE, batch_id, line['mrp'],
         line['rate'], round(gst_rate, 2), _line_uom(line), line['quantity'], invoice_ref,
         1 if count_qty else 0))


def _apply_note(cur, doc, line, company_id, planogram_id, sku_id, batch_id):
    """Record a credit note's per-unit price difference against the batch it adjusts.

    Returns 'applied' when the batch has a receipt to reduce, 'pending' when it does not.

    A price-difference note can arrive before the invoice it corrects. The rate is stored
    either way — losing it would leave the adjustment unrecoverable from a file that has
    already been filed — but the caller is told, because until the receipt lands the batch
    reads as landing_price 0 less the note, which is a negative cost. It self-corrects the
    moment the invoice is ingested, since that sets landing_price on this same row.

    SET, not accumulated. A re-uploaded note is therefore a no-op, which matters because
    there is no invoice table to check against. The trade-off is that a second, genuinely
    different note against the same batch replaces the first rather than adding to it.
    """
    cur.execute(
        """SELECT landing_price FROM fc_sku_price_details
            WHERE company_id = %s AND entity_id = %s AND batch_id = %s LIMIT 1""",
        (company_id, sku_id, batch_id))
    row = cur.fetchone()
    landing = float((row['landing_price'] if isinstance(row, dict) else row[0]) or 0) if row else 0.0

    cur.execute(
        """INSERT INTO fc_sku_price_details
             (company_id, planogram_id, entity_id, entity_type, batch_id, cn_rate,
              cn_reference, uom, created_by, updated_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'ingestion','ingestion')
           ON DUPLICATE KEY UPDATE cn_rate = VALUES(cn_rate),
                                   cn_reference = VALUES(cn_reference),
                                   updated_by = 'ingestion'""",
        (company_id, planogram_id, sku_id, ENTITY_TYPE, batch_id,
         abs(float(line['rate'])), doc['doc_number'], _line_uom(line)))
    return 'applied' if landing > 0 else 'pending'


# ── Reads for the admin screen ───────────────────────────────────────────────
def jsonable(value):
    """Coerce DB values Flask-RESTX's JSON encoder cannot serialise.

    MySQL hands back DATE/DATETIME as date objects and DECIMAL as Decimal, and the encoder
    raises TypeError on both — so a read is fine while the table is empty and 500s the
    moment it holds a row.
    """
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def list_received(company_ids=None, warehouse_id=None, limit=200, offset=0, docs=None):
    """What has been taken in — transferin_info joined to the product, batch and price.

    `docs` narrows the result to specific document numbers (transferin_id). The screen
    uses it to show ONLY the lines of the file just uploaded: this is a confirmation of
    what an upload did, not a stock report, and listing every past receipt made a fresh
    upload impossible to pick out. With no docs given the caller gets nothing, so the
    view cannot fall back to showing history by accident.
    """
    if docs is not None and not docs:
        return []
    where, params = ['1=1'], []
    if docs:
        where.append('t.transferin_id IN (%s)' % ','.join(['%s'] * len(docs)))
        params += list(docs)
    if company_ids is not None:
        if not company_ids:
            return []
        where.append('t.company_id IN (%s)' % ','.join(['%s'] * len(company_ids)))
        params += list(company_ids)
    if warehouse_id:
        where.append('t.planogram_id = %s')
        params.append(int(warehouse_id))
    params += [limit, offset]
    return jsonable(mysql_manager.execute_query(
        f"""SELECT t.id, t.transferin_id, t.meta_info, t.entity_id, t.batch_id,
                   t.quantity, t.unstacked_quantity, t.cost_price, t.mrp,
                   t.created_on, t.company_id,
                   p.name AS product_name, p.product_string AS sku_code,
                   b.batch_params,
                   pr.landing_price, pr.cn_rate, pr.gst_rate, pr.mrp AS batch_mrp,
                   (pr.landing_price - pr.cn_rate) AS final_landing_price,
                   ROUND((pr.landing_price - pr.cn_rate)
                         * (1 + pr.gst_rate / 100), 4) AS final_landing_inc_gst,
                   pr.grn_reference, pr.cn_reference
              FROM transferin_info t
              LEFT JOIN product p   ON p.product_id = t.entity_id
              LEFT JOIN sku_batch b ON b.id = t.batch_id
              LEFT JOIN fc_sku_price_details pr
                     ON pr.entity_id = t.entity_id AND pr.batch_id = t.batch_id
                    AND pr.company_id = t.company_id
             WHERE {' AND '.join(where)}
             ORDER BY t.id DESC LIMIT %s OFFSET %s""",
        tuple(params)) or [])


# ── Batch costing report ─────────────────────────────────────────────────────
# Every figure below is DERIVED from the three stored rates (landing_price, cn_rate,
# gst_rate) and the received quantity. Nothing here is a second copy of a stored value,
# so the report cannot disagree with the inventory it describes.
#
#     amount (invoice)  = qty * landing_price
#     amount (CN/DN)    = -(qty * cn_rate)          negative: it reduces the cost
#     final amount      = the two summed
#     net amount        = amount * (1 + gst_rate/100)
#     landed ex-GST     = landing_price - cn_rate
#     landed inc-GST    = landed ex-GST * (1 + gst_rate/100)
#     margin @+N%       = landed inc-GST * (1 + N/100)
_REPORT_SQL = """
SELECT  p.name                                        AS product_name,
        p.product_string                              AS sku_code,
        p.hsn_code                                    AS hsn,
        -- Ingestion writes the description as 'PACK · MFR'; the pack is its first part.
        SUBSTRING_INDEX(COALESCE(p.description, ''), ' · ', 1) AS pack,
        JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.batch_number')) AS batch_number,
        DATE_FORMAT(
            JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.expiry')), '%%c/%%y') AS exp,
        pr.quantity_received                          AS qty,
        pr.uom                                        AS uom,
        pr.gst_rate                                   AS gst_rate,
        pr.mrp                                        AS mrp,

        pr.landing_price                              AS rate_invoice,
        ROUND(pr.quantity_received * pr.landing_price, 2)                    AS amount_invoice,
        ROUND(pr.quantity_received * pr.landing_price
              * (1 + pr.gst_rate / 100), 2)                                  AS net_amount_invoice,

        -pr.cn_rate                                   AS rate_cn,
        ROUND(-pr.quantity_received * pr.cn_rate, 2)                         AS amount_cn,
        ROUND(-pr.quantity_received * pr.cn_rate
              * (1 + pr.gst_rate / 100), 2)                                  AS net_amount_cn,

        ROUND(pr.quantity_received * (pr.landing_price - pr.cn_rate), 2)     AS final_amount,
        ROUND(pr.quantity_received * (pr.landing_price - pr.cn_rate)
              * (1 + pr.gst_rate / 100), 2)                                  AS final_net_amount,

        ROUND(pr.landing_price - pr.cn_rate, 4)                              AS landed_ex_gst,
        ROUND((pr.landing_price - pr.cn_rate)
              * (1 + pr.gst_rate / 100), 4)                                  AS landed_inc_gst,
        ROUND((pr.landing_price - pr.cn_rate)
              * (1 + pr.gst_rate / 100) * 1.05, 4)                           AS margin_5,
        ROUND((pr.landing_price - pr.cn_rate)
              * (1 + pr.gst_rate / 100) * 1.10, 4)                           AS margin_10,
        ROUND((pr.landing_price - pr.cn_rate)
              * (1 + pr.gst_rate / 100) * 1.15, 4)                           AS margin_15,

        TRIM(BOTH ', ' FROM CONCAT_WS(', ', NULLIF(pr.grn_reference, ''),
                                            NULLIF(pr.cn_reference, '')))    AS doc_nos,
        pr.company_id, pr.entity_id AS sku_id, pr.batch_id
  FROM  fc_sku_price_details pr
  JOIN  product   p ON p.product_id = pr.entity_id
  LEFT JOIN sku_batch b ON b.id = pr.batch_id
 WHERE  {where}
 ORDER BY p.name, batch_number
 LIMIT %s OFFSET %s
"""


def batch_costing_report(company_ids=None, search=None, limit=2000, offset=0):
    """One row per SKU + batch: what it cost, what it retails for, and the margin.

    batch_id 0 is excluded. That row is a supplier LIST RATE loaded from a price list by
    the product-master upload (see catalog/product_pack.py) — a rate for goods that have
    not been received. Including it would put a line in a costing report for stock that
    never arrived, with a blank batch number and a quantity of zero.
    """
    where, params = ['pr.batch_id > 0'], []
    if company_ids is not None:
        if not company_ids:
            return []
        where.append('pr.company_id IN (%s)' % ','.join(['%s'] * len(company_ids)))
        params += list(company_ids)
    if search:
        where.append("(p.name LIKE %s OR p.product_string LIKE %s"
                     " OR JSON_UNQUOTE(JSON_EXTRACT(b.batch_params,'$.batch_number')) LIKE %s)")
        params += [f'%{search}%'] * 3
    params += [limit, offset]
    return jsonable(mysql_manager.execute_query(
        _REPORT_SQL.format(where=' AND '.join(where)), tuple(params)) or [])
