# -*- encoding: utf-8 -*-
"""
Supply Sheet routes:
  GET  /api/supply-sheet/dealers               — dealers with invoiced orders
  GET  /api/supply-sheet/routes                — all transport routes
  GET  /api/supply-sheet/routes/<id>/dealers   — dealers for a route
  POST /api/supply-sheet/generate              — generate PDF supply sheet
"""

from datetime import date, datetime
from io import BytesIO

from flask import request, send_file
from flask_restx import Resource

from ..extensions import rest_api
from ..core.auth import token_required, active_required, supply_sheet_required
from ..db_manager import mysql_manager, partition_filter
from ..models import SupplySheetCounter
from ..core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# GET /api/supply-sheet/dealers
# ---------------------------------------------------------------------------

@rest_api.route('/api/supply-sheet/dealers')
class SupplySheetDealers(Resource):
    """
    Returns dealers that have at least one Invoiced order for the given
    warehouse + company.  Populates the frontend dealer table.

    Query params:
      warehouse_id  (int, required)
      company_id    (int, required)
    """

    @token_required
    @active_required
    @supply_sheet_required
    def get(self, current_user):
        warehouse_id = request.args.get('warehouse_id', type=int)
        company_id   = request.args.get('company_id',   type=int)

        if not warehouse_id or not company_id:
            return {'success': False, 'msg': 'warehouse_id and company_id are required'}, 400

        try:
            pf_inv_sql, pf_inv_params = partition_filter('invoice',         alias='i')
            pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')
            rows = mysql_manager.execute_query(
                f"""
                SELECT DISTINCT
                    d.dealer_id,
                    d.name,
                    d.dealer_code,
                    d.town
                FROM invoice i
                JOIN dealer d ON i.dealer_id = d.dealer_id
                JOIN potential_order po
                       ON po.original_order_id = i.original_order_id
                      AND po.warehouse_id      = i.warehouse_id
                      AND po.company_id        = i.company_id
                      AND {pf_po_sql}
                      AND po.status = 'Invoiced'
                WHERE {pf_inv_sql}
                  AND i.warehouse_id = %s
                  AND i.company_id   = %s
                ORDER BY d.name
                """,
                pf_po_params + pf_inv_params + (warehouse_id, company_id)
            )
            dealers = [
                {
                    'dealer_id':   r['dealer_id'],
                    'name':        r['name'],
                    'dealer_code': r['dealer_code'] or '',
                    'town':        r['town'] or '',
                }
                for r in (rows or [])
            ]
            return {'success': True, 'dealers': dealers}, 200

        except Exception as e:
            logger.exception("Error in GET /api/supply-sheet/dealers")
            return {'success': False, 'msg': f'Error fetching dealers: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# GET /api/supply-sheet/routes
# ---------------------------------------------------------------------------

@rest_api.route('/api/supply-sheet/routes')
class SupplySheetRoutes(Resource):
    """Returns all transport routes for the route selector dropdown."""

    @token_required
    @active_required
    @supply_sheet_required
    def get(self, current_user):
        try:
            rows = mysql_manager.execute_query(
                "SELECT route_id, name, description FROM transport_routes ORDER BY name"
            )
            routes = [
                {
                    'route_id':    r['route_id'],
                    'name':        r['name'],
                    'description': r['description'] or '',
                }
                for r in (rows or [])
            ]
            return {'success': True, 'routes': routes}, 200

        except Exception as e:
            logger.exception("Error in GET /api/supply-sheet/routes")
            return {'success': False, 'msg': f'Error fetching routes: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# GET /api/supply-sheet/routes/<route_id>/dealers
# ---------------------------------------------------------------------------

@rest_api.route('/api/supply-sheet/routes/<int:route_id>/dealers')
class SupplySheetRouteDealers(Resource):
    """
    Returns dealers assigned to this transport route that also have at least
    one Invoiced order for the given warehouse + company.

    Query params:
      warehouse_id  (int, required)
      company_id    (int, required)
    """

    @token_required
    @active_required
    @supply_sheet_required
    def get(self, current_user, route_id):
        warehouse_id = request.args.get('warehouse_id', type=int)
        company_id   = request.args.get('company_id',   type=int)

        if not warehouse_id or not company_id:
            return {'success': False, 'msg': 'warehouse_id and company_id are required'}, 400

        try:
            pf_inv_sql, pf_inv_params = partition_filter('invoice',         alias='i')
            pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')
            rows = mysql_manager.execute_query(
                f"""
                SELECT DISTINCT
                    d.dealer_id,
                    d.name,
                    d.dealer_code,
                    d.town
                FROM customer_route_mappings crm
                JOIN dealer d ON crm.dealer_id = d.dealer_id
                JOIN invoice i ON i.dealer_id   = d.dealer_id
                             AND i.warehouse_id  = %s
                             AND i.company_id    = %s
                             AND {pf_inv_sql}
                JOIN potential_order po
                       ON po.original_order_id = i.original_order_id
                      AND po.warehouse_id      = i.warehouse_id
                      AND po.company_id        = i.company_id
                      AND {pf_po_sql}
                      AND po.status = 'Invoiced'
                WHERE crm.route_id = %s
                ORDER BY d.name
                """,
                (warehouse_id, company_id) + pf_inv_params + pf_po_params + (route_id,)
            )
            dealers = [
                {
                    'dealer_id':   r['dealer_id'],
                    'name':        r['name'],
                    'dealer_code': r['dealer_code'] or '',
                    'town':        r['town'] or '',
                }
                for r in (rows or [])
            ]
            return {'success': True, 'dealers': dealers}, 200

        except Exception as e:
            logger.exception("Error in GET /api/supply-sheet/routes/<route_id>/dealers")
            return {'success': False, 'msg': f'Error fetching route dealers: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# POST /api/supply-sheet/generate
# ---------------------------------------------------------------------------

@rest_api.route('/api/supply-sheet/generate')
class SupplySheetGenerate(Resource):
    """
    Generate a PDF supply sheet for a set of dealers.

    JSON body:
      warehouse_id  int           (required)
      company_id    int           (required)
      dealer_ids    list[int]     (required, min 1)

    Returns a binary PDF file.
    """

    @token_required
    @active_required
    @supply_sheet_required
    def post(self, current_user):
        data         = request.get_json(force=True) or {}
        warehouse_id = data.get('warehouse_id')
        company_id   = data.get('company_id')
        dealer_ids   = data.get('dealer_ids', [])
        finalize     = bool(data.get('finalize', False))

        if not warehouse_id or not company_id:
            return {'success': False, 'msg': 'warehouse_id and company_id are required'}, 400
        if not dealer_ids:
            return {'success': False, 'msg': 'At least one dealer_id is required'}, 400

        try:
            sheet_number = SupplySheetCounter.next_for_warehouse(warehouse_id)
            rows         = _fetch_supply_sheet_data(warehouse_id, company_id, dealer_ids)
            pdf_bytes    = _build_pdf(sheet_number, rows)

            if finalize:
                orders_moved = _finalize_orders(warehouse_id, company_id, dealer_ids, current_user.id)
                logger.info(
                    "Supply sheet finalized — orders moved to Dispatch Ready",
                    extra={
                        "warehouse_id": warehouse_id,
                        "company_id":   company_id,
                        "orders_moved": orders_moved,
                        "user_id":      current_user.id,
                    }
                )

            filename = (
                f"supply_sheet_{sheet_number}_{date.today().strftime('%d-%m-%y')}.pdf"
            )
            return send_file(
                BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=False,          # inline so browser can preview
                download_name=filename,
            )

        except Exception as e:
            logger.exception("Error generating supply sheet PDF")
            return {'success': False, 'msg': f'Error generating supply sheet: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# Finalize helper — transitions Invoiced orders to Dispatch Ready
# ---------------------------------------------------------------------------

def _finalize_orders(warehouse_id: int, company_id: int, dealer_ids: list, user_id: int) -> int:
    """
    Bulk-transition all Invoiced potential_orders for the given dealers to
    'Dispatch Ready' and write audit rows to order_state_history.

    Returns the number of orders moved.
    """
    from datetime import datetime

    if not dealer_ids:
        return 0

    now          = datetime.utcnow()
    placeholders = ', '.join(['%s'] * len(dealer_ids))

    pf_inv_sql, pf_inv_params = partition_filter('invoice',         alias='i')
    pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')

    # Resolve 'Dispatch Ready' state_id
    state_rows = mysql_manager.execute_query(
        "SELECT state_id FROM order_state WHERE state_name = %s", ('Dispatch Ready',)
    )
    if not state_rows:
        logger.error("'Dispatch Ready' state not found in order_states table")
        return 0
    dispatch_ready_id = state_rows[0]['state_id']

    # Find Invoiced potential_orders for the selected dealers
    order_rows = mysql_manager.execute_query(
        f"""
        SELECT DISTINCT po.potential_order_id
        FROM potential_order po
        JOIN invoice i ON i.original_order_id = po.original_order_id
                     AND i.warehouse_id        = po.warehouse_id
                     AND i.company_id          = po.company_id
                     AND {pf_inv_sql}
        WHERE {pf_po_sql}
          AND po.warehouse_id = %s
          AND po.company_id   = %s
          AND po.status       = 'Invoiced'
          AND i.dealer_id IN ({placeholders})
        """,
        pf_inv_params + pf_po_params + (warehouse_id, company_id) + tuple(dealer_ids)
    )

    if not order_rows:
        return 0

    po_ids      = [r['potential_order_id'] for r in order_rows]
    po_ph       = ', '.join(['%s'] * len(po_ids))

    # Bulk UPDATE potential_order → Dispatch Ready
    mysql_manager.execute_query(
        f"""UPDATE potential_order
            SET status = 'Dispatch Ready', updated_at = %s
            WHERE potential_order_id IN ({po_ph})""",
        (now,) + tuple(po_ids),
        fetch=False
    )

    # Bulk INSERT order_state_history
    hist_params = [(po_id, dispatch_ready_id, user_id, now) for po_id in po_ids]
    with mysql_manager.get_cursor() as cursor:
        cursor.executemany(
            """INSERT INTO order_state_history
               (potential_order_id, state_id, changed_by, changed_at)
               VALUES (%s, %s, %s, %s)""",
            hist_params
        )

    return len(po_ids)


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _fetch_supply_sheet_data(warehouse_id: int, company_id: int, dealer_ids: list) -> list:
    """
    Return one dict per invoice row for the selected dealers.
    Sorted by: dealer_name ASC → order_type ASC → invoice_date ASC.

    Each dict contains:
      invoice_number, original_order_id, dealer_name, town, order_type,
      invoice_value, box_count, invoice_date,
      oil_products: { product_label: qty }   — only for ZGOI orders
      (product_label uses nickname if set, otherwise description)
    """
    if not dealer_ids:
        return []

    placeholders = ', '.join(['%s'] * len(dealer_ids))
    pf_inv_sql, pf_inv_params = partition_filter('invoice',                  alias='i')
    pf_po_sql,  pf_po_params  = partition_filter('potential_order',          alias='po')
    pf_pop_sql, pf_pop_params = partition_filter('potential_order_product',  alias='pop')

    # ── Core invoice + order query ────────────────────────────────────────
    # Only include orders currently in 'Invoiced' state (not yet dispatched).
    invoice_rows = mysql_manager.execute_query(
        f"""
        SELECT
            i.invoice_id,
            i.invoice_number,
            i.original_order_id,
            i.invoice_round_off_amount   AS invoice_value,
            i.invoice_date,
            d.name                       AS dealer_name,
            d.town,
            po.potential_order_id,
            po.box_count,
            po.order_type
        FROM invoice i
        JOIN dealer d ON i.dealer_id = d.dealer_id
        JOIN potential_order po
               ON po.original_order_id = i.original_order_id
              AND po.warehouse_id      = i.warehouse_id
              AND po.company_id        = i.company_id
              AND {pf_po_sql}
              AND po.status = 'Invoiced'
        WHERE {pf_inv_sql}
          AND i.warehouse_id = %s
          AND i.company_id   = %s
          AND i.dealer_id IN ({placeholders})
        ORDER BY d.name ASC, po.order_type ASC, i.invoice_date ASC
        """,
        pf_po_params + pf_inv_params + (warehouse_id, company_id) + tuple(dealer_ids)
    )

    if not invoice_rows:
        return []

    # ── Collect potential_order_ids for ZGOI orders ───────────────────────
    zgoi_po_ids = [
        r['potential_order_id']
        for r in invoice_rows
        if r.get('order_type', '').upper() == 'ZGOI' and r.get('potential_order_id')
    ]

    # oil_map: { potential_order_id: { product_label: qty } }
    # product_label = nickname if set, else description
    oil_map = {}
    if zgoi_po_ids:
        po_placeholders = ', '.join(['%s'] * len(zgoi_po_ids))
        product_rows = mysql_manager.execute_query(
            f"""
            SELECT
                pop.potential_order_id,
                COALESCE(NULLIF(TRIM(p.nickname), ''), p.description) AS product_label,
                pop.quantity    AS qty
            FROM potential_order_product pop
            JOIN product p ON pop.product_id = p.product_id
            WHERE {pf_pop_sql}
              AND pop.potential_order_id IN ({po_placeholders})
            """,
            pf_pop_params + tuple(zgoi_po_ids)
        )
        for pr in (product_rows or []):
            po_id = pr['potential_order_id']
            label = (pr['product_label'] or '').strip()
            qty   = pr['qty'] or 0
            oil_map.setdefault(po_id, {})[label] = qty

    # ── Assemble result rows ──────────────────────────────────────────────
    result = []
    for r in invoice_rows:
        po_id        = r.get('potential_order_id')
        oil_products = oil_map.get(po_id, {}) if po_id else {}
        result.append({
            'invoice_number':    r['invoice_number'] or '',
            'original_order_id': r['original_order_id'] or '',
            'dealer_name':       r['dealer_name'] or '',
            'town':              r['town'] or '',
            'order_type':        r['order_type'] or '',
            'invoice_value':     float(r['invoice_value'] or 0),
            'box_count':         int(r['box_count'] or 0),
            'invoice_date':      r['invoice_date'],
            'oil_products':      oil_products,
        })

    return result


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _build_pdf(sheet_number: str, rows: list) -> bytes:
    """
    Build the supply sheet PDF using ReportLab.

    Layout:
      - Title row : "Supply Sheet No: {sheet_number}"
      - Sub-header: Date | Driver: ___ | Approved by: ___
      - "DESCRIPTION OIL IN PCS" spanning the dynamic oil columns
      - Data table with fixed columns (incl. Order Type) + dynamic product columns
      - TOTAL row at the bottom

    Rows are pre-sorted: dealer name → order type → invoice date.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    # ── Collect all unique oil product labels (preserving first-seen order) ──
    oil_labels = []
    seen = set()
    for r in rows:
        for label in r['oil_products']:
            if label not in seen:
                oil_labels.append(label)
                seen.add(label)

    FIXED_COLS  = ['Invoice No.', 'Order No.', 'Order Type', 'Account Name', 'Town',
                   'Invoice Value', 'Cases']
    TRAIL_COLS  = ['Invoice Date']
    all_columns = FIXED_COLS + oil_labels + TRAIL_COLS
    n_cols      = len(all_columns)

    # ── Styles ────────────────────────────────────────────────────────────
    styles       = getSampleStyleSheet()
    header_style = styles['Heading2']
    header_style.alignment = TA_CENTER

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )

    today_str = date.today().strftime('%d-%m-%y')

    # ── Colour palette ────────────────────────────────────────────────────
    HEADER_BG   = colors.HexColor('#4472C4')
    OIL_BG      = colors.HexColor('#70AD47')
    SUBHDR_BG   = colors.HexColor('#BDD7EE')
    TOTAL_BG    = colors.HexColor('#D9D9D9')
    WHITE       = colors.white
    LIGHT_GREY  = colors.HexColor('#F2F2F2')

    bold_center = dict(fontName='Helvetica-Bold', fontSize=7, alignment=TA_CENTER)
    bold_left   = dict(fontName='Helvetica-Bold', fontSize=7, alignment=TA_LEFT)
    norm_center = dict(fontName='Helvetica',      fontSize=7, alignment=TA_CENTER)
    norm_left   = dict(fontName='Helvetica',      fontSize=7, alignment=TA_LEFT)

    def P(text, **kwargs):
        style = styles['Normal'].clone('tmp')
        for k, v in kwargs.items():
            setattr(style, k, v)
        return Paragraph(str(text), style)

    table_data = []

    # Row 0 — title
    title_text = f"Supply Sheet No: {sheet_number}"
    title_cell = P(title_text, **bold_center)
    table_data.append([title_cell] + [''] * (n_cols - 1))

    # Row 1 — date / driver / approved
    date_label = P(today_str, **bold_center)
    driver_lbl = P('Driver: ____________________________', **bold_left)
    approv_lbl = P('Approved by: ____________________________', **bold_left)
    seg1  = 2            # date spans first 2 cols
    seg2  = n_cols - 4   # driver spans middle
    seg3  = 2            # approved spans last 2
    row1  = [date_label] + [''] * (seg1 - 1) + [driver_lbl] + [''] * (seg2 - 1) + [approv_lbl] + ['']
    table_data.append(row1[:n_cols])

    # Row 2 — "DESCRIPTION OIL IN PCS" spanning oil columns (if any)
    if oil_labels:
        oil_header_row = [''] * n_cols
        oil_start = len(FIXED_COLS)
        oil_header_row[oil_start] = P('DESCRIPTION OIL IN PCS', **bold_center)
        table_data.append(oil_header_row)
    else:
        table_data.append([''] * n_cols)

    # Row 3 — column headers
    col_header_row = [P(c, **bold_center) for c in all_columns]
    table_data.append(col_header_row)

    # Data rows
    total_value = 0.0
    total_cases = 0
    oil_totals  = {lbl: 0 for lbl in oil_labels}

    for i, r in enumerate(rows):
        inv_date = r['invoice_date']
        if isinstance(inv_date, datetime):
            inv_date_str = inv_date.strftime('%d-%m-%y')
        elif inv_date:
            inv_date_str = str(inv_date)[:10]
        else:
            inv_date_str = ''

        inv_val   = r['invoice_value']
        box_cnt   = r['box_count']
        total_value += inv_val
        total_cases += box_cnt

        data_row = [
            P(r['invoice_number'],    **norm_center),
            P(r['original_order_id'], **norm_center),
            P(r['order_type'],        **norm_center),
            P(r['dealer_name'],       **norm_left),
            P(r['town'],              **norm_center),
            P(f"{inv_val:,.0f}",      **norm_center),
            P(str(box_cnt) if box_cnt else '-', **norm_center),
        ]
        for lbl in oil_labels:
            qty = r['oil_products'].get(lbl, '')
            oil_totals[lbl] += qty if isinstance(qty, int) else 0
            data_row.append(P(str(qty) if qty else '', **norm_center))
        data_row.append(P(inv_date_str, **norm_center))

        table_data.append(data_row)

    # Total row
    total_row = [P('', **bold_center)] * n_cols
    total_row[4] = P('TOTAL', **bold_center)
    total_row[5] = P(f"{total_value:,.0f}", **bold_center)
    total_row[6] = P(str(total_cases), **bold_center)
    for j, lbl in enumerate(oil_labels):
        t = oil_totals[lbl]
        total_row[7 + j] = P(str(t) if t else '0', **bold_center)
    table_data.append(total_row)

    # ── Column widths ─────────────────────────────────────────────────────
    # Landscape A4: ~277 mm usable (297 - 20 mm margins).
    # Hard constraint: every column must fit on one page width.
    # When there are many dynamic oil columns the widths are scaled down
    # proportionally — narrow columns wrap their text (Paragraph cells grow
    # taller) instead of overflowing the page horizontally.
    page_w_mm = (landscape(A4)[0] - 20 * mm) / mm

    # Preferred widths (mm) — used when there is enough room
    pref_fixed = [28, 42, 20, 38, 22, 22, 14]    # Invoice No … Cases
    pref_trail = [20]                              # Invoice Date
    pref_oil   = 20                                # per oil product column

    n_oil           = len(oil_labels)
    total_preferred = sum(pref_fixed) + sum(pref_trail) + n_oil * pref_oil

    # Always scale to exactly fill the full page width — stretches when there
    # is spare room, shrinks (with text wrapping) when columns are many.
    scale   = page_w_mm / total_preferred
    fixed_w = [w * scale for w in pref_fixed]
    trail_w = [w * scale for w in pref_trail]
    oil_w   = [pref_oil * scale] * n_oil

    col_widths = [(w * mm) for w in fixed_w + oil_w + trail_w]

    # ── Build Table ───────────────────────────────────────────────────────
    t = Table(table_data, colWidths=col_widths, repeatRows=4)

    n_data  = len(rows)

    style_cmds = [
        # Grid
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.grey),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),

        # Title row (row 0) — spans full width, blue bg
        ('SPAN',        (0, 0), (-1, 0)),
        ('BACKGROUND',  (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR',   (0, 0), (-1, 0), WHITE),
        ('FONTSIZE',    (0, 0), (-1, 0), 9),
        ('TOPPADDING',  (0, 0), (-1, 0), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),

        # Date/driver row (row 1)
        ('SPAN',        (0, 1), (seg1 - 1, 1)),
        ('SPAN',        (seg1, 1), (seg1 + seg2 - 1, 1)),
        ('SPAN',        (seg1 + seg2, 1), (n_cols - 1, 1)),
        ('BACKGROUND',  (0, 1), (-1, 1), SUBHDR_BG),

        # "DESCRIPTION OIL IN PCS" row (row 2)
        ('BACKGROUND',  (0, 2), (-1, 2), SUBHDR_BG),

        # Column header row (row 3)
        ('BACKGROUND',  (0, 3), (-1, 3), HEADER_BG),
        ('TEXTCOLOR',   (0, 3), (-1, 3), WHITE),
        ('FONTSIZE',    (0, 3), (-1, 3), 7),
        ('WORDWRAP',    (0, 3), (-1, 3), True),

        # Total row (last)
        ('BACKGROUND',  (0, -1), (-1, -1), TOTAL_BG),
        ('FONTNAME',    (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]

    # Oil columns header span + green background (row 2)
    if oil_labels:
        oil_s = len(FIXED_COLS)
        oil_e = oil_s + len(oil_labels) - 1
        style_cmds += [
            ('SPAN',       (oil_s, 2), (oil_e, 2)),
            ('BACKGROUND', (oil_s, 2), (oil_e, 2), OIL_BG),
            ('TEXTCOLOR',  (oil_s, 2), (oil_e, 2), WHITE),
        ]

    # Alternating row background for data rows (rows 4 .. 4+n_data-1)
    for i in range(n_data):
        if i % 2 != 0:
            style_cmds.append(
                ('BACKGROUND', (0, 4 + i), (-1, 4 + i), LIGHT_GREY)
            )

    t.setStyle(TableStyle(style_cmds))

    # ── Build document ────────────────────────────────────────────────────
    elements = [t]
    doc.build(elements)

    return buf.getvalue()
