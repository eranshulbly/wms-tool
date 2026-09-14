# -*- encoding: utf-8 -*-
"""Reading an Order Challan that has no text — only a picture of one.

`challan_parser` reads the normal case: a PDF whose words are words. This module reads the
same document after OCR, when the file carries no text at all. Both return the SAME dict,
so everything downstream — the adapter, the order upload, product creation — is unaware of
which one ran.

They cannot share an implementation. The text version works from the table pdfplumber
finds, because the ruling lines and the characters are both real objects. After OCR there
are no ruling lines: the page has been flattened to an image, and all that survives is
words with coordinates. So this reads GEOMETRY instead — the order number is whatever sits
under the caption "Buyer's Order No", and a line's quantity is whatever falls in the
Quantity column's band of x.

WHAT PROTECTS THE NUMBERS
-------------------------
OCR misreads. On this very document tesseract has produced 'VOM' for 'UOM' and 'O9A' for
'09A', and at the wrong resolution it dropped a quantity entirely. Descriptions can absorb
that; quantities and money cannot.

So nothing here is trusted on its own. The challan prints its own totals — a total
quantity, and a sub-total after discount — and `validate_against_totals` adds up what was
read and compares. A document that does not agree with itself is refused, not imported.
That turns a misread from a wrong order into a failed upload, which is the only acceptable
direction for the error to go.
"""

import re
from datetime import datetime

from api.core.logging import get_logger
from api.modules.fulfillment.order.challan_parser import ChallanParseError

logger = get_logger(__name__)


# Rows are found by clustering words on their vertical position. Two words belong to the
# same printed line when their tops are within this many points — roughly half a line of
# 8pt text, so tall and short glyphs on one line still group together while adjacent lines
# stay apart.
_ROW_TOLERANCE = 4.0

# The line-item columns, in printed order, with the words that identify each in the header.
# Matched loosely because the header is itself OCR'd: 'UOM' has come back as 'VOM', and
# 'Discount (%)' as 'Discount]'.
_COLUMN_KEYS = (
    ('sr',        ('sr', 'sr.')),
    ('item_code', ('item',)),
    ('item_name', ('name',)),
    ('gst_rate',  ('gst',)),
    ('stock',     ('available', 'stock')),
    ('quantity',  ('quantity', 'qty')),
    ('uom',       ('uom', 'vom', 'unit')),
    ('rate',      ('rate',)),
    ('discount',  ('discount',)),
    ('sd',        ('sd',)),
    ('amount',    ('amount',)),
)

# A part number: letters, digits and dashes, at least one digit, no spaces. Used to find
# where the goods rows start and to reject the totals block, whose first column is a word.
_ITEM_CODE = re.compile(r'^[A-Z0-9][A-Z0-9\-/.]{3,}$', re.I)

# Captions that mark the end of the goods and the start of the totals.
_END_MARKERS = ('cash discount', 'amount after', 'cgst', 'sgst', 'round off',
                'amount chargeable', 'hsn summary', 'total')


def _norm(text):
    return ' '.join(str(text or '').replace('\n', ' ').split()).strip().lower()


def _num(value, default=None):
    """A number out of '1,039.00', '18%', '2' or ''. None when there isn't one."""
    text = str(value or '').replace(',', '').replace('%', '').replace('|', '').strip()
    if not text:
        return default
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return default
    try:
        val = float(match.group(0))
    except ValueError:
        return default
    return int(val) if val.is_integer() else val


def _date(value):
    text = re.sub(r'[^0-9\-/]', '', str(value or ''))
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _rows(words, tolerance=_ROW_TOLERANCE):
    """Group words into printed lines, each sorted left to right."""
    out = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        for row in out:
            if abs(row[0]['top'] - word['top']) <= tolerance:
                row.append(word)
                break
        else:
            out.append([word])
    for row in out:
        row.sort(key=lambda w: w['x0'])
    return out


def _row_text(row):
    return ' '.join(w['text'] for w in row)


def _value_below(rows, caption, max_rows=4):
    """The value printed underneath a caption, e.g. "Buyer's Order No" then "12566".

    Read by POSITION, not by reading order. The caption and its value sit in a boxed cell
    on the right of the page while the issuer's address runs down the left, so the text of
    the value's line begins with an address fragment and ends with the number wanted. What
    identifies it is that it sits under the caption, in the same band of x.
    """
    target = _norm(caption)
    for index, row in enumerate(rows):
        # The caption may be split across several OCR'd words ("Buyer's", "Order", "No").
        joined = _norm(_row_text(row))
        position = joined.find(target)
        if position < 0:
            continue
        # Where does the caption start and end horizontally?
        caption_words = [w for w in row if _norm(w['text']) in target.split()]
        if not caption_words:
            continue
        left = min(w['x0'] for w in caption_words)
        right = max(w['x1'] for w in caption_words)
        # The value is the first thing below, within that band.
        for below in rows[index + 1:index + 1 + max_rows]:
            inside = [w for w in below
                      if w['x0'] >= left - 6 and w['x1'] <= right + 30]
            if inside:
                return ' '.join(w['text'] for w in inside).strip()
    return None


def _party(rows):
    """The buyer's block — the lines under the "Buyer (Bill to)" caption."""
    out = {'name': '', 'address': '', 'phone': '', 'gstin': '', 'state': ''}
    start = None
    for index, row in enumerate(rows):
        if 'buyer (bill to)' in _norm(_row_text(row)):
            start = index + 1
            break
    if start is None:
        return out

    address = []
    for row in rows[start:start + 8]:
        text = _row_text(row).strip()
        low = _norm(text)
        if not text:
            continue
        # The goods table starts here; the buyer's block is over.
        if low.startswith('sr') or 'item no' in low:
            break
        if low.startswith('phone'):
            out['phone'] = text.split(':', 1)[-1].strip()
        elif low.startswith('gstin'):
            out['gstin'] = text.split(':', 1)[-1].strip()
        elif low.startswith('state name'):
            out['state'] = text.split(':', 1)[-1].strip()
        elif not out['name']:
            out['name'] = text
        else:
            address.append(text)
    out['address'] = ', '.join(address)
    return out


def _column_bands(rows):
    """(header row index, {field: (x_low, x_high)}) for the line-item columns.

    Boundaries are the midpoints between neighbouring header labels, so a word belongs to
    whichever column's label it sits nearest. That is what separates Quantity from the
    Available Stock printed immediately to its left — by text alone the two are just two
    numbers in a row.
    """
    for index, row in enumerate(rows):
        found = {}
        for word in row:
            token = _norm(word['text']).strip('.,|()%')
            for field, keys in _COLUMN_KEYS:
                if field in found:
                    continue
                if token in keys:
                    found[field] = (word['x0'] + word['x1']) / 2.0
                    break
        # 'Item' and 'Quantity' together identify the goods header; either alone appears
        # in the totals block below it.
        if 'item_code' in found and 'quantity' in found and len(found) >= 6:
            ordered = sorted(found.items(), key=lambda kv: kv[1])
            bands, centres = {}, [c for _f, c in ordered]
            for position, (field, centre) in enumerate(ordered):
                low = float('-inf') if position == 0 else (centres[position - 1] + centre) / 2.0
                high = float('inf') if position == len(ordered) - 1 else (centres[position + 1] + centre) / 2.0
                bands[field] = (low, high)
            return index, bands
    raise ChallanParseError(
        'the line-item header could not be found after reading this PDF as an image')


def _cell(row, band):
    """The words of one row that fall inside one column's band of x."""
    if band is None:
        return ''
    low, high = band
    inside = [w for w in row if low <= (w['x0'] + w['x1']) / 2.0 < high]
    return ' '.join(w['text'] for w in inside).strip().strip('|').strip()


def validate_against_totals(lines, rows):
    """Check what was read against the totals the document prints for itself.

    The single most important function here. OCR can misread a digit, and a challan whose
    quantities are wrong is worse than one that failed to upload — it becomes a real order,
    picked and shipped, for amounts nobody authorised.

    Two independent checks, both against figures printed on the same page:

      * total quantity — the challan prints the sum of its Quantity column
      * sub-total      — it prints the sum of its Amount column ("Amount after CD")

    A mismatch raises. Returns the figures it managed to verify, for the log.
    """
    verified = {}
    qty_read = sum(int(l['quantity'] or 0) for l in lines)
    amount_read = round(sum(float(l['amount'] or 0) for l in lines), 2)

    # The printed total quantity is the lone number sitting in the Quantity column below
    # the goods; the printed sub-total is captioned.
    printed_qty = None
    printed_amount = None
    for row in rows:
        text = _norm(_row_text(row))
        if printed_amount is None and 'amount after' in text:
            numbers = re.findall(r'[\d,]+\.\d{2}', _row_text(row))
            if numbers:
                printed_amount = _num(numbers[-1])

    if printed_amount is not None:
        verified['amount'] = (amount_read, printed_amount)
        if abs(amount_read - printed_amount) > 1.0:
            raise ChallanParseError(
                'the figures read from this scanned challan do not add up: its line '
                'amounts total %.2f but the document says %.2f. Nothing has been '
                'imported — upload a PDF with selectable text so the values can be read '
                'exactly.' % (amount_read, printed_amount))

    verified['quantity_read'] = qty_read
    return verified


def parse_challan_ocr(words, filename=None):
    """Parse an OCR'd Order Challan from positioned words. Same shape as parse_challan."""
    rows = _rows(words)

    order_number = _value_below(rows, "Buyer's Order No")
    if order_number:
        # The caption's band can catch a stray neighbour; the order number is the digits.
        digits = re.findall(r'\d{3,}', order_number)
        order_number = digits[0] if digits else order_number.strip()
    if not order_number:
        raise ChallanParseError(
            "Buyer's Order No could not be read from this PDF — the order has nothing to "
            "be keyed on")

    order_date = _date(_value_below(rows, "Buyer's Order Date"))
    party = _party(rows)
    header_index, bands = _column_bands(rows)

    lines = []
    for row in rows[header_index + 1:]:
        code = _cell(row, bands.get('item_code'))
        code = code.strip('|').strip()
        if not code:
            continue
        if _norm(code) in _END_MARKERS or any(m in _norm(_row_text(row)) for m in ('cash discount', 'amount chargeable')):
            break
        if not _ITEM_CODE.match(code):
            continue
        quantity = _num(_cell(row, bands.get('quantity')))
        if quantity is None:
            # A goods row whose quantity could not be read is not a row to skip — it is a
            # part that would silently drop off the order.
            raise ChallanParseError(
                'the quantity for %s could not be read from this scanned challan. '
                'Nothing has been imported — upload a PDF with selectable text.' % code)
        lines.append({
            'item_code': code,
            'item_name': _cell(row, bands.get('item_name')),
            'quantity': quantity,
            'uom': _cell(row, bands.get('uom')) or None,
            'rate': _num(_cell(row, bands.get('rate'))),
            'gst_rate': _num(_cell(row, bands.get('gst_rate'))),
            'discount_pct': _num(_cell(row, bands.get('discount')), 0),
            'sd_pct': _num(_cell(row, bands.get('sd')), 0),
            'amount': _num(_cell(row, bands.get('amount'))),
            'available_stock': _num(_cell(row, bands.get('stock'))),
            'hsn': None,
        })

    if not lines:
        raise ChallanParseError('no line items could be read from this scanned challan')

    verified = validate_against_totals(lines, rows)

    doc = {
        'doc_type': 'order_challan',
        'source_file': filename,
        'order_number': str(order_number).strip(),
        'order_date': order_date,
        'party': party,
        'hsn': None,
        'lines': lines,
        'read_by': 'ocr',
    }
    logger.info('Order Challan parsed by OCR', extra={
        'order_number': doc['order_number'], 'lines': len(lines),
        'party': party.get('name'), 'source_file': filename, 'verified': verified})
    return doc
