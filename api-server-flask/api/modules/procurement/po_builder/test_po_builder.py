# -*- encoding: utf-8 -*-
"""Unit tests for the PO Builder rules (pure modules — no DB rows are touched).

Run inside the backend container:
    python -m unittest api.modules.procurement.po_builder.test_po_builder -v
"""

import unittest

from api.modules.procurement.po_builder.matching import (
    DEFAULT_FINISH_SUFFIXES, Matcher, derive_finish, parse_suffixes)
from api.modules.procurement.po_builder.parsers import parse_list
from api.modules.procurement.po_builder.pricing import price_po, slab_for

SETTINGS = {'dtr_discount_pct': 51.2, 'std_discount_pct': 12}
QTY_GROUP = {'id': 1, 'scheme_no': 'SG67', 'name': 'Qty group', 'basis': 'QTY', 'slabs': [
    {'slab_no': 1, 'min_threshold': 175, 'discount_pct': 3},
    {'slab_no': 2, 'min_threshold': 350, 'discount_pct': 5},
    {'slab_no': 3, 'min_threshold': 700, 'discount_pct': 7}]}
VALUE_GROUP = {'id': 2, 'scheme_no': 'SG35', 'name': 'Value group', 'basis': 'VALUE', 'slabs': [
    {'slab_no': 1, 'min_threshold': 52500, 'discount_pct': 3},
    {'slab_no': 2, 'min_threshold': 105000, 'discount_pct': 5}]}
GROUPS = {1: QTY_GROUP, 2: VALUE_GROUP}


class PricingTest(unittest.TestCase):

    def test_price_build_up_matches_order_book_formula(self):
        # Order Book row: DP1-12-3M-AB, MRP 326, scheme 3%, qty 10
        out = price_po([{'id': 1, 'qty': 10, 'mrp': 326, 'gst_pct': 18, 'scheme_group_id': None,
                         'fixed_scheme_pct': 3}], {}, SETTINGS)['lines'][1]
        dtr = 326 * (1 - 0.512)
        self.assertAlmostEqual(out['dtr_basic'], dtr)
        self.assertAlmostEqual(out['after_std'], dtr * 0.88)
        self.assertAlmostEqual(out['landing'], dtr * 0.88 * 0.97)
        self.assertAlmostEqual(out['line_value'], dtr * 0.88 * 0.97 * 10)
        self.assertAlmostEqual(out['gst'], out['line_value'] * 0.18)

    def test_slabs_are_cumulative_within_a_group_and_never_across(self):
        lines = [{'id': 1, 'qty': 400, 'mrp': 100, 'gst_pct': 18, 'scheme_group_id': 1},
                 {'id': 2, 'qty': 300, 'mrp': 100, 'gst_pct': 18, 'scheme_group_id': 1},
                 {'id': 3, 'qty': 5000, 'mrp': 1, 'gst_pct': 18, 'scheme_group_id': 2}]
        r = price_po(lines, GROUPS, SETTINGS)
        g = {s['scheme_no']: s for s in r['groups']}
        self.assertEqual(g['SG67']['total'], 700)          # 400 + 300 together
        self.assertEqual(g['SG67']['scheme_pct'], 7)
        self.assertEqual(r['lines'][2]['scheme_pct'], 7)    # both lines get the group's %
        self.assertEqual(g['SG35']['scheme_pct'], 0)        # SG67's qty does not leak in

    def test_below_slab_one_is_zero_and_gap_is_reported(self):
        r = price_po([{'id': 1, 'qty': 680, 'mrp': 10, 'gst_pct': 18, 'scheme_group_id': 1}], GROUPS, SETTINGS)
        g = r['groups'][0]
        self.assertEqual((g['slab_no'], g['scheme_pct'], g['next_threshold'], g['gap']), (2, 5, 700, 20))
        r = price_po([{'id': 1, 'qty': 10, 'mrp': 10, 'gst_pct': 18, 'scheme_group_id': 1}], GROUPS, SETTINGS)
        self.assertEqual((r['groups'][0]['slab_no'], r['groups'][0]['scheme_pct']), (0, 0))

    def test_value_basis_uses_price_after_standard_discount(self):
        # after-std price of MRP 1000 = 1000 x 0.488 x 0.88 = 429.44; 123 units = 52,821 -> slab 1
        r = price_po([{'id': 1, 'qty': 123, 'mrp': 1000, 'gst_pct': 18, 'scheme_group_id': 2}], GROUPS, SETTINGS)
        self.assertAlmostEqual(r['groups'][0]['total'], 429.44 * 123)
        self.assertEqual(r['groups'][0]['scheme_pct'], 3)
        r = price_po([{'id': 1, 'qty': 122, 'mrp': 1000, 'gst_pct': 18, 'scheme_group_id': 2}], GROUPS, SETTINGS)
        self.assertEqual(r['groups'][0]['scheme_pct'], 0)

    def test_highest_slab_reached_wins_when_minimums_repeat(self):
        # SG17 in the Q2 FY27 file: 3% from 10, 5% from 10, 7% from 40
        slabs = [{'slab_no': 1, 'min_threshold': 10, 'discount_pct': 3},
                 {'slab_no': 2, 'min_threshold': 10, 'discount_pct': 5},
                 {'slab_no': 3, 'min_threshold': 40, 'discount_pct': 7}]
        no, pct, nxt = slab_for(10, slabs)
        self.assertEqual((no, pct, nxt['slab_no']), (2, 5, 3))


class MatchingTest(unittest.TestCase):

    def setUp(self):
        self.suffixes = parse_suffixes(DEFAULT_FINISH_SUFFIXES)
        self.m = Matcher(
            ['CDSS250-SP-ZW', 'RH35-AGP-BG', 'RH35-AGP-H-BG', 'EBS-SO2-SL', 'PWBSC45-16-20-04BR',
             'TBR40-AT', 'TBR40-BR', 'TBR40-WM', 'BPO1-45-AT', 'KMS-S-AT', 'KMS-S-WM', 'KMS-S-G-AT',
             'GSP1-4-50-3M-AS', 'GSP1-4-50-3M-AB'],
            self.suffixes, inactive_codes=['OLD-1'])

    def check(self, code, finish, status, sku=None):
        r = self.m.match(code, finish)
        self.assertEqual(r['status'], status, (code, r))
        if sku:
            self.assertEqual(r['sku_code'] or r['candidates'][0], sku)
        return r

    def test_cascade(self):
        self.check(' cdss250-sp-zw ', '', 'exact', 'CDSS250-SP-ZW')
        self.check('CDSS250-SP', 'ZW', 'finish_added', 'CDSS250-SP-ZW')
        self.check('PWBSC45-16-20-04', 'BR', 'finish_added', 'PWBSC45-16-20-04BR')
        self.check('KMS-S', 'AT (WITH WOOD)', 'finish_added', 'KMS-S-AT')
        self.check('BPO1-45', '', 'base_single', 'BPO1-45-AT')
        r = self.check('TBR40', '', 'needs_choice')
        self.assertEqual(set(r['candidates']), {'TBR40-AT', 'TBR40-BR', 'TBR40-WM'})
        r = self.check('GSP1-4-50-3M-AS/AB', '', 'needs_choice')
        self.assertEqual(set(r['candidates']), {'GSP1-4-50-3M-AS', 'GSP1-4-50-3M-AB'})
        self.check('GSP1-4-50-3M-AS/AB', 'AB', 'finish_added', 'GSP1-4-50-3M-AB')
        self.check('RH3S-AGP-BG', 'BG', 'fuzzy', 'RH35-AGP-BG')     # 5 typed as S
        self.check('EBS-S02', 'SL', 'fuzzy', 'EBS-SO2-SL')          # letter O typed as zero
        self.check('NOTHING-LIKE-IT', '', 'unmatched')
        self.assertEqual(self.m.match('OLD-1')['note'], 'Inactive in SKU master')

    def test_derive_finish(self):
        self.assertEqual(derive_finish('CDSS250-SP-ZW', self.suffixes), 'ZW')
        self.assertEqual(derive_finish('PWBSC45-16-20-04BR', self.suffixes), 'BR')
        self.assertEqual(derive_finish('HTD1-SC', self.suffixes), '')   # SC = soft close, not a finish


class ListParsingTest(unittest.TestCase):

    def test_pasted_cells_without_header_are_code_qty_optional_finish(self):
        out = parse_list(text='CDSS250-SP\t5\tZW\nRH35-SC-TN\t4\t\nBAD\tx\t\n')
        self.assertEqual([(r['code'], r['qty'], r['finish']) for r in out['rows']],
                         [('CDSS250-SP', 5, 'ZW'), ('RH35-SC-TN', 4, ''), ('BAD', 0, '')])
        two = parse_list(text='CDSS250-SP-ZW\t5\n')
        self.assertEqual([(r['code'], r['qty'], r['finish']) for r in two['rows']], [('CDSS250-SP-ZW', 5, '')])

    def test_header_prefers_the_sku_code_column(self):
        out = parse_list(text='Line,Code (as quoted),SKU Code (corrected),Finish,Qty\n1,RH3S,RH35-AGP-BG,BG,3\n')
        self.assertEqual(out['columns']['code'], 'SKU Code (corrected)')
        self.assertEqual(out['rows'][0]['code'], 'RH35-AGP-BG')


if __name__ == '__main__':
    unittest.main()
