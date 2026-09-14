# -*- encoding: utf-8 -*-
"""Pick lists — the sheet a picker walks the warehouse with.

One document per order, laid out like the printed pick list the warehouse already uses:
a header identifying who the goods are for, a line per part telling the picker where to
find it and how many to take, and signature blocks at the foot for picked / checked /
packed.

The column this system adds is CASES. A picker sent for "200" of a part that comes 50 to a
case has to do the division in their head, and gets it wrong at the end of a long shift;
printing "4 cases" next to the 200 removes the arithmetic from the warehouse floor. The
factor comes from product_uom, so it is the same ladder orders and prices are converted
through — not a number re-entered for picking and free to disagree with the rest.

Quantities are printed in the base unit AS ORDERED, with the case count beside them rather
than instead of them. An order for 210 where a case holds 50 is "210" and "4 + 10 loose",
never "4.2 cases", because a picker cannot pick two tenths of a case and rounding it to 4
would short the dealer by ten.
"""

import io
import re
import zipfile
from datetime import datetime

from api.shared.db_manager import mysql_manager, partition_filter
from api.core.logging import get_logger

logger = get_logger(__name__)


# Only these orders can be picked. An order that has not reached Open has not been
# accepted yet, and one past it has already been picked — printing either invites the
# warehouse to pick something twice.
PICKABLE_STATUSES = ('Open',)

# Bins are separated by COMMAS, and by nothing else.
#
# A location is one whole code — "A-10-C-01", and equally "A-04 - C-02", which is the same
# code with spaces around its middle dash. Splitting on that dash was wrong: it turned one
# bin into two half-bins ("A-04" and "C-02") and would have sent a picker to two places
# that do not exist. Only a comma separates genuinely different bins, as in
# "A-02-C-01, A-02-C-02, A-02-B-01".
_BIN_SPLIT = re.compile(r'\s*[,;|]\s*')


def split_bins(bin_location, columns=3):
    """The L1/L2/L3 cells for one part.

    Padded to `columns` so every row has the same shape. When a part is spread across MORE
    bins than there are columns, the surplus is joined into the last cell rather than
    dropped — a bin that does not appear on the sheet is stock the picker will not find,
    which is worse than a slightly crowded cell.
    """
    text = str(bin_location or '').strip()
    parts = [p.strip() for p in _BIN_SPLIT.split(text) if p and p.strip()] if text else []
    if len(parts) > columns:
        parts = parts[:columns - 1] + [', '.join(parts[columns - 1:])]
    return parts + [''] * (columns - len(parts))


def case_breakdown(quantity, units_per_case):
    """(cases, loose, label) for a quantity in base units.

    Returns whole cases and whatever will not fill one. A part with no case size — most of
    them — gets (None, None, '') rather than a fabricated "1 case", because a ladder this
    system was never told about is unknown, not equal to one.
    """
    try:
        qty = int(quantity or 0)
        per = int(units_per_case or 0)
    except (TypeError, ValueError):
        return None, None, ''
    if per <= 1 or qty <= 0:
        return None, None, ''
    cases, loose = divmod(qty, per)
    if loose == 0:
        return cases, 0, str(cases)
    if cases == 0:
        return 0, loose, f'{loose} loose'
    return cases, loose, f'{cases} + {loose} loose'


def _orders(order_ids, company_ids=None):
    """Header rows for the requested orders, tenant-scoped."""
    if not order_ids:
        return []
    from api.permissions import company_filter_sql
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    placeholders = ','.join(['%s'] * len(order_ids))
    status_ph = ','.join(['%s'] * len(PICKABLE_STATUSES))
    return mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.order_date,
                   po.purchaser_name, po.purchaser_sap_code, po.shipping_address,
                   po.status, po.warehouse_id, po.created_at,
                   d.name  AS dealer_name, d.dealer_code, d.town, d.gstin AS dealer_gstin,
                   d.address AS dealer_address,
                   w.name  AS warehouse_name, w.location AS warehouse_location,
                   w.code  AS warehouse_code,
                   c.name  AS company_name
            FROM potential_order po
            LEFT JOIN dealer    d ON d.dealer_id    = po.dealer_id
            LEFT JOIN warehouse w ON w.warehouse_id = po.warehouse_id
            LEFT JOIN company   c ON c.company_id   = po.company_id
            WHERE {pf_sql} AND {cf_sql}
              AND po.potential_order_id IN ({placeholders})
              AND po.status IN ({status_ph})""",
        pf_params + tuple(cf_params) + tuple(order_ids) + PICKABLE_STATUSES) or []


def _lines(order_ids):
    """Every line of the requested orders, with bin, case size and stock on hand.

    One query for all the orders rather than one per order: a picker printing a morning's
    work selects dozens at a time, and a query per order would put the round-trip count on
    the operator's wait.

    Ordered by bin so the printed sheet walks the warehouse in aisle order instead of
    sending the picker back and forth in whatever order the document happened to list.
    """
    if not order_ids:
        return {}
    pf_sql, pf_params = partition_filter('potential_order_product', alias='pop')
    placeholders = ','.join(['%s'] * len(order_ids))
    rows = mysql_manager.execute_query(
        f"""SELECT pop.potential_order_id, pop.quantity, pop.quantity_packed,
                   p.product_string, p.name, p.description, p.hsn_code,
                   pl.bin_location,
                   pu.factor_to_base AS units_per_case,
                   ti.quantity       AS stock_on_hand
            FROM potential_order_product pop
            JOIN product p ON p.product_id = pop.product_id
            LEFT JOIN product_location pl
                   ON pl.product_id = p.product_id
                  AND pl.warehouse_id = (SELECT warehouse_id FROM potential_order po2
                                         WHERE po2.potential_order_id = pop.potential_order_id
                                         LIMIT 1)
            LEFT JOIN product_uom pu
                   ON pu.product_id = p.product_id AND pu.uom_code = 'CASE'
            LEFT JOIN temp_inventory ti ON ti.part_number = p.product_string
            WHERE {pf_sql} AND pop.potential_order_id IN ({placeholders})
            ORDER BY pop.potential_order_id,
                     CASE WHEN pl.bin_location IS NULL OR pl.bin_location = '' THEN 1 ELSE 0 END,
                     pl.bin_location, p.product_string""",
        pf_params + tuple(order_ids)) or []

    grouped = {}
    for row in rows:
        cases, loose, label = case_breakdown(row['quantity'], row['units_per_case'])
        bins = split_bins(row['bin_location'])
        grouped.setdefault(row['potential_order_id'], []).append({
            'part_number': row['product_string'],
            'description': row['name'] or row['description'] or '',
            'hsn': row['hsn_code'] or '',
            'bins': bins,
            'quantity': int(row['quantity'] or 0),
            'units_per_case': int(row['units_per_case']) if row['units_per_case'] else None,
            'cases': cases,
            'loose': loose,
            'cases_label': label,
            'stock_on_hand': int(row['stock_on_hand']) if row['stock_on_hand'] is not None else None,
            'quantity_packed': int(row['quantity_packed'] or 0),
        })
    return grouped


def build(order_ids, company_ids=None):
    """[{header, lines}] for the requested orders. Orders not pickable are omitted."""
    orders = _orders(order_ids, company_ids)
    if not orders:
        return []
    lines = _lines([o['potential_order_id'] for o in orders])
    out = []
    for order in orders:
        order_lines = lines.get(order['potential_order_id'], [])
        total_cases = sum(l['cases'] or 0 for l in order_lines)
        out.append({'order': order, 'lines': order_lines, 'total_cases': total_cases})
    logger.info("picklist built", extra={
        'orders': len(out), 'lines': sum(len(o['lines']) for o in out)})
    return out


# ── PDF rendering ────────────────────────────────────────────────────────────

def _safe_filename(text):
    """An order number as a filename component. Slashes in order numbers are common."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', str(text or 'order')).strip('_')
    return cleaned or 'order'


def render_pdf(picklists):
    """One PDF holding the given picklists, a page each. Returns bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title='Pick List')

    styles = getSampleStyleSheet()
    centre = ParagraphStyle('c', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9)
    title = ParagraphStyle('t', parent=styles['Normal'], alignment=TA_CENTER,
                           fontSize=13, spaceBefore=4, spaceAfter=4, fontName='Helvetica-Bold')
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontSize=7, leading=8.5)

    story = []
    for index, sheet in enumerate(picklists):
        if index:
            story.append(PageBreak())
        story.extend(_sheet_flowables(sheet, centre, title, cell, colors, Table,
                                      TableStyle, Paragraph, Spacer, mm))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def _sheet_flowables(sheet, centre, title, cell, colors, Table, TableStyle,
                     Paragraph, Spacer, mm):
    """The flowables for one order's page."""
    order, lines = sheet['order'], sheet['lines']
    flow = []

    # ── Who is issuing, and to whom ──────────────────────────────────────────
    issuer = [order.get('company_name') or '']
    for extra in (order.get('warehouse_name'), order.get('warehouse_location')):
        if extra:
            issuer.append(str(extra))
    for text in issuer:
        if text:
            flow.append(Paragraph(f'<b>{_esc(text)}</b>' if text is issuer[0] else _esc(text),
                                  centre))
    flow.append(Paragraph('Pick List', title))

    # The dealer's own details when the dealer record carries them, and what the order
    # document said when it does not — an order uploaded from a challan names its buyer
    # even before anyone has filled in a dealer record for them.
    name = order.get('dealer_name') or order.get('purchaser_name') or ''
    code = order.get('dealer_code') or order.get('purchaser_sap_code') or ''
    date = order.get('order_date') or order.get('created_at')
    # NOT escaped: these are plain table cells, and reportlab renders a plain cell
    # literally. Escaping here printed the dealer "M/S RAM GLASS & PLYWOOD" as
    # "M/S RAM GLASS &amp; PLYWOOD" on the sheet. Only Paragraph parses mini-HTML, so
    # only Paragraph content is escaped.
    meta = [
        ['Code', code, 'Order No', order.get('original_order_id') or '',
         'Order Date', _fmt_date(date)],
        ['Name', name, 'City', order.get('town') or '', '', ''],
    ]
    meta_table = Table(meta, colWidths=[18 * mm, 70 * mm, 22 * mm, 70 * mm, 24 * mm, 40 * mm])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTNAME', (4, 0), (4, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    flow.append(meta_table)
    flow.append(Spacer(1, 4 * mm))

    # ── The lines ────────────────────────────────────────────────────────────
    header = [
        ['S.\nNo.', 'Bin Location', '', '', 'Part Number', 'Description', 'HSN No.',
         'Stock on\nHand', 'Order\nQty', 'Cases', 'Picked\nQty'],
        ['', 'L1', 'L2', 'L3', '', '', '', '', '', '', ''],
    ]
    body = []
    for n, line in enumerate(lines, 1):
        body.append([
            str(n),
            # Paragraphs, not plain strings, so a long bin cell WRAPS inside its column.
            # A part in several bins puts the surplus in L3 ("A-02-B-01, A-02-B-02"),
            # which is wider than the column; as a plain cell that does not wrap, it
            # overflowed and printed on top of the part number.
            _bin_cell(line['bins'][0], cell, Paragraph),
            _bin_cell(line['bins'][1], cell, Paragraph),
            _bin_cell(line['bins'][2], cell, Paragraph),
            # Paragraphs — these DO parse mini-HTML, so their content is escaped. Part
            # descriptions carry & and " freely.
            Paragraph(_esc(line['part_number']), cell),
            Paragraph(_esc(line['description']), cell),
            line['hsn'],
            '' if line['stock_on_hand'] is None else str(line['stock_on_hand']),
            str(line['quantity']),
            line['cases_label'],
            '',                      # filled in by hand on the floor
        ])
    if not body:
        body = [['', '', '', '', Paragraph('<i>No line items on this order</i>', cell),
                 '', '', '', '', '', '']]

    # Bin columns are wide enough for a full code plus its comma ("A-02-B-01,") at 7pt;
    # the description gives up the millimetres, being the one column that reads fine
    # wrapped onto two lines.
    widths = [10 * mm, 18 * mm, 18 * mm, 18 * mm, 36 * mm, 64 * mm, 20 * mm,
              18 * mm, 15 * mm, 22 * mm, 16 * mm]
    table = Table(header + body, colWidths=widths, repeatRows=2)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('ALIGN', (7, 2), (10, -1), 'CENTER'),
        ('ALIGN', (0, 2), (0, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 1), colors.Color(0.92, 0.92, 0.92)),
        ('SPAN', (1, 0), (3, 0)),        # 'Bin Location' spans L1..L3
        ('SPAN', (0, 0), (0, 1)),
        ('SPAN', (4, 0), (4, 1)), ('SPAN', (5, 0), (5, 1)), ('SPAN', (6, 0), (6, 1)),
        ('SPAN', (7, 0), (7, 1)), ('SPAN', (8, 0), (8, 1)), ('SPAN', (9, 0), (9, 1)),
        ('SPAN', (10, 0), (10, 1)),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    flow.append(table)
    flow.append(Spacer(1, 6 * mm))

    # ── Sign-off ─────────────────────────────────────────────────────────────
    total_cases = sheet.get('total_cases') or 0
    footer = [
        ['Picked By', '', 'Picked Date', '', 'Total No of Cases', str(total_cases or '')],
        ['Checked By', '', 'Checked Date', '', '', ''],
        ['Packed By', '', 'Packed Date', '', '', ''],
        ['Remarks', '', '', '', '', ''],
    ]
    foot = Table(footer, colWidths=[28 * mm, 55 * mm, 28 * mm, 55 * mm, 38 * mm, 30 * mm])
    foot.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTNAME', (4, 0), (4, 0), 'Helvetica-Bold'),
        ('LINEBELOW', (1, 0), (1, 2), 0.4, colors.black),
        ('LINEBELOW', (3, 0), (3, 2), 0.4, colors.black),
        ('LINEBELOW', (1, 3), (5, 3), 0.4, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    flow.append(foot)
    return flow


def _bin_cell(text, style, Paragraph):
    """One bin cell, with each bin code on its own line.

    The break is placed explicitly after the comma rather than left to word wrap: wrapping
    breaks at the SPACE after the comma, which puts a lone "," on a line of its own when
    the code before it is already as wide as the column.
    """
    return Paragraph(_esc(text).replace(', ', ',<br/>'), style)


def _esc(text):
    """Escape for reportlab's mini-HTML. Part descriptions contain & and < freely."""
    return (str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _fmt_date(value):
    if not value:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%d/%m/%Y')
    try:
        return value.strftime('%d/%m/%Y')
    except AttributeError:
        return str(value)


def render_zip(picklists):
    """One PDF per order, zipped. Returns bytes.

    Filenames carry the order number so a picklist can be found again without opening it.
    A number that repeats — which it should not, but the order table has no unique key to
    forbid it — gets a numeric suffix rather than silently overwriting its namesake.
    """
    buf = io.BytesIO()
    used = {}
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        for sheet in picklists:
            base = _safe_filename(sheet['order'].get('original_order_id'))
            used[base] = used.get(base, 0) + 1
            suffix = '' if used[base] == 1 else f'_{used[base]}'
            archive.writestr(f'picklist_{base}{suffix}.pdf', render_pdf([sheet]))
    buf.seek(0)
    return buf.read()
