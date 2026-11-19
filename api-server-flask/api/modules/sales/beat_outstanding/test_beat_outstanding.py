# -*- encoding: utf-8 -*-
"""Tests for the Beat Outstanding rules and parsers — no database."""

import io
from datetime import date

import pytest

from api.modules.sales.beat_outstanding import parser as P
from api.modules.sales.beat_outstanding import rules as R


def _o(name, beat_id, beat_name='B', city=''):
    return {'outlet_name': name, 'name_key': P.name_key(name), 'beat_id': beat_id,
            'beat_name': beat_name, 'city': city}


def _b(party, amount, due=date(2026, 9, 14), ref='INV-1'):
    return {'party_name': party, 'name_key': P.name_key(party), 'bill_date': due,
            'ref_no': ref, 'amount': amount, 'due_on': due}


def test_name_key_ignores_prefix_case_ampersand_and_spacing():
    assert P.name_key('M/S UPKAR  HARDWARE  STORE') == P.name_key('m/s. Upkar Hardware Store')
    assert P.name_key('M/S RAM GLASS & PLYWOOD') == 'RAM GLASS AND PLYWOOD'


def test_party_on_one_beat_is_placed():
    placed, unplaced = R.place_parties([_b('SASTHI PLYWOOD', 100)],
                                       [_o('SASTHI PLYWOOD', '1318', 'Anmol_BAREILLY', 'Bareilly')])
    assert placed[P.name_key('SASTHI PLYWOOD')]['beat_id'] == '1318' and unplaced == []


def test_party_on_two_beats_is_not_guessed():
    placed, unplaced = R.place_parties([_b('KRISHNA HARDWARE', 100)],
                                       [_o('KRISHNA HARDWARE', '1'), _o('Krishna Hardware', '2')])
    assert placed == {} and unplaced[0]['reason'] == R.REASON_AMBIGUOUS


def test_party_missing_from_master_is_reported():
    _, unplaced = R.place_parties([_b('Anand Enterprises', 25590)], [_o('Other', '1')])
    assert [(u['party_name'], u['amount'], u['reason']) for u in unplaced] == \
        [('Anand Enterprises', 25590, R.REASON_NOT_IN_MASTER)]


def test_dealers_on_only_the_given_beats_worst_first():
    bills = [_b('A', 100, date(2026, 10, 1)), _b('B', 500, date(2026, 10, 10)),
             _b('C', 900, date(2026, 9, 1))]
    outlets = [_o('A', '1'), _o('B', '1'), _o('C', '2')]
    placed, _ = R.place_parties(bills, outlets)
    out = R.dealers_on(['1'], bills, placed, today=date(2026, 11, 4))
    assert [(d['party_name'], d['max_days_overdue']) for d in out] == [('A', 34), ('B', 25)]


def test_executives_group_their_beats():
    plan = [{'user_id': '177', 'se_name': 'Nitesh', 'beat_id': '1', 'beat_name': 'X'},
            {'user_id': '177', 'se_name': 'Nitesh', 'beat_id': '2', 'beat_name': 'Y'}]
    assert [len(e['beats']) for e in R.executives_on(plan)] == [2]


def _tally(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_tally_bills_receivable_layout():
    buf = _tally([
        ['Ebco Anmol Associates'], ['Bills Receivable'], ['1-Apr-26 to 17-Oct-26'],
        ['Date', 'Ref. No.', "Party's Name", 'Pending', 'Due on', 'Overdue'],
        ['', '', '', 'Amount', '', 'by days'],
        [None, '', 'Anand Enterprises', None, None, ''],
        [date(2026, 9, 14), '26-27-EB-INV-20', '', 25590, date(2026, 9, 14), '33'],
        [None, '', '', 25590, None, ''],
        [None, '', '', 25590, '', ''],
    ])
    tables, warnings, meta = P.parse(P.FEED_OUTSTANDING, buf, 'os.xlsx')
    assert meta['distributor'] == 'Ebco Anmol Associates'
    assert meta['report_to'] == date(2026, 10, 17)
    assert [(b['party_name'], b['ref_no'], b['amount']) for b in tables['bills']] == \
        [('Anand Enterprises', '26-27-EB-INV-20', 25590)]
    assert warnings == []


def test_tally_total_mismatch_is_warned():
    buf = _tally([
        ['Dist'], ['Date', 'Ref. No.', "Party's Name", 'Pending', 'Due on'],
        [None, '', 'A', None, None],
        [date(2026, 9, 14), 'R1', '', 10, date(2026, 9, 14)],
        [None, '', '', 99, None],
    ])
    _, warnings, _ = P.parse(P.FEED_OUTSTANDING, buf, 'os.xlsx')
    assert any('report total' in w for w in warnings)


def test_beat_plan_in_outlet_slot_is_refused():
    csv = b'"UserID","SEName","Date","Day","BeatId","BeatName","Total_Outlets"\n"1","N","2026-11-04","Wed","1318","B","5"\n'
    with pytest.raises(P.ParseError):
        P.parse(P.FEED_OUTLETS, io.BytesIO(csv), 'plan.csv')


def test_beat_plan_rows():
    csv = b'"UserID","SEName","Date","Day","BeatId","BeatName","Total_Outlets"\n"177","Nitesh Massey","2026-11-04","Wednesday","1316","Anmol_UDHAM SINGH NAGAR","32"\n'
    tables, _, _ = P.parse(P.FEED_BEAT_PLAN, io.BytesIO(csv), 'plan.csv')
    r = tables['beat_plan'][0]
    assert (r['se_name'], r['plan_date'], r['beat_id'], r['total_outlets']) == \
        ('Nitesh Massey', date(2026, 11, 4), '1316', 32)


def test_mapped_beats_match_by_name_without_case_or_spacing():
    outlets = [_o('A', '1318', 'Anmol_BAREILLY'), _o('B', '1309', 'Anmol_PILIBHIT'), _o('C', '1316', 'Anmol_Agra')]
    assert R.beat_ids_named([' anmol_bareilly', 'Anmol_Pilibhit '], outlets) == {'1318', '1309'}


def test_cd_sheet_keeps_unpaid_bills_20_days_or_more_old():
    today = date(2026, 11, 7)
    outlets = [_o('SASTHI PLYWOOD', '1318', 'Anmol_BAREILLY')]
    bills = [_b('SASTHI PLYWOOD', 100, date(2026, 10, 17), 'INV-21'),   # 21 days — lapsed
             _b('SASTHI PLYWOOD', 50, date(2026, 10, 18), 'INV-20'),    # 20 days — lapsed
             _b('SASTHI PLYWOOD', 40, date(2026, 10, 19), 'INV-19'),    # 19 days — still in CD
             _b('SASTHI PLYWOOD', -30, date(2026, 9, 1), 'CR-1')]       # a credit: pays the oldest bill
    placed, _ = R.place_parties(bills, outlets)
    cd = R.cd_lapsed(R.dealers_on({'1318'}, bills, placed, today), today)
    assert [(b['ref_no'], b['amount']) for b in cd[0]['bills']] == [('INV-21', 70), ('INV-20', 50)]
    assert cd[0]['amount'] == 120 and cd[0]['max_days_since_bill'] == 21


def test_cd_sheet_drops_dealers_with_nothing_lapsed():
    today = date(2026, 11, 7)
    bills = [_b('SASTHI PLYWOOD', 100, date(2026, 11, 1))]
    placed, _ = R.place_parties(bills, [_o('SASTHI PLYWOOD', '1318', 'Anmol_BAREILLY')])
    assert R.cd_lapsed(R.dealers_on({'1318'}, bills, placed, today), today) == []


def test_exec_beats_file_needs_user_and_beat_and_drops_repeats():
    csv_bytes = b'User,Beat\nNitesh Massey,Anmol_HAPUR\nnitesh massey,anmol_hapur\nKamlesh Kumar,\n,Anmol_Agra\nArun Dixit,Anmol_Agra\n'
    rows, warnings = P.parse_exec_beats(csv_bytes, 'map.csv')
    assert rows == [{'se_name': 'Nitesh Massey', 'beat_name': 'Anmol_HAPUR'},
                    {'se_name': 'Arun Dixit', 'beat_name': 'Anmol_Agra'}]
    assert len(warnings) == 2
    with pytest.raises(P.ParseError):
        P.parse_exec_beats(b'Name,Town\nA,B\n', 'map.csv')


def test_exec_beats_file_accepts_the_dms_beat_plan_headers():
    rows, _ = P.parse_exec_beats(b'UserID,SEName,BeatName\n177,Nitesh Massey,Anmol_HAPUR\n', 'plan.csv')
    assert rows == [{'se_name': 'Nitesh Massey', 'beat_name': 'Anmol_HAPUR'}]


def test_tally_group_layout_keeps_the_exact_party_name():
    buf = _tally([
        ['Group :', 'Ebco Debtors', None, '1-Apr-26 to 6-Nov-26'],
        ['Details of:', 'Pending Bills'],
        ['Date', 'Ref. No.', "Party's Name", 'Opening', 'Pending', 'Due on', 'Overdue'],
        ['', '', '', 'Amount', 'Amount', '', 'by days'],
        [None, '', 'Aggarwal Matal & Hardware | Ebco | Meerut', None, None, None, ''],
        [date(2026, 9, 10), '26-27-EB-INV-7', '', 9930, 9930, date(2026, 9, 10), '57'],
        [None, '', '', 9930, 9930, None, ''],
    ])
    tables, _, meta = P.parse(P.FEED_OUTSTANDING, buf, 'os.xlsx')
    assert meta['distributor'] == 'Ebco Debtors'
    assert meta['report_to'] == date(2026, 11, 6)
    b = tables['bills'][0]
    assert b['opening'] == 9930
    assert b['party_name'] == 'Aggarwal Matal & Hardware | Ebco | Meerut'
    assert b['name_key'] == P.name_key('Aggarwal Matal & Hardware')


def test_unassigned_dealers_are_those_no_executive_covers():
    today = date(2026, 11, 14)
    outlets = [_o('OWNED', '1', 'Anmol_BAREILLY'), _o('FREE', '2', 'Anmol_Agra')]
    bills = [_b('OWNED', 10), _b('FREE', 20, ref='F1'), _b('STRANGER', 30, ref='S1')]
    placed, unplaced = R.place_parties(bills, outlets)
    out = R.unassigned_dealers(bills, placed, unplaced, {'1'}, today)
    assert [(d['party_name'], d['reason'], d['beat_name']) for d in out] == [
        ('FREE', R.REASON_BEAT_UNOWNED, 'Anmol_Agra'),
        ('STRANGER', R.REASON_NOT_IN_MASTER, '')]


def test_cd_sheet_sets_credits_against_the_oldest_bills():
    """Sasthi Plywood: ₹50,000 on account (receipt 4637, a Cr line) pays INV-6 down to ₹8,050;
    the CD sheet shows what is left, adding up to the party's balance."""
    today = date(2026, 11, 18)
    p = 'Sasthi Plywood | Ebco | Jogi Navada'
    bills = [_b(p, 58050, date(2026, 9, 10), 'INV-6'), _b(p, 23128, date(2026, 9, 18), 'INV-30'),
             _b(p, 11399, date(2026, 10, 7), 'INV-60'), _b(p, 4375, date(2026, 10, 9), 'INV-69'),
             _b(p, 7643, date(2026, 10, 17), 'INV-89'), _b(p, -50000, date(2026, 10, 21), '4637')]
    for b in bills:
        b['name_key'] = P.name_key(p.split('|')[0])
    placed, _ = R.place_parties(bills, [_o('SASTHI PLYWOOD', '1318', 'Anmol_BAREILLY')])
    dealers = R.dealers_on({'1318'}, bills, placed, today)
    assert dealers[0]['amount'] == 54595 and dealers[0]['max_days_overdue'] == 69
    cd = R.cd_lapsed(dealers, today)
    left = {b['ref_no']: b['amount'] for b in cd[0]['bills']}
    assert left == {'INV-6': 8050, 'INV-30': 23128, 'INV-60': 11399, 'INV-69': 4375, 'INV-89': 7643}
    assert cd[0]['amount'] == 54595
    # a credit bigger than every bill leaves nothing to show and nothing overdue
    big = bills[:-1] + [_b(p, -200000, date(2026, 10, 21), '4637')]
    big[-1]['name_key'] = bills[0]['name_key']
    dealers = R.dealers_on({'1318'}, big, placed, today)
    assert R.cd_lapsed(dealers, today) == [] and dealers[0]['max_days_overdue'] is None


_OUTLET_HEAD = '"S No","Outlet Id","Outlet Name","Outlet Status","Warehouse","GST NO","Beat Id","Beat Name","City"\n'


def test_outlet_master_reads_the_dms_outlet_report_and_drops_inactive():
    csv = (_OUTLET_HEAD
           + '"1","5249","Agarwal Kitchenwares (Aligarh)","Active","Anmol Associates","\'09AOLPA4280M2ZL"," 1376 ","Anmol_Aligarh","Aligarh"\n'
           + '"2","5893","M/S AGARWAL KITCHENWARES","Inactive","Anmol Associates","","1318","Anmol_BAREILLY","Bareilly"\n'
           + '"3","7000","No Beat Store","Active","Anmol Associates","","0","","Agra"\n').encode()
    tables, warnings, _ = P.parse(P.FEED_OUTLETS, io.BytesIO(csv), 'outlets.csv')
    assert [(o['outlet_id'], o['beat_id'], o['beat_name'], o['city'], o['distributor']) for o in tables['outlets']] == \
        [('5249', '1376', 'Anmol_Aligarh', 'Aligarh', 'Anmol Associates'), ('7000', '', '', 'Agra', 'Anmol Associates')]
    assert [o['outlet_id'] for o in tables['inactive']] == ['5893']
    assert any('No Beat Store is on no beat' in w for w in warnings)
    assert any('1 Inactive outlet(s) not kept' in w for w in warnings)


def test_old_outlet_master_layout_is_refused():
    csv = b'"Outlet_Id","Outlet_Name","Beat_Name","Beat_ID","city"\n"5249","A","Anmol_Aligarh","1376","Aligarh"\n'
    with pytest.raises(P.ParseError, match='missing column'):
        P.parse(P.FEED_OUTLETS, io.BytesIO(csv), 'old.csv')


class _Cur:
    def __init__(self, stored):
        self.stored, self.deleted = stored, []

    def execute(self, sql, args=()):
        if sql.startswith('DELETE'):
            self.deleted += list(args)

    def fetchall(self):
        return self.stored


def test_outlet_merge_removes_outlets_now_inactive():
    from api.modules.sales.beat_outstanding import service as S
    stored = [{'id': 1, 'outlet_id': '10', 'name_key': 'A'}, {'id': 2, 'outlet_id': '11', 'name_key': 'B'},
              {'id': 3, 'outlet_id': '12', 'name_key': 'C'}]
    cur = _Cur(stored)
    merge = S._merge_outlets(cur, 1, [{'outlet_id': '10', 'name_key': 'A'}, {'outlet_id': '20', 'name_key': 'N'}],
                             [{'outlet_id': '11', 'name_key': 'B'}, {'outlet_id': '99', 'name_key': 'Z'}])
    assert sorted(cur.deleted) == [1, 2]
    assert merge == {'added': 1, 'updated': 1, 'removed': 1, 'kept': 1}


def test_outlet_master_keeps_the_gstin_without_the_dms_quote():
    csv = (_OUTLET_HEAD
           + '"1","5249","Agarwal Kitchenwares","Active","Anmol Associates","\'09aolpa4280m2zl "," 1376 ","Anmol_Aligarh","Aligarh"\n'
           + '"2","5250","No GST Store","Active","Anmol Associates","","1376","Anmol_Aligarh","Aligarh"\n').encode()
    tables, _, _ = P.parse(P.FEED_OUTLETS, io.BytesIO(csv), 'outlets.csv')
    assert [o['gstin'] for o in tables['outlets']] == ['09AOLPA4280M2ZL', '']
