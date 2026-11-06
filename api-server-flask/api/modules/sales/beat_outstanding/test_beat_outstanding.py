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
