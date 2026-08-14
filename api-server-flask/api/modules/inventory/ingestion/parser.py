# -*- encoding: utf-8 -*-
"""PDF parser for the supplier's document template (Anmol Associates layout).

Reads a goods receipt note or credit/debit note into a plain dict. Extraction only —
nothing here touches the database, resolves a SKU or decides what stock moves. That
separation is what makes the parser testable against a corpus of real PDFs.

Three properties of the template drive the implementation:

1. **A light-grey diagonal watermark overlaps the table.** Its characters are upright and
   land INSIDE table cells, so text extraction interleaves them with real values —
   'ACENEXT P TAB' comes back as 'ACENEXT P TAB\\ns\\nA\\nl\\no\\nm\\nn\\nA'. Left in, they
   add phantom segments and shift every subsequent value onto the wrong product. They are
   removed by appearance, not position: the watermark is ~24-33pt light grey, real content
   is <=14pt and black or dark blue.

2. **Every line item lives in ONE table row**, newline-separated per cell. A 15-line
   invoice is a single row whose Qty cell holds 15 segments. Lines are recovered by
   splitting each cell and zipping across columns — which is only safe because the
   watermark is gone first, and is checked by _split_lines refusing ragged segment counts.

3. **Column positions are fixed; the header labels are not.** The supplier prints two tax
   layouts (22 of 25 sample documents IGST, 3 SGST+CGST) and the header text spills across
   cells — 'Amount Net Amount' arrives as 'Am' / 'ount Net' / 'Amount'. The VALUES stay put
   in both layouts, so columns are read by index and the header is used only to validate
   the template and to name the tax at COL_TAX1. A header that does not match aborts the
   parse: silently misreading a money column is worse than refusing the file.
"""

import hashlib
import re
from calendar import monthrange
from datetime import date, datetime

import pdfplumber

# ── Fixed column indices in the extracted line-item table ────────────────────
COL_SNO, COL_QTY, COL_MFR, COL_PACK, COL_NAME = 0, 1, 3, 4, 5
COL_BATCH, COL_EXP, COL_HSN, COL_MRP, COL_RATE = 8, 11, 12, 13, 15
COL_DIS, COL_TAX1, COL_TAX2, COL_AMOUNT, COL_NET = 17, 18, 20, 21, 22

# (index, expected label) pairs asserted before any value is read.
_HEADER_GUARD = [
    (COL_SNO, 'S.'), (COL_QTY, 'Qty.'), (COL_MFR, 'Mfr'), (COL_PACK, 'Pack'),
    (COL_NAME, 'Product Name'), (COL_BATCH, 'Batch'), (COL_EXP, 'Exp'),
    (COL_HSN, 'HSN'), (COL_MRP, 'M.R.P'), (COL_RATE, 'Rate'), (COL_DIS, 'DIS'),
]

DOC_TITLES = {
    'GOODS RECEIPT NOTE': 'GRN',
    'DEBIT NOTE': 'DN',
    'CREDIT NOTE': 'CN',
    'GST INVOICE': 'INVOICE',      # outbound: a sale to a customer
    'TAX INVOICE': 'INVOICE',
}

# Which document kinds move goods, and in which direction.
INBOUND_TYPES = ('GRN',)
OUTBOUND_TYPES = ('INVOICE',)


class ParseError(ValueError):
    """The file is not the expected template, or the template changed."""


# ── Watermark removal ────────────────────────────────────────────────────────
def _is_watermark(obj):
    """True for the decorative overlay, identified by appearance rather than position.

    The overlay is large light-grey text; real content is small and black/dark-blue. Both
    tests are required — a heading can be large, and a rule can be grey.
    """
    if obj.get('object_type') != 'char':
        return False
    colour = obj.get('non_stroking_color') or ()
    if not isinstance(colour, (list, tuple)) or len(colour) < 3:
        return False
    light = all(isinstance(c, (int, float)) and c >= 0.8 for c in colour[:3])
    return light and (obj.get('size') or 0) > 18


# ── Small value helpers ──────────────────────────────────────────────────────
def _cell(row, idx):
    if idx >= len(row):
        return ''
    return (row[idx] or '').strip()


def _segments(text):
    return [s.strip() for s in (text or '').split('\n') if s.strip()]


def _num(text, default=0.0):
    """Parse a printed number. Returns `default` for blanks and unparseable text."""
    if text is None:
        return default
    cleaned = re.sub(r'[^\d.\-]', '', str(text))
    if cleaned in ('', '-', '.', '-.'):
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_expiry(raw):
    """'3/28' -> date(2028, 3, 31): the LAST day of the printed month.

    Pharma prints expiry to month precision, and the stock is good for the whole month.
    Month-end makes "has this expired?" a plain date comparison and FEFO a plain ORDER BY,
    instead of an off-by-one-month question at every call site.
    """
    if not raw:
        return None
    m = re.match(r'^\s*(\d{1,2})\s*/\s*(\d{2,4})\s*$', str(raw))
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    if year < 100:
        year += 2000
    return date(year, month, monthrange(year, month)[1])


def _parse_date(raw):
    """Printed as DD-MM-YYYY."""
    if not raw:
        return None
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y'):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


# ── Header / footer field extraction ─────────────────────────────────────────
# Other field names printed in the same header band. A blank field lets the scan run on
# into its neighbour, so "Order No." with nothing after it would otherwise return the
# adjacent "Cases 0" — a value belonging to a different field entirely.
_SIBLING_LABELS = ('Cases', 'Transport', 'L.R. No.', 'L.R. Date', 'Order No.',
                   'Order Date', 'Invoice No', 'Invoice Date', 'Due Date', 'Party Name')


def _labelled_value(table, label):
    """Value printed beside `label` — the next non-empty cell on the same row.

    Located by content rather than coordinates so it survives the cell-merge differences
    between documents. Returns '' when the field is blank rather than bleeding into the
    next field along.
    """
    for row in table:
        for i, raw in enumerate(row):
            if (raw or '').strip().split('\n')[0].strip() == label:
                for j in range(i + 1, len(row)):
                    val = _cell(row, j)
                    if not val:
                        continue
                    head = val.split('\n')[0].strip()
                    if any(head.startswith(sib) for sib in _SIBLING_LABELS):
                        return ''      # field is empty; this belongs to another field
                    return val
    return ''


def _find_doc_type(text):
    for title, code in DOC_TITLES.items():
        if title in text:
            return code, title
    return '', ''


def _find_cell(table, needle):
    """The full text of the first cell containing `needle`."""
    for row in table:
        for raw in row:
            if raw and needle in raw:
                return raw
    return ''


def _money_in(blob, label):
    """Number printed beside `label` inside a totals cell.

    The totals sit in one cell as stacked 'LABEL value' lines
    ('DIS AMT. 0.00\\nSGST 972.24\\nCGST 0.00\\nCR/DR NOTE 0.00'), so they are read from
    that cell rather than by scanning the flattened page. Scanning would also match the
    identically named RATE column in the line-item header — on an SGST document 'SGST'
    appears both as a 2.50 rate and an 11,354.00 amount, and picking the wrong one is
    silent.
    """
    segs = _segments(blob)
    for i, line in enumerate(segs):
        if not line.upper().startswith(label.upper()):
            continue
        tail = line[len(label):]
        if re.search(r'\d', tail):
            return _num(tail)
        # 'Grand Total' is printed above its figure rather than beside it, so the value
        # is the next segment in the same cell.
        if i + 1 < len(segs) and re.search(r'\d', segs[i + 1]):
            return _num(segs[i + 1])
    return 0.0


# ── Line items ───────────────────────────────────────────────────────────────
def _header_row_index(table):
    for i, row in enumerate(table):
        cells = [(c or '').strip() for c in row]
        if 'S.' in cells and 'Qty.' in cells:
            return i
    return None


def _validate_header(header):
    """Refuse the file unless every guarded column sits where it is expected.

    The parser reads money by index, so a shifted template must fail loudly. A wrong
    number that looks plausible is far more expensive than a rejected upload.
    """
    for idx, expected in _HEADER_GUARD:
        actual = _cell(header, idx).split('\n')[0].strip()
        if actual != expected:
            raise ParseError(
                f"unexpected document layout: column {idx} is {actual!r}, expected "
                f"{expected!r}. The supplier's template may have changed — the parser "
                f"must be re-checked against it before these values can be trusted."
            )
    tax = _cell(header, COL_TAX1).split('\n')[0].strip()
    if tax not in ('IGST', 'SGST', 'CGST'):
        raise ParseError(f"unexpected tax column header {tax!r} at column {COL_TAX1}")
    return tax


def _split_lines(item_row, tax_label):
    """Recover the individual line items from the single packed table row."""
    columns = {
        'sno': COL_SNO, 'qty': COL_QTY, 'mfr': COL_MFR, 'pack': COL_PACK,
        'name': COL_NAME, 'batch': COL_BATCH, 'exp': COL_EXP, 'hsn': COL_HSN,
        'mrp': COL_MRP, 'rate': COL_RATE, 'dis': COL_DIS, 'tax1': COL_TAX1,
        'tax2': COL_TAX2, 'amount': COL_AMOUNT, 'net': COL_NET,
    }
    parts = {key: _segments(_cell(item_row, idx)) for key, idx in columns.items()}

    count = len(parts['sno'])
    if count == 0:
        return []

    # On the LAST page the totals row shares cells with the final item row, so a column
    # arrives with the total prepended: CGST as ['TOTAL', '2.50'], Net as
    # ['97685.29', '9924.60']. The item's own value is the trailing one.
    #
    # Only LEADING extras are dropped. Watermark contamination appends single characters
    # instead, so trimming from the front cannot mistake one for the other — and a column
    # with FEWER segments than expected is still refused below.
    for key, seq in parts.items():
        if len(seq) > count:
            trimmed = [x for x in seq if x.strip().upper() != 'TOTAL']
            parts[key] = trimmed[-count:] if len(trimmed) >= count else trimmed

    # Ragged columns mean segments no longer correspond one-to-one, so zipping would
    # attach one product's quantity to another's batch. Every observed case was watermark
    # contamination; either way the file must not be read on a guess.
    ragged = {k: len(v) for k, v in parts.items() if v and len(v) != count}
    if ragged:
        raise ParseError(
            f"line items do not align: expected {count} segments per column, got {ragged}. "
            f"Refusing to parse rather than risk attributing values to the wrong product."
        )

    def at(key, i):
        seq = parts[key]
        return seq[i] if i < len(seq) else ''

    lines = []
    for i in range(count):
        quantity = _num(at('qty', i))
        amount = _num(at('amount', i))
        # The printed rate is rounded to 2dp and does not reproduce the amount
        # (3000 x 6.48 = 19,440.00 against a printed 19,444.80). The amount is the
        # authoritative figure, so the true rate is derived from it; the printed one is
        # kept only to show what the paper said.
        rate = round(amount / quantity, 4) if quantity else 0.0
        tax = _num(at('tax1', i))
        lines.append({
            'line_no': i + 1,
            'raw_product_name': at('name', i),
            'raw_pack': at('pack', i),
            'raw_mfr': at('mfr', i),
            'raw_batch': at('batch', i),
            'raw_expiry': at('exp', i),
            'raw_hsn': at('hsn', i),
            'expiry_date': parse_expiry(at('exp', i)),
            'quantity': quantity,
            'amount': amount,
            'rate': rate,
            'printed_rate': _num(at('rate', i)),
            'net_amount': _num(at('net', i)),
            'mrp': _num(at('mrp', i)),
            'discount_pct': _num(at('dis', i)),
            'igst_rate': tax if tax_label == 'IGST' else 0.0,
            'sgst_rate': tax if tax_label == 'SGST' else _num(at('tax2', i)) if tax_label == 'CGST' else 0.0,
            'cgst_rate': _num(at('tax2', i)) if tax_label == 'SGST' else 0.0,
        })
    return lines


# ── Entry point ──────────────────────────────────────────────────────────────
def parse_pdf(stream, filename=''):
    """Parse one supplier PDF into {header fields, lines, warnings}.

    `stream` is a file-like object or path. Raises ParseError when the document is not
    the expected template.
    """
    if hasattr(stream, 'read'):
        payload = stream.read()
    else:
        with open(stream, 'rb') as fh:
            payload = fh.read()
    sha256 = hashlib.sha256(payload).hexdigest()

    import io
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        if not pdf.pages:
            raise ParseError('PDF has no pages')
        # EVERY page, not just the first. A 31-line invoice spills onto a second page, and
        # reading only page one drops the overflow silently — which on an outbound
        # document means stock that never gets deducted.
        pages = [pg.filter(lambda o: not _is_watermark(o)) for pg in pdf.pages]
        tables = [pg.extract_table() or [] for pg in pages]
        texts = [pg.extract_text() or '' for pg in pages]

    table = tables[0]
    text = '\n'.join(texts)
    if not table:
        raise ParseError('no table found — the file may be a scan rather than a text PDF')

    hdr_idx = _header_row_index(table)
    if hdr_idx is None:
        raise ParseError('could not locate the line-item header row')
    tax_label = _validate_header(table[hdr_idx])

    doc_type, title = _find_doc_type(text)
    if not doc_type:
        raise ParseError(
            'document type not found (expected a GRN, GST invoice, credit or debit note)')

    # Line items from every page, renumbered into one continuous sequence: the supplier
    # restarts the printed S.No per page.
    lines = []
    for pg_table in tables:
        h = _header_row_index(pg_table)
        if h is None or h + 1 >= len(pg_table):
            continue
        for ln in _split_lines(pg_table[h + 1], tax_label):
            ln['line_no'] = len(lines) + 1
            lines.append(ln)

    # Dates: the Invoice Date cell carries invoice date and due date stacked.
    date_cell = _segments(_labelled_value(table, 'Invoice Date') or
                          _labelled_value(table, 'Invoice Date\nDue Date'))
    doc_date = _parse_date(date_cell[0]) if date_cell else None
    due_date = _parse_date(date_cell[1]) if len(date_cell) > 1 else None

    gstins = re.findall(r'GSTIN\s*:\s*([0-9A-Z]{15})', text)
    subtotal = sum(l['amount'] for l in lines)

    # Totals sit on the LAST page. Page one of a multi-page invoice carries running
    # subtotals ('SGST PAYBLE') which are not the final figures, so search backwards and
    # take the last match.
    totals = next((c for c in (_find_cell(t, 'DIS AMT.') for t in reversed(tables)) if c), '')
    discount = _money_in(totals, 'DIS AMT.')
    note_amt = _money_in(totals, 'CR/DR NOTE')

    # The totals block ALWAYS books the tax in its "SGST" slot, even when the transaction
    # is inter-state and the line-item column is headed IGST — sample P000005 is billed to
    # a Gujarat registration against a UP supplier, prints an IGST column, and still
    # totals as "SGST 972.24 / CGST 0.00". The column header is the reliable signal for
    # WHICH tax applies, so the printed amount is filed under the layout's tax, not under
    # the slot it was printed in.
    printed_tax = _money_in(totals, 'SGST')
    second_tax = _money_in(totals, 'CGST')
    if tax_label == 'IGST':
        igst, sgst, cgst = printed_tax + second_tax, 0.0, 0.0
    else:
        igst, sgst, cgst = 0.0, printed_tax, second_tax

    grand = _money_in(
        next((c for c in (_find_cell(t, 'Grand Total') for t in reversed(tables)) if c), ''),
        'Grand Total')

    computed = round(subtotal - discount + cgst + sgst + igst, 2)
    variance = round(grand - computed, 2)

    msg = ''
    m = re.search(r'MSG:\s*(.+)', text)
    if m:
        msg = m.group(1).strip()[:255]

    words = ''
    m = re.search(r'(Rs\..+?only)', text, re.I | re.S)
    if m:
        words = re.sub(r'\s+', ' ', m.group(1)).strip()[:255]

    warnings = []
    if abs(variance) >= 1:
        warnings.append(
            f'grand total {grand} does not reconcile with computed {computed} '
            f'(variance {variance})')
    for ln in lines:
        if not ln['raw_batch']:
            warnings.append(f"line {ln['line_no']}: no batch printed")
        if ln['raw_expiry'] and ln['expiry_date'] is None:
            warnings.append(
                f"line {ln['line_no']}: expiry {ln['raw_expiry']!r} not understood")

    return {
        'doc_type': doc_type,
        'doc_title': title,
        'doc_number': _labelled_value(table, 'Invoice No'),
        # Printed but routinely blank on this supplier's outbound invoices; callers
        # substitute a derived number when it is missing.
        'order_number': _labelled_value(table, 'Order No.'),
        'doc_date': doc_date,
        'due_date': due_date,
        'supplier_name': _segments(_cell(table[0], 0))[0] if table and table[0] else '',
        'supplier_gstin': gstins[0] if gstins else '',
        'party_name': next((s for s in _segments(_labelled_value(table, 'Party Name :'))
                            if s), '') or _party_from_text(text),
        'party_gstin': gstins[1] if len(gstins) > 1 else '',
        'lr_number': _labelled_value(table, 'L.R. No.'),
        'transport': _labelled_value(table, 'Transport'),
        'cases': int(_num(re.sub(r'.*Cases', '', _labelled_value(table, 'Cases') or '')) or 0),
        'tax_layout': tax_label,
        'subtotal': round(subtotal, 2),
        'discount_amount': discount,
        'cgst_amount': cgst,
        'sgst_amount': sgst,
        'igst_amount': igst,
        'note_amount': note_amt,
        'grand_total': grand,
        'computed_total': computed,
        'total_variance': variance,
        'amount_in_words': words,
        'message': msg,
        'source_filename': filename,
        'source_sha256': sha256,
        'lines': lines,
        'warnings': warnings,
    }


def _party_from_text(text):
    m = re.search(r'Party Name\s*:?\s*\n?\s*(.+)', text)
    return m.group(1).strip()[:255] if m else ''
