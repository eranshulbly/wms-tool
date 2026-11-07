# -*- encoding: utf-8 -*-
"""PO exports.

  order_book_xlsx   the "Final PO" sheet of [Internal] Order Book — same columns, the two
                    discounts in F1 / G1 and live formulas, so it can still be edited in
                    Excel — plus a Scheme Summary sheet
  dms_order_csv     the DMS's secondary/primary order upload file — one row per SKU, so
                    the PO can be placed in the DMS as a primary order
"""

import csv
import io
from datetime import datetime

import xlsxwriter

from api.modules.procurement.po_builder.pricing import _scheme_sort_key


class ExportError(ValueError):
    pass


_OB_HEADERS = ['S.No', 'Segment', 'Sub-segment', 'SKU Code', 'Finish', 'MRP', 'DTR Basic',
               'Discount Amount', 'Scheme %', 'Final Landing', 'Qty', 'Amount before scheme',
               'Final Amount', 'Remarks']
_OB_WIDTHS = [7, 30, 38, 22, 9, 11, 11, 14, 10, 12, 9, 14, 12, 24]


def _sorted_lines(lines):
    return sorted(lines, key=lambda l: (l['category'] or '~', l['sku_code']))


def order_book_xlsx(view):
    po, settings = view['po'], view['settings']
    lines = [l for l in _sorted_lines(view['lines']) if l['qty'] > 0]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {'in_memory': True})
    bold = wb.add_format({'bold': True, 'bg_color': '#DDEBF7', 'border': 1, 'text_wrap': True,
                          'valign': 'vcenter'})
    pct_in = wb.add_format({'num_format': '0.0%', 'bold': True, 'bg_color': '#FFF2CC'})
    money = wb.add_format({'num_format': '#,##0.00'})
    pct = wb.add_format({'num_format': '0%'})
    whole = wb.add_format({'num_format': '#,##0'})

    ws = wb.add_worksheet('Final PO')
    for i, w in enumerate(_OB_WIDTHS):
        ws.set_column(i, i, w)
    ws.write(0, 0, f"{po['po_no']}  {po['po_date']}  {po['title'] or ''}".strip())
    ws.write_number(0, 5, settings['dtr_discount_pct'] / 100.0, pct_in)
    ws.write_number(0, 6, settings['std_discount_pct'] / 100.0, pct_in)
    for c, h in enumerate(_OB_HEADERS):
        ws.write(1, c, h, bold)
    ws.freeze_panes(2, 0)

    for i, l in enumerate(lines):
        r = i + 2
        x = r + 1  # Excel row number
        ws.write_number(r, 0, i + 1)
        ws.write(r, 1, l['category'])
        ws.write(r, 2, '')
        ws.write(r, 3, l['sku_code'])
        ws.write(r, 4, l['finish'])
        ws.write_number(r, 5, l['mrp'], money)
        ws.write_formula(r, 6, f'=F{x}*(1-$F$1)', money, l['dtr_basic'])
        ws.write_formula(r, 7, f'=G{x}*(1-$G$1)', money, l['after_std'])
        ws.write_number(r, 8, l['scheme_pct'] / 100.0, pct)
        ws.write_formula(r, 9, f'=H{x}*(1-I{x})', money, l['landing'])
        ws.write_number(r, 10, l['qty'], whole)
        ws.write_formula(r, 11, f'=H{x}*K{x}', whole, l['pre_scheme_value'])
        ws.write_formula(r, 12, f'=K{x}*J{x}', whole, l['line_value'])
        ws.write(r, 13, po['remarks'] or '')

    _summary_sheet(wb, view, bold, money, whole)
    wb.close()
    return buf.getvalue()


def _summary_sheet(wb, view, bold, money, whole):
    ws = wb.add_worksheet('Scheme Summary')
    pctf = wb.add_format({'num_format': '0.0"%"'})
    widths = [10, 60, 8, 14, 10, 9, 14, 14, 8, 14]
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)
    po = view['po']
    scheme = po.get('scheme')
    ws.write(0, 0, f"{po['po_no']} — scheme: {scheme['name'] if scheme else 'none active on PO date'}")
    heads = ['Scheme', 'Group', 'Basis', 'Total', 'Slab', 'Scheme %', 'Next slab at', 'Gap to next',
             'Lines', 'Value (₹)']
    for c, h in enumerate(heads):
        ws.write(2, c, h, bold)
    r = 3
    for g in sorted(view['summary']['groups'], key=lambda g: _scheme_sort_key(g['scheme_no'])):
        ws.write(r, 0, g['scheme_no'])
        ws.write(r, 1, g['name'])
        ws.write(r, 2, 'Qty' if g['basis'] == 'QTY' else 'Value')
        ws.write_number(r, 3, g['total'], whole if g['basis'] == 'QTY' else money)
        ws.write(r, 4, f"{g['slab_no']} of {g['slab_count']}" if g['slab_no'] else 'Below slab 1')
        ws.write_number(r, 5, g['scheme_pct'], pctf)
        if g['next_threshold'] is not None:
            ws.write_number(r, 6, g['next_threshold'], whole)
            ws.write_number(r, 7, g['gap'], whole if g['basis'] == 'QTY' else money)
        else:
            ws.write(r, 6, 'Top slab')
        ws.write_number(r, 8, g['line_count'])
        ws.write_number(r, 9, g['value'], money)
        r += 1
    t = view['summary']['totals']
    r += 1
    for label, v in (('Lines', t['line_count']), ('Value before scheme', t['pre_scheme_value']),
                     ('Scheme saving', t['scheme_saving']), ('Value (pre-GST)', t['value']),
                     ('GST (IGST)', t['gst']), ('Grand total', t['grand_total'])):
        ws.write(r, 1, label, bold)
        ws.write_number(r, 3, v, money)
        r += 1


# The DMS order upload template, column for column (upload-secondary-and-primary-order-final.csv).
# Starred columns are mandatory in the DMS; everything not filled below is left blank, as in
# the template the DMS hands out.
DMS_ORDER_HEADERS = [
    '*fordate(dd-mm-yyyy)', 'user_id', '*outlet_id', '*warehouse_id', '*skunit_id',
    'Quantity(case)', 'Quantity(units)', '*Auto Scheme Apply', 'unitprice', 'po_number',
    'po_deliveryTime(dd-mm-yyyy)', '*primaryorder', 'additional_warehouse_tax_amount',
    'additional_warehouse_tax_percentage', 'cashback_redeem_type', 'cashback_redeemed',
    'cashback_value', 'createdby_userid', 'credit_limit_type_id', 'credit_limit_value_id',
    'currency_conversion_rate_id', 'delivery_status', 'deliveryshift_id', 'is_bnpl',
    'maxcashback_value', 'order_classification', 'order_source', 'parent_order_id',
    'retailer_source', 'retailer_user_id', 'service_tax', 'service_tax_percent', 'shipment_date',
    'shippingfromoutlet_id', 'vbdistype', 'vdiscount', 'vehicle_id', 'SKU name', 'Delivery Date',
]


def dms_order_csv(view, dms):
    """The PO as a DMS primary order: dated the PO date, quantities in units (cases 0),
    the DMS applying its own schemes. `dms` holds the user / outlet / warehouse ids from
    PO Builder settings.

    Raises ExportError when an id is not set, or when a line's SKU has no DMS Sku_Id in
    the master — the DMS keys the order on that id, so the line could not be placed.
    """
    missing = [label for key, label in (('dms_user_id', 'DMS user id'),
                                        ('dms_outlet_id', 'DMS outlet id'),
                                        ('dms_warehouse_id', 'DMS warehouse id')) if not dms.get(key)]
    if missing:
        raise ExportError(f"Set the {', '.join(missing)} in PO Builder → Settings first.")
    lines = [l for l in _sorted_lines(view['lines']) if l['qty'] > 0]
    if not lines:
        raise ExportError('The PO has no quantities to order.')
    no_id = [l['sku_code'] for l in lines if not l.get('dms_sku_id')]
    if no_id:
        shown = ', '.join(no_id[:10]) + (f' and {len(no_id) - 10} more' if len(no_id) > 10 else '')
        raise ExportError(f'{len(no_id)} SKU(s) have no DMS Sku_Id in the SKU master: {shown}.')

    for_date = datetime.strptime(view['po']['po_date'][:10], '%Y-%m-%d').strftime('%d-%m-%Y')
    buf = io.StringIO()
    # Windows line endings (\r\n), byte for byte like the DMS's own template.
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(DMS_ORDER_HEADERS)
    for l in lines:
        qty = l['qty']
        row = {
            '*fordate(dd-mm-yyyy)': for_date,
            'user_id': dms['dms_user_id'],
            '*outlet_id': dms['dms_outlet_id'],
            '*warehouse_id': dms['dms_warehouse_id'],
            '*skunit_id': l['dms_sku_id'],
            'Quantity(case)': 0,
            'Quantity(units)': int(qty) if float(qty).is_integer() else qty,
            '*Auto Scheme Apply': 1,
            '*primaryorder': 1,
        }
        w.writerow([row.get(h, '') for h in DMS_ORDER_HEADERS])
    return buf.getvalue()
