# -*- encoding: utf-8 -*-
"""Read a DMS pick-list PDF into the `meta` structure stored on order_picklist.

This is the lossy step, and it is the only one. The uploaded PDF is discarded after
ingest, so anything not captured here cannot be recovered — which is why every
failure below raises rather than returning a half-filled document. A pick list that
silently loses three of its eight lines is worse than one that refuses to upload.

Two shapes of damage in the PDF text layer that this has to undo:

  * part numbers wrap mid-token across a cell's lines — "ADGAA7Y0010" + "0099GS" is
    one part, "31916KPH90099" + "S" is another. Any whitespace inside a part number
    cell is therefore joined away, not turned into a space.
  * the description repeats the part number after a hyphen ("SOCKET 20-070HH198012S").
    That is what the document says, so it is kept verbatim — the product master gets
    the same string the existing product upload would have given it.
"""

import re
from datetime import datetime

from api.core.logging import get_logger

logger = get_logger(__name__)

META_VERSION = 1


class PicklistExtractError(Exception):
    """The uploaded PDF could not be read as a pick list."""


# ── Header block regexes ─────────────────────────────────────────────────────
# The order block prints as one run: "Code <code> Order No <no> Order Date <dt>".
_RE_CODE = re.compile(r'\bCode\s+(\S+)', re.IGNORECASE)
_RE_ORDER_NO = re.compile(r'\bOrder\s+No\.?\s+(\S+)', re.IGNORECASE)
_RE_ORDER_DATE = re.compile(
    r'\bOrder\s+Date\s+(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)?)')
_RE_NAME = re.compile(r'^\s*Name\s+(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
_RE_CITY = re.compile(r'^\s*City\s+(.+?)\s*$', re.IGNORECASE | re.MULTILINE)
_RE_STATE_CODE = re.compile(r'State\s+Code\s*:\s*(\S+)', re.IGNORECASE)
_RE_CONTACT = re.compile(r'Contact\s*:\s*([0-9+\-\s]+)', re.IGNORECASE)
_RE_GSTIN = re.compile(r'GSTIN\s*No\s*:\s*(\S+)', re.IGNORECASE)
_RE_AUTH = re.compile(r'Authorized\s+Parts\s+Distributor\s*:\s*(.+?)\s*$',
                      re.IGNORECASE | re.MULTILINE)
_RE_PAGE = re.compile(r'^\s*Page\s+\d+\s+of\s+\d+\s*$', re.IGNORECASE)
_RE_LABEL_LINE = re.compile(r'(State\s+Code|GSTIN|Authorized\s+Parts|Contact)\s*:', re.IGNORECASE)
_RE_AMPM = re.compile(r'\b(AM|PM)\b', re.IGNORECASE)

_DATE_FORMATS = ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y')

# Column order of the printed grid. The header itself spans two physical rows
# (Bin Location arches over L1/L2/L3), so rows are identified by shape, not by
# matching header text — see _is_data_row.
COLUMNS = ('sl', 'l1', 'l2', 'l3', 'part', 'desc', 'hsn', 'moq',
           'stock', 'mrp', 'order_qty', 'allocated_qty', 'picked_qty')
N_COLUMNS = len(COLUMNS)


def extract(file_stream, source_filename=None) -> dict:
    """Parse an open PDF file object into the meta dict.

    Raises PicklistExtractError when the document is unreadable, carries no order
    number, or yields no line items.
    """
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - deployment guard
        raise PicklistExtractError(
            "pdfplumber is not installed on this server, so pick-list PDFs cannot be read"
        ) from e

    try:
        file_stream.seek(0)
        pdf = pdfplumber.open(file_stream)
    except Exception as e:
        raise PicklistExtractError("could not open the file as a PDF (%s)" % e)

    with pdf:
        if not pdf.pages:
            raise PicklistExtractError("the PDF has no pages")

        first_text = pdf.pages[0].extract_text() or ''
        header = _parse_distributor(first_text)
        order = _parse_order(first_text)

        lines = []
        for page in pdf.pages:
            lines.extend(_parse_page_lines(page))

    if not order.get('order_no'):
        raise PicklistExtractError(
            "no 'Order No' found on page 1 — this does not look like a pick list")

    # Refuse a truncated order number rather than import under it.
    #
    # One got through as "30305-02-PSAO-0926-" — the printer had wrapped it and
    # the reader stopped at the line break. Nothing downstream could tell that
    # from a real order number, so an order was created under it, matched nothing
    # ever again, and had to be deleted by hand. _joined() now rejoins the usual
    # case; this catches whatever it could not, because a bad import is far more
    # expensive to undo than a refused one.
    if order['order_no'].endswith('-'):
        raise PicklistExtractError(
            "the order number reads '%s', which is cut off — the sheet's layout "
            "split it and it could not be pieced back together"
            % order['order_no'])
    if not lines:
        raise PicklistExtractError(
            "no part lines could be read from the table; the layout may differ from "
            "the pick lists this importer understands")

    # Renumber defensively: a multi-page pick list restarts S.No. per page in some
    # DMS builds, and meta.lines is what the reprint iterates.
    for i, line in enumerate(lines, start=1):
        line['sl'] = line.get('sl') or i

    return {
        'v': META_VERSION,
        'header': header,
        'order': order,
        'lines': lines,
        'footer_fields': ['Picked By', 'Picked Date', 'Total No of Cases',
                          'Checked By', 'Checked Date', 'Packed By', 'Packed Date'],
        'source_filename': source_filename,
        'extracted_at': datetime.utcnow().isoformat() + 'Z',
    }


# ── Header ───────────────────────────────────────────────────────────────────

def _parse_distributor(text: str) -> dict:
    """The centred block above 'Pick List' — who printed the sheet.

    Snapshotted per pick list rather than read from `warehouse` at reprint time for
    two reasons: the warehouse table has no GSTIN, state code or contact column at
    all, and reprinting a March pick list should show March's letterhead.
    """
    lines = [ln.strip() for ln in (text or '').splitlines()]
    lines = [ln for ln in lines if ln and not _RE_PAGE.match(ln)]

    block = []
    for ln in lines:
        if ln.lower().startswith('pick list'):
            break
        block.append(ln)

    name = block[0] if block else ''

    # Address is everything between the name and the first labelled line.
    address_lines = []
    for ln in block[1:]:
        if _RE_LABEL_LINE.search(ln):
            break
        address_lines.append(ln)

    contact = _first(_RE_CONTACT, text)
    return {
        'distributor_name': name,
        'address_lines': address_lines,
        'state_code': _first(_RE_STATE_CODE, text),
        # The line prints as "Contact: 9837038183, ," — trailing empty slots for
        # numbers the DMS has no value for. Strip them rather than store the commas.
        'contact': contact.strip(' ,') if contact else '',
        'gstin': _first(_RE_GSTIN, text),
        'authorized_distributor_of': _first(_RE_AUTH, text),
        'doc_title': 'Pick List',
    }


def _parse_order(text: str) -> dict:
    raw_date = _first(_RE_ORDER_DATE, text)
    return {
        'code': _joined(_RE_CODE, text),
        'order_no': _joined(_RE_ORDER_NO, text),
        'order_date': raw_date,
        'order_date_iso': _parse_date(raw_date),
        'dealer_name': _first(_RE_NAME, text),
        'city': _first(_RE_CITY, text),
    }


# A continuation of a wrapped identifier: digits and capitals only, and not
# followed by a lowercase letter. That last part is what stops it swallowing the
# label that usually comes next — "Order" would otherwise contribute its "O".
_RE_CONTINUATION = re.compile(r'\s*([0-9A-Z][0-9A-Z-]+)(?![a-z])')


def _joined(pattern, text: str) -> str:
    """Read an identifier, rejoining it when the printer wrapped it mid-number.

    `\\S+` stops at the line break, and these identifiers break at a hyphen:
    "Order No 30305-02-PSAO-0926-" on one line and "45532" on the next read as an
    order number ending in a separator. That is not a near-miss — it created a
    whole order under a truncated number that matched nothing and had to be
    deleted by hand.

    A trailing hyphen is the signal, because a complete one never ends in one.
    """
    m = pattern.search(text or '')
    if not m:
        return ''
    value = m.group(1).strip()
    tail = text[m.end():]

    # A loop, not a single step: an identifier long enough to wrap once can wrap
    # twice. Bounded so a malformed document cannot spin here.
    for _ in range(4):
        if not value.endswith('-'):
            break
        nxt = _RE_CONTINUATION.match(tail)
        if not nxt:
            break
        value += nxt.group(1)
        tail = tail[nxt.end():]

    return value


def _first(pattern, text: str) -> str:
    m = pattern.search(text or '')
    return m.group(1).strip() if m else ''


def _parse_date(raw: str):
    if not raw:
        return None
    cleaned = ' '.join(raw.split())
    # 12-hour stamps ("08:59:37 AM") appear in some builds; %p needs the marker present.
    if _RE_AMPM.search(cleaned):
        for fmt in ('%d/%m/%Y %I:%M:%S %p', '%d/%m/%Y %I:%M %p'):
            try:
                return datetime.strptime(cleaned.upper(), fmt).isoformat()
            except ValueError:
                continue
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    logger.warning("Unparseable pick-list date", extra={'raw_value': raw})
    return None


# ── Table ────────────────────────────────────────────────────────────────────

def _parse_page_lines(page) -> list:
    """Pull the part rows off one page.

    The grid is fully ruled, so pdfplumber's line-based table finder is the primary
    strategy; the text strategy is the fallback for a build that drops the rules.
    """
    tables = []
    try:
        tables = page.extract_tables() or []
    except Exception as e:
        logger.warning("extract_tables failed on a pick-list page", extra={'error': str(e)})

    if not tables:
        try:
            found = page.extract_table({'vertical_strategy': 'text',
                                        'horizontal_strategy': 'text'})
            if found:
                tables = [found]
        except Exception:
            pass

    rows = []
    for table in tables:
        for raw_row in table or []:
            cells = _normalise_row(raw_row)
            if cells and _is_data_row(cells):
                rows.append(_row_to_line(cells))
    return rows


def _normalise_row(raw_row) -> list:
    """Trim to the expected width, collapsing whitespace inside each cell."""
    cells = [(c or '').strip() for c in (raw_row or [])]
    if len(cells) < N_COLUMNS:
        return cells + [''] * (N_COLUMNS - len(cells))
    if len(cells) > N_COLUMNS:
        # A stray split inside the widest free-text column is the likeliest cause,
        # so fold the surplus back into the description rather than dropping cells.
        trailing = N_COLUMNS - 6          # columns that follow the description
        head = cells[:5]
        tail = cells[len(cells) - trailing:]
        middle = ' '.join(c for c in cells[5:len(cells) - trailing] if c)
        return head + [middle] + tail
    return cells


def _is_data_row(cells: list) -> bool:
    """A data row starts with a serial number and names a part.

    Matching on shape rather than on "is this the header?" means the two-row header,
    any repeated header on page 2, and the footer sign-off grid are all excluded by
    the same test, without depending on their wording.
    """
    return bool(re.fullmatch(r'\d+', cells[0].strip())) and bool(_join_part(cells[4]))


def _row_to_line(cells: list) -> dict:
    row = dict(zip(COLUMNS, cells))
    part = _join_part(row['part'])
    return {
        'sl': _to_int(row['sl']),
        # Every bin slot is kept, including the empties, so the reprint lays the
        # L1/L2/L3 columns out the way the original did.
        'bin': [_clean(row['l1']), _clean(row['l2']), _clean(row['l3'])],
        'part': part,
        'desc': _repair_desc(_clean(row['desc']), part),
        'hsn': _join_part(row['hsn']),
        'moq': _to_int(row['moq']),
        'stock': _to_int(row['stock']),
        'mrp': _to_decimal_str(row['mrp']),
        'order_qty': _to_int(row['order_qty']),
        'allocated_qty': _to_int(row['allocated_qty']),
        'picked_qty': _to_int(row['picked_qty']),
    }


def _clean(value: str) -> str:
    """Collapse the cell's internal line breaks into single spaces.

    Wrapping inside a cell is genuinely ambiguous — a line break can be a real word
    boundary or a token split mid-word, and the PDF does not distinguish them. A
    space is the safe reading: turning "METER ASSEMBLY" + "COMBINATION" into one
    word is a worse error than leaving a space that was already there.

    The one place the ambiguity IS resolvable is the part number, which is why the
    part column strips whitespace outright (see _join_part) and the description gets
    its trailing part number repaired (see _repair_desc).
    """
    return ' '.join((value or '').split())


def _repair_desc(desc: str, part: str) -> str:
    """Rejoin the part number the description ends with.

    These descriptions always read "<text>-<PART NUMBER>", and the part number is the
    longest unbroken token on the line, so it is the piece the printer is most likely
    to wrap: the sample breaks "COMBINATION-ADGAA7Y00100099GS" into three lines.

    Unlike the prose half, this is repairable without guessing — the part number is
    sitting in its own column. Where the tail matches it ignoring whitespace, the tail
    is rewritten tightly; where it does not, the description is left exactly as read.
    """
    if not desc or not part or '-' not in desc:
        return desc

    head, _, tail = desc.rpartition('-')
    if re.sub(r'\s+', '', tail).upper() != part:
        return desc
    return '%s-%s' % (head.rstrip(), part)


def _join_part(value: str) -> str:
    """Strip ALL whitespace — a wrapped part number is one token, not two words."""
    return re.sub(r'\s+', '', (value or '')).upper()


def _to_int(value):
    text = _clean(value).replace(',', '')
    if not text:
        return None
    m = re.search(r'-?\d+', text)
    return int(m.group(0)) if m else None


def _to_decimal_str(value):
    """MRP stays a string. It is money that gets reprinted verbatim, never summed."""
    text = _clean(value).replace(',', '')
    if not text:
        return None
    m = re.search(r'-?\d+(?:\.\d+)?', text)
    return m.group(0) if m else None
