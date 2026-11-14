# -*- encoding: utf-8 -*-
"""Tests for the TAT rules and the parsers — no database."""

import io
from datetime import date

import pytest

from api.modules.sales.tat_check import tat as T
from api.modules.sales.tat_check import parser as P


def _d(doc, sku, qty):
    return {'billing_doc': doc, 'sku_code': sku, 'qty': qty}


def _g(doc, sku, qty):
    return {'billing_doc': doc, 'sku_code': sku, 'qty_uploaded': qty}


def test_dispatch_without_approved_grn_is_in_transit():
    out = T.in_transit([_d('126025169', 'A', 10)], [])
    assert [(o['billing_doc'], o['qty']) for o in out] == [('126025169', 10)]


def test_approved_grn_receives_the_dispatch_line():
    assert T.in_transit([_d('126023937', 'A', 10)], [_g('126023937', 'A', 10)]) == []


def test_grn_for_another_invoice_does_not_receive_it():
    out = T.in_transit([_d('1', 'A', 10)], [_g('2', 'A', 10)])
    assert [o['qty'] for o in out] == [10]


def test_invoice_split_across_grns_is_netted():
    # One invoice, two DMS orders, only one GRN approved so far.
    out = T.in_transit([_d('1', 'A', 30)], [_g('1', 'A', 20)])
    assert [o['qty'] for o in out] == [10]


def _t(qty, eta):
    return {'qty': qty, 'eta': eta}


def test_status_is_the_nearest_bucket_with_stock():
    eta = date(2026, 11, 5)
    assert T.summarize(5, [_t(10, eta)], 40)['status'] == 'In stock'
    assert T.summarize(0, [_t(10, eta)], 40)['status'] == 'In transit'
    assert T.summarize(0, [], 40)['status'] == 'In PO'
    assert T.summarize(0, [], 0)['status'] == 'Not available'
    assert [b['qty'] for b in T.summarize(0, [_t(60, eta)], 40)['buckets']] == [0, 60, 40]


def test_expected_arrival_is_dispatch_date_plus_transit_days():
    out = T.in_transit([{**_d('1', 'A', 10), 'billing_date': date(2026, 10, 31)}], [])
    assert out[0]['eta'] == date(2026, 11, 5)


def test_transit_eta_spans_earliest_to_latest_line():
    s = T.summarize(0, [_t(5, date(2026, 11, 8)), _t(5, date(2026, 11, 5))], 0)
    transit = s['buckets'][1]
    assert (transit['eta'], transit['eta_last'], s['eta']) == (date(2026, 11, 5), date(2026, 11, 8), date(2026, 11, 5))


def test_billing_doc_strips_the_dms_order_suffix():
    assert P.billing_doc_of('126023937_16466') == '126023937'
    assert P.billing_doc_of('126024034') == '126024034'


def test_inventory_keeps_only_units():
    csv = ('"Sku_Code","Sku_Name","Units","Saleable_Stock"\n'
           '"BC4-ZY","Bed Clamp","200","8"\n').encode()
    tables, _ = P.parse(P.FEED_INVENTORY, io.BytesIO(csv), 'inv.csv')
    assert tables['inventory'] == [{'sku_code': 'BC4-ZY', 'sku_name': 'Bed Clamp', 'stock_qty': 200.0}]


def test_grn_file_in_inventory_slot_is_refused():
    csv = (','.join(P.GRN_COLS) + '\n' + ','.join(['x'] * len(P.GRN_COLS)) + '\n').encode()
    with pytest.raises(P.ParseError):
        P.parse(P.FEED_INVENTORY, io.BytesIO(csv), 'grn.csv')


def test_grn_unapproved_date_is_none():
    row = ['126025169_17244', 'MH2710016029_17244', 'A', 'Name', '4', '0', '2026-10-31', '0000-00-00']
    csv = (','.join(P.GRN_COLS) + '\n' + ','.join(row) + '\n').encode()
    tables, _ = P.parse(P.FEED_GRN, io.BytesIO(csv), 'grn.csv')
    g = tables['grn'][0]
    assert g['billing_doc'] == '126025169' and g['approved_date'] is None


_DISPATCH_HEAD = ['Profit Center', 'Billing Date', 'Billing Document', 'Doc. Reference ID',
                  'Product', 'Product', 'Sales Volume Qty']
_PENDING_HEAD = ['Plant Name', 'Order date', 'PO Number', 'Sales Document', 'Sales Document Item',
                 'Product', 'Product Description', 'Order Quantity', 'Delivered Quantity',
                 'Open Dlv Quantity']


def _workbook(**sheets):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_D_ROW = ['P1', date(2026, 11, 1), '126025169', 'R1', 'SKU1', 'Hinge', 10]
_P_ROW = ['P1', date(2026, 10, 1), 'PO1', 'SO1', '10', 'SKU2', 'Slide', 5, 2, 3]


def test_dispatch_pending_both_sheets():
    data = _workbook(DISPATCH=[_DISPATCH_HEAD, _D_ROW], PENDING=[_PENDING_HEAD, _P_ROW])
    tables, _ = P.parse_dispatch_pending(data, 'dp.xlsx')
    assert (len(tables['dispatch']), len(tables['pending'])) == (1, 1)


def test_pending_only_leaves_dispatch_out():
    tables, _ = P.parse_dispatch_pending(_workbook(PENDING=[_PENDING_HEAD, _P_ROW]), 'p.xlsx')
    assert list(tables) == ['pending'] and tables['pending'][0]['open_qty'] == 3


def test_dispatch_only_csv_is_recognised_by_columns():
    csv = (','.join(_DISPATCH_HEAD) + '\nP1,2026-11-01,126025169,R1,SKU1,Hinge,10\n').encode()
    tables, _ = P.parse_dispatch_pending(csv, 'dispatch.csv')
    assert list(tables) == ['dispatch'] and tables['dispatch'][0]['sku_name'] == 'Hinge'


def test_file_with_neither_sheet_is_refused():
    with pytest.raises(P.ParseError):
        P.parse_dispatch_pending(_workbook(Sheet1=[['a', 'b'], [1, 2]]), 'x.xlsx')


def test_stock_by_category_sums_per_category_and_keeps_unknown_codes():
    inv = [{'sku_code': 'CSQL1', 'sku_name': 'Lock', 'stock_qty': 4},
           {'sku_code': 'csql1lk', 'sku_name': 'Lock LK', 'stock_qty': 0},
           {'sku_code': 'H1', 'sku_name': 'Hinge', 'stock_qty': 10},
           {'sku_code': 'GHOST', 'sku_name': 'Unknown thing', 'stock_qty': 2}]
    master = {'CSQL1': {'category': 'FG-Furniture Locks', 'description': 'Cupboard Lock'},
              'CSQL1LK': {'category': 'FG-Furniture Locks', 'description': 'Cupboard Lock (Longer Key)'},
              'H1': {'category': 'FG-Hinges', 'description': 'Hinge 1'}}
    rows = T.stock_by_category(inv, master)
    assert [r['category'] for r in rows] == ['FG-Hinges', 'FG-Furniture Locks', T.NOT_IN_MASTER]
    locks = rows[1]
    assert (locks['skus'], locks['skus_in_stock'], locks['stock']) == (2, 1, 4)
    # only in-stock codes are listed, with the master's description
    assert locks['items'] == [{'sku_code': 'CSQL1', 'description': 'Cupboard Lock', 'qty': 4}]
    # a code the master does not know keeps the Inventory Report's name
    assert rows[2]['items'][0]['description'] == 'Unknown thing'
    assert sum(r['stock'] for r in rows) == 16


def test_esmart_digital_locks_are_reported_under_window_door_hardware():
    inv = [{'sku_code': 'ESDL2-V-FNN-BL', 'sku_name': '', 'stock_qty': 3},
           {'sku_code': 'CSQL1', 'sku_name': '', 'stock_qty': 5}]
    master = {'ESDL2-V-FNN-BL': {'category': 'FG-Furniture Locks', 'description': 'ESmart Digital Lock 2'},
              'CSQL1': {'category': 'FG-Furniture Locks', 'description': 'Cupboard Lock'}}
    rows = {r['category']: r for r in T.stock_by_category(inv, master)}
    assert [i['sku_code'] for i in rows['FG-Window, D&G Hard']['items']] == ['ESDL2-V-FNN-BL']
    assert [i['sku_code'] for i in rows['FG-Furniture Locks']['items']] == ['CSQL1']


def test_inventory_export_is_the_rows_sent_with_text_kept_as_text():
    import io as _io
    from openpyxl import load_workbook
    from api.modules.sales.tat_check import exports as X
    rows = X.clean_rows([{'category': 'FG-Hinges', 'sku_code': 'H1', 'description': '=HYPERLINK("x")', 'qty': 10},
                         {'category': 'FG-Hinges', 'sku_code': 'H2', 'description': 'Hinge', 'qty': '2.5'}])
    wb = load_workbook(_io.BytesIO(X.build_workbook(rows)))
    ws = wb['In-stock SKUs']
    data = [r for r in ws.iter_rows(values_only=True) if r[1] in ('H1', 'H2')]
    assert data == [('FG-Hinges', 'H1', '=HYPERLINK("x")', 10), ('FG-Hinges', 'H2', 'Hinge', 2.5)]
    assert ws['C4'].data_type == 's'   # a description is never a formula
    assert ws.auto_filter.ref == 'A3:D5'
    assert [ws['A1'].value, ws['A2'].value] == ['In-stock SKUs by Category', None]  # title only
    assert wb.sheetnames == ['In-stock SKUs']
    assert {ws.cell(row=r, column=4).number_format for r in (4, 5, 6)} == {X.QTY_FORMAT}
    assert '.' not in X.QTY_FORMAT  # whole numbers show as 420, not '420.'
    with pytest.raises(X.ExportError):
        X.clean_rows([])
