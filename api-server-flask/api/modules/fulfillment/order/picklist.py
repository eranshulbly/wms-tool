# -*- encoding: utf-8 -*-
"""
Picklist generation for orders created by file upload.

A warehouse picker works off one printed sheet per order: what to pick, from
where, and how many cases that makes. Every order the "Upload Orders" pipeline
creates already carries upload_batch_id (order/service.py, via
BaseUploadService's create_upload_batch step), so that column alone is what
makes an order eligible here — the moment a file upload lands, its orders
appear in the Download Picklist list, exactly as many rows as orders in the
file. Orders raised by hand (Submitted Orders' Add Order cart) have no
upload_batch_id and are deliberately left out: those were entered one at a
time already, with nothing to re-derive a picklist from.

Stock on hand and the Cases figure both come from the same tables the rest of
the app already uses for them — fc_entity_stock (summed across every batch and
bin for the product, company-scoped) and product_uom's CASE rung (the same
packaging ladder order/router.py's _decompose_quantity reads), so a picklist
can never show a number that disagrees with what Inventory or an order detail
page would show for the same product.

Bin Location is printed as a single column, not the three (L1/L2/L3) some
picklists split it into — fc_entity_stock stores bin_location as one string,
and today it is blank for every row (the multi-bin layout was never wired
up), so the column simply prints blank until that's captured somewhere. That
is a real, honest gap, not a bug in this module.
"""

from datetime import date, datetime
from io import BytesIO

from api.shared.db_manager import mysql_manager
from api.permissions import company_filter_sql


class PicklistError(Exception):
    """The requested order has no picklist to give — not found, not this
    caller's company, or not created by a file upload."""


# Orders still worth handing a picker a sheet for. Once an order is Packed or
# past it, picking is already done — the order stays in the system, just not
# in this list, so the list doesn't grow forever with orders nobody would
# ever pick again.
PICKABLE_STATUSES = ('Open', 'Picking')


# --------------------------------------------------------------------------- #
# Listing — Download Picklist page                                            #
# --------------------------------------------------------------------------- #

def list_picklist_orders(company_ids, warehouse_id=None):
    """One row per order that is open and ready to pick.

    Newest first (ties broken by order id) so a just-uploaded file's orders
    land at the top, matching where the operator is looking right after the
    upload finishes.
    """
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    status_ph = ','.join(['%s'] * len(PICKABLE_STATUSES))
    # Params must line up left-to-right with the placeholders as they appear in the SQL
    # text below: status list first, then the company filter, then (optionally) warehouse.
    params = list(PICKABLE_STATUSES) + list(cf_params)
    wh_clause = ''
    if warehouse_id:
        wh_clause = ' AND po.warehouse_id = %s'
        params.append(warehouse_id)

    rows = mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.order_date,
                   po.status, po.warehouse_id, po.company_id,
                   d.name AS dealer_name, d.town AS dealer_town,
                   (SELECT COUNT(*) FROM potential_order_product pop
                     WHERE pop.potential_order_id = po.potential_order_id) AS item_count
              FROM potential_order po
              LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
             WHERE po.upload_batch_id IS NOT NULL
               AND po.status IN ({status_ph})
               AND {cf_sql}{wh_clause}
             ORDER BY po.order_date DESC, po.potential_order_id DESC""",
        tuple(params)) or []

    out = []
    for r in rows:
        out.append({
            'order_id': r['potential_order_id'],
            'order_number': r['original_order_id'] or f"PO{r['potential_order_id']}",
            'order_date': r['order_date'].isoformat() if r['order_date'] else None,
            'status': r['status'],
            'dealer_name': r['dealer_name'] or 'Unknown dealer',
            'dealer_town': r['dealer_town'],
            'warehouse_id': r['warehouse_id'],
            'company_id': r['company_id'],
            'item_count': r['item_count'] or 0,
        })
    return out


# --------------------------------------------------------------------------- #
# PDF generation — one order                                                  #
# --------------------------------------------------------------------------- #

def _uom_rungs(product_ids):
    """{product_id: [rung rows]} — same shape/query as order/router.py's
    _uom_rungs_by_product, kept local so this module has no import-order
    dependency on the route file."""
    ids = [p for p in set(product_ids) if p]
    if not ids:
        return {}
    ph = ','.join(['%s'] * len(ids))
    rows = mysql_manager.execute_query(
        f"""SELECT product_id, uom_code, factor_to_base, is_stock_unit
              FROM product_uom WHERE product_id IN ({ph})""", tuple(ids)) or []
    by_product = {}
    for r in rows:
        by_product.setdefault(r['product_id'], []).append(r)
    return by_product


def _cases_display(quantity, rungs):
    """('<n>', n) for a quantity that divides evenly into whole cases, or
    ('<qty> loose', 0) otherwise — no CASE rung, no stock rung, or a
    remainder left over. The second value is what "Total No of Cases"
    sums, so a "loose" line (by definition not a whole case) never adds to it,
    matching a physical pick list's own convention.
    """
    if quantity is None:
        return '', 0
    stock = next((r for r in rungs if r['is_stock_unit']), None)
    case = next((r for r in rungs if r['uom_code'] == 'CASE'), None)
    if not stock or not stock['factor_to_base'] or not case or not case['factor_to_base']:
        return f'{quantity} loose', 0
    per_case = int(case['factor_to_base'] / stock['factor_to_base'])
    if per_case <= 0:
        return f'{quantity} loose', 0
    n, rem = divmod(int(quantity), per_case)
    if rem == 0 and n > 0:
        return str(n), n
    return f'{quantity} loose', 0


def _order_for_picklist(order_id, company_ids):
    """The one order header this picklist is for, or None if it doesn't
    exist / isn't a file-upload order / isn't in the caller's company scope."""
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    rows = mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.order_date, po.company_id,
                   d.name AS dealer_name, d.town AS dealer_town, d.gstin AS dealer_gstin,
                   w.name AS warehouse_name, c.name AS company_name
              FROM potential_order po
              LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
              LEFT JOIN warehouse w ON w.warehouse_id = po.warehouse_id
              LEFT JOIN company c ON c.company_id = po.company_id
             WHERE po.potential_order_id = %s
               AND po.upload_batch_id IS NOT NULL
               AND {cf_sql}""",
        (order_id, *cf_params))
    return rows[0] if rows else None


def _order_lines(order_id):
    return mysql_manager.execute_query(
        """SELECT pop.product_id, pop.quantity,
                  COALESCE(p.product_string, pop.sku_code) AS sku_code,
                  COALESCE(p.name, pop.product_name)        AS product_name,
                  p.hsn_code
             FROM potential_order_product pop
             LEFT JOIN product p ON p.product_id = pop.product_id
            WHERE pop.potential_order_id = %s
            ORDER BY pop.potential_order_product_id""",
        (order_id,)) or []


def _stock_on_hand(product_ids, company_id):
    """{product_id: (stock_qty, bin_location)} — stock summed across every
    batch and bin for the product in this company; bin_location is whichever
    non-blank one comes first (there is usually at most one)."""
    ids = [p for p in set(product_ids) if p]
    if not ids:
        return {}
    ph = ','.join(['%s'] * len(ids))
    rows = mysql_manager.execute_query(
        f"""SELECT entity_id, SUM(quantity) AS stock_qty,
                   MIN(NULLIF(bin_location, '')) AS bin_location
              FROM fc_entity_stock
             WHERE company_id = %s AND entity_id IN ({ph})
             GROUP BY entity_id""",
        (company_id, *ids)) or []
    return {r['entity_id']: (r['stock_qty'], r['bin_location']) for r in rows}


def build_picklist_pdf(order_id, company_ids):
    """Render the picklist PDF for one order. Raises PicklistError if the
    order can't be found in this caller's scope or wasn't created by a file
    upload."""
    order = _order_for_picklist(order_id, company_ids)
    if not order:
        raise PicklistError(f'Order {order_id} has no picklist to download.')

    lines = _order_lines(order_id)
    product_ids = [l['product_id'] for l in lines]
    stock_by_product = _stock_on_hand(product_ids, order['company_id'])
    rungs_by_product = _uom_rungs(product_ids)

    return _render_pdf(order, lines, stock_by_product, rungs_by_product)


def build_picklist_zip(order_ids, company_ids):
    """One PDF per order, bundled into a zip — what the "Download Picklist"
    button on the list page actually calls when one or more orders are
    selected, one file each, so a multi-order selection is still one click
    and one download.

    Orders that no longer resolve (wrong company, deleted, or simply not a
    file-upload order — the selection came from the client and could be
    stale) are silently left out rather than failing the whole batch; the
    zip just ends up with fewer files than were selected. Raises
    PicklistError only when NONE of the requested orders resolved, so the
    caller isn't handed an empty zip with nothing to open.
    """
    import zipfile

    buf = BytesIO()
    included = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        seen_names = set()
        for order_id in order_ids:
            order = _order_for_picklist(order_id, company_ids)
            if not order:
                continue
            try:
                pdf_bytes = build_picklist_pdf(order_id, company_ids)
            except Exception:
                # One bad order shouldn't sink the rest of the selection.
                continue

            order_no = order['original_order_id'] or f"PO{order['potential_order_id']}"
            name = f'picklist_{order_no}.pdf'
            # original_order_id isn't guaranteed unique across companies, and two
            # orders sharing a name would silently overwrite one another in the zip.
            if name in seen_names:
                name = f'picklist_{order_no}_{order["potential_order_id"]}.pdf'
            seen_names.add(name)
            zf.writestr(name, pdf_bytes)
            included += 1

    if included == 0:
        raise PicklistError('None of the selected orders have a picklist to download.')

    return buf.getvalue()


def _render_pdf(order, lines, stock_by_product, rungs_by_product):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    styles = getSampleStyleSheet()

    def P(text, **kwargs):
        style = styles['Normal'].clone('tmp')
        for k, v in kwargs.items():
            setattr(style, k, v)
        return Paragraph('' if text is None else str(text), style)

    bold_center_lg = dict(fontName='Helvetica-Bold', fontSize=13, alignment=TA_CENTER)
    bold_center_md = dict(fontName='Helvetica-Bold', fontSize=10, alignment=TA_CENTER)
    norm_center_md = dict(fontName='Helvetica', fontSize=9, alignment=TA_CENTER)
    bold_left = dict(fontName='Helvetica-Bold', fontSize=8, alignment=TA_LEFT)
    norm_left = dict(fontName='Helvetica', fontSize=8, alignment=TA_LEFT)
    head_cell = dict(fontName='Helvetica-Bold', fontSize=7.5, alignment=TA_CENTER, textColor=colors.white)
    body_cell = dict(fontName='Helvetica', fontSize=7.5, alignment=TA_CENTER)
    body_left = dict(fontName='Helvetica', fontSize=7.5, alignment=TA_LEFT)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
    )

    elements = []
    elements.append(P(order.get('company_name') or 'Company', **bold_center_lg))
    if order.get('warehouse_name'):
        elements.append(P(order['warehouse_name'], **bold_center_md))
    elements.append(P('Pick List', **bold_center_md))
    elements.append(Spacer(1, 6))

    order_date = order.get('order_date')
    if isinstance(order_date, (datetime, date)):
        order_date_str = order_date.strftime('%d/%m/%Y')
    else:
        order_date_str = str(order_date)[:10] if order_date else ''

    # ── Header info block: Code / Order No / Order Date, then Name / City ──
    header_rows = [
        [P('Code', **bold_left), P(order.get('dealer_gstin') or '', **norm_left),
         P('Order No', **bold_left), P(order['original_order_id'] or f"PO{order['potential_order_id']}", **norm_left),
         P('Order Date', **bold_left), P(order_date_str, **norm_left)],
        [P('Name', **bold_left), P(order.get('dealer_name') or 'Unknown dealer', **norm_left),
         P('City', **bold_left), P(order.get('dealer_town') or '', **norm_left),
         '', ''],
    ]
    header_table = Table(header_rows, colWidths=[22 * mm, 60 * mm, 22 * mm, 60 * mm, 22 * mm, 60 * mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8))

    # ── Items table ──────────────────────────────────────────────────────
    columns = ['S.No', 'Bin Location', 'Part Number', 'Description', 'HSN No.',
               'Stock on Hand', 'Order Qty', 'Cases', 'Picked Qty']
    table_data = [[P(c, **head_cell) for c in columns]]

    total_cases = 0
    for i, l in enumerate(lines, start=1):
        stock_qty, bin_location = stock_by_product.get(l['product_id'], (None, None))
        cases_text, cases_n = _cases_display(l['quantity'], rungs_by_product.get(l['product_id'], []))
        total_cases += cases_n
        table_data.append([
            P(i, **body_cell),
            P(bin_location or '', **body_cell),
            P(l['sku_code'] or '', **body_cell),
            P(l['product_name'] or '', **body_left),
            P(l['hsn_code'] or '', **body_cell),
            P(int(stock_qty) if stock_qty is not None else '—', **body_cell),
            P(l['quantity'], **body_cell),
            P(cases_text, **body_cell),
            P('', **body_cell),
        ])

    page_w_mm = (landscape(A4)[0] - 24 * mm) / mm
    pref = [10, 26, 26, 62, 18, 22, 18, 18, 18]  # mm, sums to 218 — scaled to fill the page
    scale = page_w_mm / sum(pref)
    col_widths = [(w * scale) * mm for w in pref]

    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 14))

    # ── Footer: signatures + total cases ────────────────────────────────
    footer_rows = [
        [P('Picked By', **bold_left), P('_' * 34, **norm_left),
         P('Picked Date', **bold_left), P('_' * 20, **norm_left),
         P('Total No of Cases', **bold_left), P(str(total_cases), **bold_left)],
        [P('Checked By', **bold_left), P('_' * 34, **norm_left),
         P('Checked Date', **bold_left), P('_' * 20, **norm_left), '', ''],
        [P('Packed By', **bold_left), P('_' * 34, **norm_left),
         P('Packed Date', **bold_left), P('_' * 20, **norm_left), '', ''],
        [P('Remarks', **bold_left), P('_' * 90, **norm_left), '', '', '', ''],
    ]
    footer_table = Table(footer_rows, colWidths=[22 * mm, 68 * mm, 26 * mm, 38 * mm, 32 * mm, 20 * mm])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('SPAN', (1, 3), (3, 3)),
    ]))
    elements.append(footer_table)

    doc.build(elements)
    return buf.getvalue()
