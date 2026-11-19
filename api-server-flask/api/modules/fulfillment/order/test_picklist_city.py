# -*- encoding: utf-8 -*-
"""The picklist's City: by the order's GSTIN in the DMS Outlet Master — no database."""

from api.modules.fulfillment.order import picklist
from api.modules.sales.beat_outstanding import schema


class _DB:
    """bo_outlet rows; answers the one GROUP BY … HAVING COUNT(*) = 1 query."""

    def __init__(self, outlets):
        self.outlets = outlets

    def execute_query(self, sql, args=()):
        company_id, gstins = args[0], set(args[1:])
        hits = {}
        for o in self.outlets:
            if o['company_id'] == company_id and o['gstin'] in gstins:
                hits.setdefault(o['gstin'], []).append(o['city'])
        return [{'gstin': g, 'city': c[0]} for g, c in hits.items() if len(c) == 1]


def test_city_only_when_exactly_one_outlet_has_the_gstin(monkeypatch):
    monkeypatch.setattr(schema, '_GSTIN_READY', True)
    monkeypatch.setattr(picklist, 'mysql_manager', _DB([
        {'company_id': 1, 'gstin': '09AKSPM2006J1ZX', 'city': 'Bareilly'},
        {'company_id': 1, 'gstin': '09AGMPD6183D1ZC', 'city': 'Moradabad'},   # two outlets,
        {'company_id': 1, 'gstin': '09AGMPD6183D1ZC', 'city': 'Moradabad'},   # same GST
        {'company_id': 2, 'gstin': '05ATUPC1091Q1Z6', 'city': 'Haldwani'},    # other company
    ]))
    orders = [
        {'potential_order_id': 1, 'company_id': 1, 'purchaser_sap_code': ' 09akspm2006j1zx'},
        {'potential_order_id': 2, 'company_id': 1, 'purchaser_sap_code': '09AGMPD6183D1ZC'},
        {'potential_order_id': 3, 'company_id': 1, 'purchaser_sap_code': '05ATUPC1091Q1Z6'},
        {'potential_order_id': 4, 'company_id': 1, 'purchaser_sap_code': ''},
        {'potential_order_id': 5, 'company_id': 1, 'purchaser_sap_code': '09ZZZZZ0000Z1ZZ'},
    ]
    assert picklist._city_by_gstin(orders) == {1: 'Bareilly'}


def test_no_lookup_when_no_order_has_a_gstin(monkeypatch):
    monkeypatch.setattr(picklist, 'mysql_manager', None)   # would fail if queried
    assert picklist._city_by_gstin([{'potential_order_id': 1, 'company_id': 1, 'purchaser_sap_code': None}]) == {}
