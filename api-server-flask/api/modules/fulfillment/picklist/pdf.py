# -*- encoding: utf-8 -*-
"""Redraw a pick list from its stored meta, with a QR code added top-right.

Built with ReportLab, the same way the supply sheet is (see
modules/logistics/supply_sheet/router.py:_build_pdf) — SimpleDocTemplate, a Table
per section, bytes out.

Nothing is overlaid on the uploaded file: the original PDF is not kept, so this is
the only renderer and a download always looks the same regardless of which DMS
build produced the input.

The QR sits where "Page N of M" used to, which is the only reliably empty corner on
the sheet; the page counter moves under it. The token prints in small monospace
below the symbol so a picker with a creased sheet can key it in rather than walk
back for a reprint — the order number and pick-list code are already in the header
block, so they are not repeated there.
"""

from io import BytesIO

from api.core.logging import get_logger
from api.modules.fulfillment.picklist import qrcode_payload

logger = get_logger(__name__)

# Widths are tuned to the sample layout. They MUST sum to no more than the printable
# width of A4 portrait at 10mm margins (190mm) — a wider total does not shrink the
# table, it overflows the frame, and adjacent cells then print on top of each other.
# The assertion below is not decoration: the first draft summed to 201 and the damage
# only showed up as two headers sharing one cell when the page was read back.
# A column has to fit its own HEADER, not just its values. The three quantity
# columns hold one or two digits but are titled "Order Qty", "Allocated Qty" and
# "Picked Qty"; at 8pt "Allocated" alone needs about 14mm. Sized at 9-10mm they
# overflowed into each other and the vertical rule between them disappeared, which
# reads back as a single cell containing "3 3" — the round-trip test caught it.
_COL_WIDTHS_MM = (
    8,     # S.No.
    15, 11, 11,   # Bin L1 / L2 / L3  (L1 takes "L3H8+9+10" and "NKF-105" whole)
    25,    # Part Number
    # Wide enough that "…-<PART NUMBER>" wraps AT the hyphen instead of hard-breaking
    # the part number in the middle. A mid-token break is ambiguous to read back: a
    # reader cannot tell it from a real word space — at 33mm "COMBINATION" came back
    # as "CO MBINATION".
    38,    # Description
    14,    # HSN No.
    9,     # MOQ
    12,    # Stock on Hand
    14,    # MRP
    11,    # Order Qty
    15,    # Allocated Qty
    11,    # Picked Qty
)
# 8mm side margins, not the usual 10: at 8pt every column has to fit its own
# header, and the three quantity titles plus a description wide enough to break at
# word boundaries do not add up inside 190mm. Well within any A4 printer's
# unprintable edge.
_PRINTABLE_WIDTH_MM = 194
assert sum(_COL_WIDTHS_MM) <= _PRINTABLE_WIDTH_MM, (
    "pick-list columns total %dmm, wider than the %dmm printable area"
    % (sum(_COL_WIDTHS_MM), _PRINTABLE_WIDTH_MM))

_SUPPORTED_META_VERSIONS = (1,)


class PicklistRenderError(Exception):
    """The stored meta could not be turned back into a page."""


def build_pdf(picklists: list) -> bytes:
    """Render one or more pick lists into a single PDF.

    `picklists` is a list of dicts, each {'qr_token', 'original_order_id',
    'picklist_code', 'meta'}. They are drawn in the order given, one page break
    between them — a batch download is one print job, not forty.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, PageBreak

    if not picklists:
        raise PicklistRenderError("nothing to render")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=10 * mm,
        title='Pick List',
    )

    story = []
    for i, pl in enumerate(picklists):
        if i:
            story.append(PageBreak())
        story.extend(_one_picklist(pl))

    doc.build(story)
    return buf.getvalue()


def _one_picklist(pl: dict) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Spacer

    meta = pl.get('meta') or {}
    version = meta.get('v')
    if version not in _SUPPORTED_META_VERSIONS:
        # Loud rather than best-effort: a half-drawn pick list handed to a picker is
        # worse than a download that says which sheet it could not rebuild.
        raise PicklistRenderError(
            "pick list %s was captured by meta version %r, which this build cannot "
            "render" % (pl.get('original_order_id'), version)
        )

    flow = []
    flow.append(_header_table(pl, meta))
    flow.append(Spacer(1, 3 * mm))
    flow.append(_order_block(meta))
    flow.append(Spacer(1, 3 * mm))
    flow.append(_lines_table(meta))
    flow.append(Spacer(1, 8 * mm))
    flow.append(_footer_table(meta))
    return flow


# ── Styles ───────────────────────────────────────────────────────────────────

def _styles():
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    base = getSampleStyleSheet()['Normal']

    def make(size, bold=False, align=TA_LEFT, leading=None):
        s = base.clone('pl%s%s%s' % (size, bold, align))
        s.fontName = 'Helvetica-Bold' if bold else 'Helvetica'
        s.fontSize = size
        s.leading = leading or size + 1.5
        s.alignment = align
        return s

    return {
        # Sized against the DMS original rather than to fit as much as possible.
        # The first cut set the table at 6.5pt, which reads as a shrunken copy of
        # the sheet next to it on the bench — and these are read at arm's length
        # off a trolley, so smaller is not a neutral trade.
        'centre': make(8.5, align=TA_CENTER, leading=10),
        'centre_bold': make(8.5, bold=True, align=TA_CENTER, leading=10),
        'title': make(13, bold=True, align=TA_CENTER, leading=16),
        'name': make(11, bold=True, align=TA_CENTER, leading=13),
        'label': make(8.5, bold=True, align=TA_LEFT),
        'value': make(8.5, align=TA_LEFT),
        'cell': make(8, align=TA_LEFT, leading=9.4),
        'cell_centre': make(8, align=TA_CENTER, leading=9.4),
        'cell_head': make(8, bold=True, align=TA_CENTER, leading=9.4),
        'token': make(6, align=TA_CENTER, leading=7),
    }


def _P(text, style):
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape
    return Paragraph(escape('' if text is None else str(text)), style)


def _desc_paragraph(desc, part, style):
    """The description, broken before the part number it ends with.

    These descriptions read "<text>-<PART NUMBER>", and the part number is a single
    unbreakable token far wider than any column this table can afford — about 49mm
    at 8pt against a 38mm column. Left alone ReportLab breaks it wherever the line
    runs out, which lands mid-word: "COMBI NATION".

    The DMS sheet solves it by putting the part number on its own line ("SOCKET 20-"
    / "070HH198012S"), so this does the same with an explicit break. Two things fall
    out of matching it: the page looks like the original, and the text survives a
    round trip — a break at the hyphen is one _repair_desc can undo, whereas one
    inside a word is not.

    A zero-width space would be the subtler way to offer the break, but ReportLab
    renders U+200B as a literal "n".
    """
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    text = '' if desc is None else str(desc)
    if part:
        marker = '-' + part
        if text.upper().endswith(marker.upper()):
            head = text[:-len(part)]        # keeps the hyphen on the first line
            return Paragraph(escape(head) + '<br/>' + escape(part), style)
    return Paragraph(escape(text), style)


# ── Header (letterhead + QR) ─────────────────────────────────────────────────

def _header_table(pl: dict, meta: dict):
    """Two columns: the centred letterhead, and the QR block on the right."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    st = _styles()
    head = meta.get('header') or {}

    centre = [_P(head.get('distributor_name', ''), st['name'])]
    for line in head.get('address_lines') or []:
        centre.append(_P(line, st['centre']))

    bits = []
    if head.get('state_code'):
        bits.append('State Code: %s' % head['state_code'])
    if head.get('contact'):
        bits.append('Contact: %s' % head['contact'])
    if bits:
        centre.append(_P(' '.join(bits), st['centre']))
    if head.get('gstin'):
        centre.append(_P('GSTIN No: %s' % head['gstin'], st['centre']))
    if head.get('authorized_distributor_of'):
        centre.append(_P('Authorized Parts Distributor: %s'
                         % head['authorized_distributor_of'], st['centre']))
    centre.append(_P(head.get('doc_title') or 'Pick List', st['title']))

    table = Table(
        [[centre, _qr_cell(pl)]],
        # The letterhead is centred on the page in the original, so the QR must
        # cost it as little width as possible — at 35mm the whole block was
        # visibly shoved left of centre.
        colWidths=[172 * mm, 22 * mm],
    )
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
        ('VALIGN', (1, 0), (1, 0), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return table


def _qr_cell(pl: dict):
    """QR symbol, the token in text under it, then the page counter."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    st = _styles()
    payload = qrcode_payload.build(
        pl.get('original_order_id', ''),
        pl.get('picklist_code', ''),
        pl.get('qr_token', ''),
    )

    rows = [
        [_qr_drawing(payload)],
        [_P(pl.get('qr_token', ''), st['token'])],
        [_P('Page 1 of 1', st['token'])],
    ]
    inner = Table(rows, colWidths=[22 * mm])
    inner.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return inner


def _qr_drawing(payload: str):
    """A 25mm QR at error-correction level Q.

    Q (25% recovery) rather than the usual M: these sheets ride around a warehouse
    on a trolley and get creased, smudged and folded before anyone scans them.

    reportlab ships its own QR widget, so this needs no extra dependency.
    """
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.units import mm

    side = 20 * mm
    widget = qr.QrCodeWidget(payload, barLevel='Q')
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]

    drawing = Drawing(side, side, transform=[side / width, 0, 0, side / height,
                                             -bounds[0] * side / width,
                                             -bounds[1] * side / height])
    drawing.add(widget)
    return drawing


# ── Order block ──────────────────────────────────────────────────────────────

def _order_block(meta: dict):
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    st = _styles()
    order = meta.get('order') or {}

    rows = [
        [_P('Code', st['label']), _P(order.get('code', ''), st['value']),
         _P('Order No', st['label']), _P(order.get('order_no', ''), st['value']),
         _P('Order Date', st['label']), _P(order.get('order_date', ''), st['value'])],
        [_P('Name', st['label']), _P(order.get('dealer_name', ''), st['value']),
         '', '', '', ''],
        [_P('City', st['label']), _P(order.get('city', ''), st['value']),
         '', '', '', ''],
    ]
    table = Table(rows, colWidths=[16 * mm, 56 * mm, 20 * mm, 52 * mm, 22 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return table


# ── Line table ───────────────────────────────────────────────────────────────

def _lines_table(meta: dict):
    """The parts grid, with the two-row header the original prints.

    'Bin Location' spans L1/L2/L3 via a SPAN; the other headers span vertically so
    the stacked labels ("S. / No.", "Stock on / Hand") land in one cell each.
    """
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    st = _styles()

    head_row_1 = [
        _P('S. No.', st['cell_head']),
        _P('Bin Location', st['cell_head']), '', '',
        _P('Part Number', st['cell_head']),
        _P('Description', st['cell_head']),
        _P('HSN No.', st['cell_head']),
        _P('MOQ', st['cell_head']),
        _P('Stock on Hand', st['cell_head']),
        _P('MRP', st['cell_head']),
        _P('Order Qty', st['cell_head']),
        _P('Allocated Qty', st['cell_head']),
        _P('Picked Qty', st['cell_head']),
    ]
    head_row_2 = [
        '',
        _P('L1', st['cell_head']), _P('L2', st['cell_head']), _P('L3', st['cell_head']),
        '', '', '', '', '', '', '', '', '',
    ]

    data = [head_row_1, head_row_2]
    for line in meta.get('lines') or []:
        bins = (line.get('bin') or ['', '', ''])[:3]
        bins = list(bins) + [''] * (3 - len(bins))
        data.append([
            _P(_num(line.get('sl')), st['cell_centre']),
            _P(bins[0], st['cell_centre']),
            _P(bins[1], st['cell_centre']),
            _P(bins[2], st['cell_centre']),
            _P(line.get('part', ''), st['cell']),
            _desc_paragraph(line.get('desc', ''), line.get('part', ''), st['cell']),
            _P(line.get('hsn', ''), st['cell_centre']),
            _P(_num(line.get('moq')), st['cell_centre']),
            _P(_num(line.get('stock')), st['cell_centre']),
            _P(_money(line.get('mrp')), st['cell_centre']),
            _P(_num(line.get('order_qty')), st['cell_centre']),
            _P(_num(line.get('allocated_qty')), st['cell_centre']),
            # Left blank on purpose — the picker writes it in by hand, exactly as on
            # the document the DMS prints.
            _P(_num(line.get('picked_qty')), st['cell_centre']),
        ])

    table = Table(
        data,
        colWidths=[w * mm for w in _COL_WIDTHS_MM],
        # No repeatRows, matching the DMS original: its page 2 carries on straight
        # from row 19 with no column headers. Repeating them reads as a tidier
        # document but it is a different one, and these are checked side by side
        # against the sheet the DMS printed.
        repeatRows=0,
    )
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('SPAN', (1, 0), (3, 0)),        # Bin Location arches over L1/L2/L3
        ('SPAN', (0, 0), (0, 1)),        # S. No.
        ('SPAN', (4, 0), (4, 1)),        # Part Number
        ('SPAN', (5, 0), (5, 1)),        # Description
        ('SPAN', (6, 0), (6, 1)),        # HSN No.
        ('SPAN', (7, 0), (7, 1)),        # MOQ
        ('SPAN', (8, 0), (8, 1)),        # Stock on Hand
        ('SPAN', (9, 0), (9, 1)),        # MRP
        ('SPAN', (10, 0), (10, 1)),      # Order Qty
        ('SPAN', (11, 0), (11, 1)),      # Allocated Qty
        ('SPAN', (12, 0), (12, 1)),      # Picked Qty
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Row padding matched to the original's density: at 2pt the sheet fitted
        # 24 lines where the DMS fits 18, which is the same complaint as a small
        # font wearing a different hat.
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    return table


def _footer_table(meta: dict):
    """The sign-off grid: Picked/Checked/Packed By and Date, then Remarks."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    st = _styles()
    rows = [
        [_P('Picked By', st['label']), _P('Picked Date', st['label']),
         _P('Total No of Cases', st['label'])],
        [_P('Checked By', st['label']), _P('Checked Date', st['label']), ''],
        [_P('Packed By', st['label']), _P('Packed Date', st['label']), ''],
        [_P('Remarks', st['label']), '', ''],
    ]
    table = Table(rows, colWidths=[65 * mm, 65 * mm, 64 * mm], rowHeights=[12 * mm] * 4)
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    return table


def _num(value):
    return '' if value is None else str(value)


def _money(value):
    """Reprint MRP the way the document showed it: two decimals, thousands grouped."""
    if value in (None, ''):
        return ''
    try:
        return '{:,.2f}'.format(float(value))
    except (TypeError, ValueError):
        return str(value)
