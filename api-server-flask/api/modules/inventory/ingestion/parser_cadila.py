# -*- encoding: utf-8 -*-
"""PDF parser for Cadila Pharmaceuticals' own documents.

Two templates, both e-invoice generated and both machine-clean:

  TAX INVOICE               goods received     -> stock IN, sets landed cost
  CREDIT NOTE (PRICE DIFF)  rate revised down  -> no stock movement, lowers landed cost

Design notes
------------
1. **One file can hold many documents.** The credit notes arrive as a single PDF with a
   separate note per page, each with its own number and IRN. Pages are therefore grouped
   by document number rather than assumed to be one document, which also handles an
   invoice whose line items run over a page.

2. **Columns are located by header label, not by position.** The two templates have
   different widths (22 columns vs 19) and Cadila can add a column without warning.
   Reading `row[13]` would then silently return the wrong field; reading the column
   under "P.Diff/ Unit" either finds it or fails loudly.

3. **Printed values are checked against each other, never trusted alone.** Every invoice
   line carries its own proof:

       PTR/TP x qty          == PTR/TP Value
       PTR/TP Value - Scheme == Transaction Value
       Transaction Value/qty == PTS

   A mis-read column breaks one of these, so a bad parse surfaces as a warning instead of
   as wrong stock. The unit rate is taken from Transaction Value / qty rather than from
   the printed PTS, because PTS is rounded to 3dp and the value column is exact.

4. **The printed GST rate on a credit note is wrong by a factor of ten** — it shows 0.5
   where the tax is 5%, and 0.25 where it is 2.5%. The rate is therefore always computed
   from the tax amount over the assessable value, on both templates.
"""

import hashlib
import io
import re
from calendar import monthrange
from datetime import date

import pdfplumber

from api.modules.inventory.ingestion.parser import ParseError


# A Cadila product code: 7 characters, letter first. The shape varies more than it looks
# (CHC143V, LQD07AG, ILD21AB, TBCAH2P), so anything tighter than this drops real lines.
PRODUCT_CODE = re.compile(r'^[A-Z][A-Z0-9]{6}$')

DOC_INVOICE = 'GRN'            # keeps the transferin_type the rest of the app already uses
DOC_CREDIT_NOTE = 'CREDIT_NOTE'

# Header labels, normalised to single-spaced lowercase, mapped to the field they carry.
_INVOICE_COLUMNS = {
    'product code': 'code', 'hsn': 'hsn', 'product description': 'description',
    'pack': 'pack', 'batch no.': 'batch', 'expiry date': 'expiry',
    'billed qty': 'billed_qty', 'free qty': 'free_qty', 'uom': 'uom',
    'qty (stp)': 'stp_qty', 'mrp': 'mrp', 'ptr / tp': 'ptr', 'pts': 'pts',
    'ptr / tp value': 'ptr_value', 'scheme value': 'scheme_value',
    'td%': 'td_pct', 'transaction value': 'txn_value',
    "manufacturer's details": 'manufacturer',
}
_NOTE_COLUMNS = {
    'product code': 'code', 'hsn of goods': 'hsn', 'product description': 'description',
    'pack size': 'pack', 'batch no.': 'batch', 'expire date': 'expiry',
    'qty': 'qty', 'uom': 'uom', 'pts': 'pts_value', 'p.diff/ unit': 'diff_unit',
    'total price differnce': 'diff_total',      # Cadila's spelling, kept verbatim
    'ref. group inv.': 'ref_group_invoice', 'ref. child inv.': 'ref_child_invoice',
    'ref . child inv. dt.': 'ref_child_invoice_date',
}
# The GST column's label wraps differently between releases; matched by prefix.
_GST_LABEL_PREFIX = 'sgst /'


def _norm(cell):
    """Collapse a table cell to single-spaced text. Header labels wrap over two or three
    lines ('Expiry\\nDate'), so comparing raw cells to labels would never match."""
    return re.sub(r'\s+', ' ', (cell or '').replace('\n', ' ')).strip()


def _num(cell):
    """A number as Cadila prints it: thousands separators, and sometimes a line break
    mid-number ('126,720.00\\n0' is 126720.000). The break is closed up, not spaced."""
    if cell is None:
        return None
    txt = re.sub(r'[\s,]', '', str(cell))
    if not txt or txt in ('-', '.'):
        return None
    m = re.match(r'^-?\d*\.?\d+', txt)
    return float(m.group(0)) if m else None


def _month_end(raw):
    """MM/YYYY -> the last day of that month.

    Pharma expiry is stated to the month and the goods are saleable through it, so the
    deadline is the month's end. Matches the convention already in sku_batch.
    """
    m = re.match(r'^(\d{1,2})\s*/\s*(\d{2,4})$', (raw or '').strip())
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if year < 100:
        year += 2000
    if not 1 <= month <= 12:
        return None
    return date(year, month, monthrange(year, month)[1])


def _doc_date(raw):
    """DD.MM.YYYY — Cadila's separator. (The Marg template used '-'.)"""
    m = re.match(r'^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$', (raw or '').strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _find(text, pattern, group=1):
    m = re.search(pattern, text, re.I)
    return (m.group(group) or '').strip() if m else ''


def _header_map(row, wanted):
    """Map {field name -> column index} for one header row, or None if it is not one.

    A row qualifies only when it carries the product-code column and at least half the
    labels we are looking for — otherwise an address block that happens to hold the word
    'Pack' could be mistaken for the line-item header.
    """
    cells = [_norm(c).lower() for c in row]
    found = {}
    for idx, label in enumerate(cells):
        if not label:
            continue
        if label in wanted:
            found.setdefault(wanted[label], idx)
        elif label.startswith(_GST_LABEL_PREFIX):
            found.setdefault('gst_pct', idx)
    if 'code' not in found or len(found) < max(3, len(wanted) // 2):
        return None
    return found


def _cells(row, colmap):
    return {field: (row[i] if i < len(row) else None) for field, i in colmap.items()}


# ── Per-page extraction ──────────────────────────────────────────────────────
def _page_header(text):
    """Identity and reference fields, read from the page's text layer.

    Read from text rather than from table cells because Cadila's header block merges
    several labels into one cell ('Invoice No. : X\\nInvoice Dt. : Y'), and the merging
    differs between the invoice and the note.
    """
    is_note = bool(re.search(r'CREDIT NOTE', text, re.I))
    number = (_find(text, r'Credit Note No\.?\s*:\s*(\S+)') if is_note
              else _find(text, r'Invoice No\.?\s*:\s*(\S+)'))
    raw_date = (_find(text, r'Credit Note Dt\.?\s*:\s*(\S+)') if is_note
                else _find(text, r'Invoice Dt\.?\s*:\s*(\S+)'))

    # Both parties print a GSTIN. Cadila's is the one next to its own PAN block at the
    # top; the buyer's follows the 'Sold To' block. Taking them positionally is fragile,
    # so they are distinguished by which PAN they sit with.
    gstins = re.findall(r'GSTIN[/A-Za-z.]*\s*:?\s*([0-9]{2}[A-Z0-9]{13})', text)
    seller_gstin = next((g for g in gstins if 'AAACC6251E' in g), gstins[0] if gstins else '')
    buyer_gstin = next((g for g in gstins if g != seller_gstin), '')

    return {
        'doc_type': DOC_CREDIT_NOTE if is_note else DOC_INVOICE,
        'doc_number': number,
        'doc_date': _doc_date(raw_date),
        'irn': _find(text, r'IRN\s*NO\s*:?-?\s*([0-9a-f]{40,72})'),
        'order_number': _find(text, r'Order No\.?\s*:\s*(\d+)'),
        'delivery_number': _find(text, r'Delivery No\.?\s*:?\s*(\d+)'),
        'claim_reference': _find(text, r'Cust\.?\s*Claim Ref\s*:?\s*(\d+)'),
        'customer_code': _find(text, r'Sold To\s*:?\s*(\d+)'),
        'seller_gstin': seller_gstin,
        'buyer_gstin': buyer_gstin,
        'seller_name': 'CADILA PHARMACEUTICALS LIMITED',
        'place_of_supply': _find(text, r'Place of Supply\(Billed to State\)\s*:?\s*([A-Z ]+)'),
    }


def _invoice_line(cells, line_no, warnings):
    code = _norm(cells.get('code'))
    billed = _num(cells.get('billed_qty'))
    free = _num(cells.get('free_qty')) or 0.0
    stp = _num(cells.get('stp_qty'))

    # Two quantity columns. Qty (STP) is the sellable unit — strips, and it is what the
    # catalogue counts; Billed Qty is the trade pack (boxes). Bottles, vials and kits
    # leave STP blank and bill in the unit directly, so the basis is whichever is given.
    basis = stp if stp else billed
    if not basis:
        warnings.append(f'line {line_no} ({code}): no quantity, line skipped')
        return None

    quantity = basis
    if free:
        # Free goods are billed in the trade pack. Convert them onto the same basis using
        # this line's own pack ratio rather than parsing the pack text, which is free-form
        # ('30X10 C', '1NO OF75GM', '5 ML BOT') and not reliably a multiplier.
        per_pack = (stp / billed) if (stp and billed) else 1.0
        quantity = basis + free * per_pack
        warnings.append(
            f'line {line_no} ({code}): {free:g} free unit(s) added as {free * per_pack:g}'
            f' at {per_pack:g}/pack — verify against the physical receipt')

    txn = _num(cells.get('txn_value'))
    pts = _num(cells.get('pts'))
    ptr = _num(cells.get('ptr'))
    ptr_value = _num(cells.get('ptr_value'))
    scheme = _num(cells.get('scheme_value')) or 0.0

    # Landed cost per unit, net of scheme. Derived from the value column rather than read
    # from PTS: the printed PTS is rounded to 3dp, and over 100k units that rounding is
    # real money. PTS then acts as the check that the division found the right columns.
    rate = (txn / basis) if (txn and basis) else pts
    if rate is None:
        warnings.append(f'line {line_no} ({code}): no rate on the line')

    # The document proves its own arithmetic three ways; each failure means a column was
    # read wrongly, which is the failure that would otherwise post wrong stock silently.
    if ptr and ptr_value and abs(ptr * basis - ptr_value) > 1.0:
        warnings.append(f'line {line_no} ({code}): PTR x qty does not equal PTR value')
    if ptr_value and txn and abs((ptr_value - scheme) - txn) > 1.0:
        warnings.append(f'line {line_no} ({code}): PTR value less scheme does not equal '
                        'transaction value')
    if rate is not None and pts and abs(rate - pts) > 0.01:
        warnings.append(f'line {line_no} ({code}): derived rate {rate:.4f} disagrees with '
                        f'printed PTS {pts:.3f}')

    expiry_raw = _norm(cells.get('expiry'))
    expiry = _month_end(expiry_raw)
    if expiry_raw and not expiry:
        warnings.append(f'line {line_no} ({code}): expiry {expiry_raw!r} not understood')

    return {
        'line_no': line_no,
        'product_code': code,
        'hsn': _norm(cells.get('hsn')),
        'raw_product_name': _norm(cells.get('description')),
        'raw_pack': _norm(cells.get('pack')),
        'raw_batch': _norm(cells.get('batch')),
        'raw_expiry': expiry_raw,
        'expiry_date': expiry,
        'quantity': quantity,
        'billed_qty': billed,
        'free_qty': free,
        # True when the quantity counts strips (Qty (STP) was given) rather than the unit
        # the UOM column names. The catalogue's unit follows this, not the printed code.
        'stp_basis': bool(stp),
        'uom': _norm(cells.get('uom')),
        'mrp': _num(cells.get('mrp')),
        'rate': rate,
        'ptr': ptr,
        'scheme_value': scheme,
        'txn_value': txn,
        'gst_rate': _num(cells.get('gst_pct')),
        'manufacturer': _norm(cells.get('manufacturer')),
    }


def _note_line(cells, line_no, warnings):
    code = _norm(cells.get('code'))
    qty = _num(cells.get('qty'))
    total = _num(cells.get('diff_total'))
    printed = _num(cells.get('diff_unit'))

    # The per-unit reduction, recomputed from the total. The printed P.Diff/Unit is only
    # 2dp: on 30,000 strips the printed 0.37 and the true 0.368285 differ by ~35 rupees
    # of landed cost, which then flows into every margin the batch appears in.
    rate = (total / qty) if (total and qty) else printed
    if rate is None:
        warnings.append(f'line {line_no} ({code}): no price difference on the line')
    elif printed and abs(rate - printed) > 0.02:
        warnings.append(f'line {line_no} ({code}): derived {rate:.4f} differs from printed '
                        f'{printed:.2f} by more than rounding')

    expiry_raw = _norm(cells.get('expiry'))
    return {
        'line_no': line_no,
        'product_code': code,
        'hsn': _norm(cells.get('hsn')),
        'raw_product_name': _norm(cells.get('description')),
        'raw_pack': _norm(cells.get('pack')),
        'raw_batch': _norm(cells.get('batch')),
        'raw_expiry': expiry_raw,
        'expiry_date': _month_end(expiry_raw),
        # Carried for reference only. A price-difference note moves no stock, so this
        # quantity must never reach fc_entity_stock.
        'quantity': qty,
        'uom': _norm(cells.get('uom')),
        'mrp': None,
        'rate': rate,
        'gross_value': _num(cells.get('pts_value')),
        'diff_total': total,
        'ref_group_invoice': _norm(cells.get('ref_group_invoice')),
        'ref_child_invoice': _norm(cells.get('ref_child_invoice')),
    }


def _page_totals(text, is_note):
    """Document totals, and the GST rate implied by them.

    Tax is derived as (taxed total - assessable value) rather than read from the CGST /
    SGST / IGST lines. Those labels and their amounts interleave unpredictably in the text
    layer — on one invoice 'CGST\\n6,787.20 5 339.36' puts the assessable value where the
    tax amount reads — whereas the two totals are unambiguously labelled.

    The rate is always derived, never read. A credit note prints '0.5' where the tax is 5%
    and '0.25' where it is 2.5%, so trusting the printed figure would understate every
    landed-cost adjustment by a factor of ten.
    """
    if is_note:
        net = _num(_find(text, r'Net Credit\s*Note Value[\s:]*([\d,\.]+)'))
        taxed = _num(_find(text, r'(?:^|\n)\s*Total\s+([\d,\.]+)'))
        payable = taxed
    else:
        net = _num(_find(text, r'Total Transaction Value\s+([\d,\.]+)'))
        # Invoice amount, NOT payable: payable is struck after TDS and rounding, which are
        # settlement adjustments and not part of the cost of the goods.
        taxed = _num(_find(text, r'TOTAL INVOICE AMT\s*Rs\.?\s*([\d,\.]+)'))
        payable = _num(_find(text, r'TOTAL INV PAYABLE AMT\s*([\d,\.]+)'))

    tax = round(taxed - net, 2) if (taxed is not None and net is not None) else None
    gst_rate = round(tax / net * 100, 2) if (tax and net) else None
    return {'net_value': net, 'tax_amount': tax, 'taxed_total': taxed,
            'grand_total': payable, 'gst_rate_derived': gst_rate}


# ── Entry point ──────────────────────────────────────────────────────────────
def parse_documents(stream, filename=''):
    """Parse one PDF into a LIST of documents.

    A list, not a single document, because Cadila batches credit notes: one file routinely
    holds ten unrelated notes, each with its own number and IRN. Returning only the first
    would silently discard nine real cost adjustments. Pages are grouped by document
    number, which equally keeps a multi-page invoice together as one document.
    """
    payload = stream.read() if hasattr(stream, 'read') else open(stream, 'rb').read()
    sha256 = hashlib.sha256(payload).hexdigest()

    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        if not pdf.pages:
            raise ParseError('PDF has no pages')
        pages = [(pg.extract_text() or '', pg.extract_tables() or []) for pg in pdf.pages]

    docs, order = {}, []
    for page_no, (text, tables) in enumerate(pages, start=1):
        if not re.search(r'CADILA PHARMACEUTICALS', text, re.I):
            raise ParseError(
                f'page {page_no} is not a Cadila document — this uploader reads Cadila '
                'tax invoices and credit notes')

        head = _page_header(text)
        if not head['doc_number']:
            raise ParseError(f'page {page_no}: document number not found')

        is_note = head['doc_type'] == DOC_CREDIT_NOTE
        wanted = _NOTE_COLUMNS if is_note else _INVOICE_COLUMNS

        key = head['doc_number']
        if key not in docs:
            docs[key] = dict(head, lines=[], warnings=[], pages=[], net_value=None,
                             tax_amount=None, taxed_total=None, grand_total=None,
                             gst_rate_derived=None)
            order.append(key)
        doc = docs[key]
        doc['pages'].append(page_no)

        # A two-page invoice carries its line items on page 1 and its totals on page 2, so
        # totals are merged from whichever page actually prints them rather than taken
        # from the first page and left null.
        for field, value in _page_totals(text, is_note).items():
            if value is not None:
                doc[field] = value

        colmap = None
        for table in tables:
            for row in table:
                found = _header_map(row, wanted)
                if found:
                    colmap = found
                    continue
                if colmap is None:
                    continue
                cells = _cells(row, colmap)
                if not PRODUCT_CODE.match(_norm(cells.get('code'))):
                    continue
                line = (_note_line if is_note else _invoice_line)(
                    cells, len(doc['lines']) + 1, doc['warnings'])
                if line:
                    doc['lines'].append(line)

    for key in order:
        doc = docs[key]
        doc['source_filename'] = filename
        doc['source_sha256'] = sha256
        if not doc['lines']:
            doc['warnings'].append('no line items found on this document')
        # GST per line is only printed on the invoice; the note's must come from its
        # totals. Fall back to the derived rate wherever the line did not carry one.
        for line in doc['lines']:
            if not line.get('gst_rate'):
                line['gst_rate'] = doc.get('gst_rate_derived')
        _reconcile(doc)

    return [docs[k] for k in order]


def _reconcile(doc):
    """Check the sum of the lines against the total the document prints for itself.

    Reported, never enforced. A supplier's own total can be the thing that is wrong — an
    earlier receipt reconciled to the paise against its line values while disagreeing with
    the printed grand total — so this records the variance and leaves the judgement open.
    """
    if doc['doc_type'] == DOC_CREDIT_NOTE:
        computed = sum(l['diff_total'] or 0 for l in doc['lines'])
    else:
        computed = sum(l['txn_value'] or 0 for l in doc['lines'])
    doc['computed_value'] = round(computed, 2)
    net = doc.get('net_value')
    doc['value_variance'] = round(computed - net, 2) if net is not None else None
    if doc['value_variance'] and abs(doc['value_variance']) > 1.0:
        doc['warnings'].append(
            f"line values total {computed:,.2f} but the document states "
            f"{net:,.2f} (variance {doc['value_variance']:+,.2f})")
