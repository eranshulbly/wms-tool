# -*- encoding: utf-8 -*-
"""Excel export of Analytics → Inventory Report → By Category.

The page sends the rows it is showing — already filtered and sorted — so the file is
exactly the view on screen. Nothing is read from or written to the database here.

  One sheet, "In-stock SKUs": Category | SKU Code | SKU Description | Qty, Excel filters
  on every column, header frozen, total at the foot.
"""

import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

MAX_ROWS = 20000

HEAD_FILL = PatternFill('solid', fgColor='1F3A5F')
HEAD_FONT = Font(bold=True, color='FFFFFF')
TOTAL_FILL = PatternFill('solid', fgColor='EEF2F7')
STRIPE_FILL = PatternFill('solid', fgColor='F8FAFC')
# Indian grouping (5,13,905 / 1,23,45,678): Excel has no such built-in format, so the
# lakh and crore commas are placed by value. Whole numbers only — no trailing '.'.
QTY_FORMAT = r'[>=10000000]##\,##\,##\,##0;[>=100000]##\,##\,##0;##,##0'
THIN = Side(style='thin', color='D9DEE5')


class ExportError(ValueError):
    pass


def clean_rows(rows):
    """[{category, sku_code, description, qty}] from the request body, or ExportError."""
    if not isinstance(rows, list):
        raise ExportError('Nothing to export.')
    if len(rows) > MAX_ROWS:
        raise ExportError(f'Too many rows to export ({len(rows):,}); narrow the filters.')
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            qty = float(r.get('qty') or 0)
        except (TypeError, ValueError):
            qty = 0.0
        out.append({'category': str(r.get('category') or '')[:128],
                    'sku_code': str(r.get('sku_code') or '')[:128],
                    'description': str(r.get('description') or '')[:500],
                    'qty': int(qty) if qty.is_integer() else qty})
    if not out:
        raise ExportError('Nothing to export.')
    return out


def _text(cell, value):
    """Write `value` as text. A string starting with '=' would otherwise be stored as a
    formula; SKU names come from supplier files, so never let one become one."""
    cell.value = value
    if isinstance(value, str) and value.startswith('='):
        cell.data_type = 's'
    return cell


def _title(ws, title, width):
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    return 3  # header row: the title, then one blank row


def _header(ws, row, labels):
    for col, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=col, value=label)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal='right' if label == 'Qty' else 'left', vertical='center')
    ws.row_dimensions[row].height = 20


def build_workbook(rows):
    """The .xlsx bytes for `rows` (clean_rows output)."""
    wb = Workbook()

    ws = wb.active
    ws.title = 'In-stock SKUs'
    labels = ['Category', 'SKU Code', 'SKU Description', 'Qty']
    head = _title(ws, 'In-stock SKUs by Category', len(labels))
    _header(ws, head, labels)
    for i, r in enumerate(rows, start=1):
        n = head + i
        for col, key in enumerate(('category', 'sku_code', 'description'), start=1):
            _text(ws.cell(row=n, column=col), r[key])
        ws.cell(row=n, column=4, value=r['qty']).number_format = QTY_FORMAT
        if i % 2 == 0:
            for col in range(1, 5):
                ws.cell(row=n, column=col).fill = STRIPE_FILL
    last = head + len(rows)
    total = last + 1
    ws.cell(row=total, column=1, value=f'Total · {len(rows):,} SKUs')
    ws.cell(row=total, column=4, value=f'=SUBTOTAL(9,D{head + 1}:D{last})').number_format = QTY_FORMAT
    for col in range(1, 5):
        c = ws.cell(row=total, column=col)
        c.font, c.fill, c.border = Font(bold=True), TOTAL_FILL, Border(top=THIN)
    ws.auto_filter.ref = f'A{head}:D{last}'
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    for col, width in zip('ABCD', (26, 24, 60, 12)):
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

