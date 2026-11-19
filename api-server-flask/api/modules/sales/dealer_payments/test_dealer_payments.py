# -*- encoding: utf-8 -*-
"""Dealer Payment Tracker — parser and rule tests, no database.

The acceptance tests (spec section 5) run on the real sample exports. They are looked for
in $DPT_SAMPLES_DIR, then <repo>/samples, then <repo>/Cadila; tests that need a file that
is not there are skipped.
"""

import io
import os
from datetime import date, timedelta
from decimal import Decimal as D

import openpyxl
import pytest

from api.modules.sales.dealer_payments import parser as P
from api.modules.sales.dealer_payments import rules as R
from api.modules.sales.dealer_payments import cheques as C

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *(['..'] * 5)))
_DIRS = [os.environ.get('DPT_SAMPLES_DIR') or '', os.path.join(_REPO, 'samples'), os.path.join(_REPO, 'Cadila'),
         os.path.join(_REPO, 'Ebco')]


def _sample(name):
    for d in _DIRS:
        p = os.path.join(d, name)
        if d and os.path.exists(p):
            with open(p, 'rb') as f:
                return f.read()
    pytest.skip(f'sample {name} not found in {_DIRS}')


GRPBILLS, PLAIN, REGISTER = 'GrpBills.xlsx', 'CADILA 1.xlsx', 'cadilaDayBook16Nov.xlsx'
AS_OF = date(2026, 11, 17)


@pytest.fixture(scope='module')
def export1():
    return P.parse_outstanding(_sample(GRPBILLS))


@pytest.fixture(scope='module')
def register():
    return P.parse_receipt_register(_sample(REGISTER))


@pytest.fixture(scope='module')
def master(export1, register):
    """The dealers, created from the Tally uploads as the app does: Export 1, then the
    Receipt Register's parties not seen yet."""
    first = R.new_dealers([], [b['party'] for b in export1['bills']])
    return first + R.new_dealers(first, [r['party'] for r in register['receipts']])


@pytest.fixture(scope='module')
def ids(master):
    return {d['tally_ledger_name']: d['dealer_id'] for d in master}


def _with_ids(rows, ids):
    return [{**r, 'dealer_id': ids[r['party']]} for r in rows]


def _dealer(master, word):
    hits = [d for d in master if d['dealer_name'].startswith(word)]
    assert len(hits) == 1, (word, hits)
    return hits[0]


def _pay(pid, dealer_id, amount, day, status=R.OPEN, mode='BT'):
    return {'id': pid, 'dealer_id': dealer_id, 'amount': D(str(amount)), 'payment_date': day,
            'status': status, 'mode': mode}


# ── dealers, created from the Tally uploads ───────────────────────────────────

def test_dealers_keep_ledger_names_exactly(master):
    shri_ram = _dealer(master, 'Shri Ram')
    assert shri_ram['tally_ledger_name'] == 'Shri Ram Pharma  | Cadila | Chandausi'  # two spaces
    assert (shri_ram['dealer_name'], shri_ram['principal'], shri_ram['town']) == ('Shri Ram Pharma', 'Cadila', 'Chandausi')
    assert [d['dealer_id'] for d in master[:2]] == ['CAD-001', 'CAD-002']
    assert len({d['dealer_id'] for d in master}) == len(master)


def test_new_party_gets_the_next_id(master):
    last = int(master[-1]['dealer_id'][4:])
    new = R.new_dealers(master, ['Shri Ram Pharma  | Cadila | Chandausi',      # known, exactly
                                 'Shri Ram Pharma | Cadila | Chandausi',       # one space: new
                                 'Cadila Pharmaceuticals Limited | Ghaziabad'])
    assert [(d['dealer_id'], d['tally_ledger_name']) for d in new] == [
        (f'CAD-{last + 1:03d}', 'Shri Ram Pharma | Cadila | Chandausi'),
        (f'CAD-{last + 2:03d}', 'Cadila Pharmaceuticals Limited | Ghaziabad')]
    assert (new[1]['dealer_name'], new[1]['town'], new[1]['principal']) == ('Cadila Pharmaceuticals Limited', 'Ghaziabad', '')


# ── acceptance test 1: Export 1 (GrpBills, as of 17-Nov-26) ───────────────────

def test_grand_total_and_as_of(export1, ids):
    assert export1['as_of'] == AS_OF and export1['period_from'] == date(2026, 4, 1)
    assert export1['detail'] is True
    assert export1['grand_total'] == D('5195763')
    assert sum(b['pending_amt'] for b in export1['bills']) == D('5195763')
    assert all(b['party'] in ids for b in export1['bills'])   # every party is in the master
    assert export1['warnings'] == []


def test_every_dealer_matches_its_tally_subtotal(export1):
    assert export1['subtotal_checks']
    assert all(c['sum'] == c['subtotal'] for c in export1['subtotal_checks'])


def _bills(export1, word):
    return {b['ref_no']: b for b in export1['bills'] if b['party'].startswith(word)}


def _adj(export1, word, ref):
    return [(a['vch_type'], a['vch_no'], a['amount']) for a in export1['adjustments']
            if a['party'].startswith(word) and a['ref_no'] == ref]


def test_chandra_pharma(export1):
    bills = _bills(export1, 'Chandra Pharma')
    assert bills['A000021']['pending_amt'] == D('50')
    assert ('Receipt', '3458', D('-17196')) in _adj(export1, 'Chandra Pharma', 'A000021')


def test_shraddha_invoice_plus_bounce_is_a_debit(export1):
    bills = _bills(export1, 'Shraddha')
    assert bills['A000003']['pending_amt'] == D('19144')
    boo = bills['Boo 104059']
    assert boo['kind'] == P.KIND_BOUNCE and boo['pending_amt'] == D('70039')   # Dr, owed again
    assert sum(b['pending_amt'] for b in bills.values()) == D('89183')
    assert _adj(export1, 'Shraddha', 'Boo 104059') == [('Payment', '634', D('70039'))]


def test_ms_distributors_bounce(export1):
    boo = _bills(export1, 'M S Distributors')['Boo 338558']
    assert boo['pending_amt'] == D('51664') and boo['opening_amt'] == D('250000')
    assert _adj(export1, 'M S Distributors', 'Boo 338558') == [
        ('Payment', '488', D('250000')), ('Receipt', '4121', D('-198336'))]


def test_katyayani_has_no_pending_bills(export1):
    assert _bills(export1, 'Katyayani') == {}


def test_credit_notes_are_cr_and_boo_bills_are_dr(export1):
    rishika = _bills(export1, 'Rishika')
    assert rishika['CN00005']['pending_amt'] == D('-44457')
    assert rishika['CN00006']['pending_amt'] == D('-924')
    assert all(b['pending_amt'] > 0 for b in export1['bills'] if b['kind'] == P.KIND_BOUNCE)


def test_voucher_lines_are_signed_from_the_number_format(export1):
    types = {}
    for a in export1['adjustments']:
        types.setdefault(a['vch_type'], set()).add(a['amount'] > 0)
    assert types['Receipt'] == {False}                  # Cr
    assert types['CADILA Sales GST'] == {True}          # Dr
    assert types['Payment'] == {True}                   # Dr


def test_sign_comes_from_the_format_not_the_value():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws['A1'] = 5
    ws['A1'].number_format = '""0.00" Cr"'
    ws['A2'] = 5
    ws['A2'].number_format = '""0.00" Dr"'
    ws['A3'] = 5
    assert [P.signed_amount(ws[c]) for c in ('A1', 'A2', 'A3')] == [D('-5'), D('5'), D('5')]


def _tamper(data, row, col, value):
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.worksheets[0]
    ws.cell(row=row, column=col).value = value
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_bill_that_disagrees_with_its_subtotal_is_refused():
    data = _sample(GRPBILLS)
    with pytest.raises(P.ParseError, match='subtotal'):
        P.parse_outstanding(_tamper(data, 41, 8, 51))       # Chandra A000021 pending 50 -> 51


def test_plain_export_and_stray_bill():
    out = P.parse_outstanding(_sample(PLAIN))               # CADILA 1.xlsx, no voucher detail
    assert out['as_of'] == date(2026, 11, 14) and out['detail'] is False
    assert out['adjustments'] == []
    assert out['grand_total'] == D('5322594')
    assert sum(b['pending_amt'] for b in out['bills']) == D('5322594')
    a77 = [b for b in out['bills'] if b['ref_no'] == 'A000077']
    assert len(a77) == 1 and a77[0]['party'] == 'Wholesale Dawa Bazar | Cadila | Rampur'
    assert any('no party header' in w for w in out['warnings'])


# ── Export 2: Receipt Register ────────────────────────────────────────────────

def test_register(register, ids):
    assert (register['period_from'], register['period_to']) == (date(2026, 4, 1), date(2026, 11, 30))
    assert len(register['receipts']) == 45 and register['total'] == D('3026456')
    assert all(r['party'] in ids and r['vch_type'] == 'Receipt' for r in register['receipts'])
    kunj = [r for r in register['receipts'] if r['vch_no'] == '5342']
    assert kunj[0]['amount'] == D('47040') and kunj[0]['vch_date'] == date(2026, 11, 16)


# ── acceptance tests 5 and 6: window reload ───────────────────────────────────

def test_reuploading_the_same_register_adds_no_rows(register):
    rs, lo, hi = register['receipts'], register['period_from'], register['period_to']
    once = R.window_reload([], rs, lo, hi)
    twice = R.window_reload(once, rs, lo, hi)
    assert len(twice) == len(rs) == len({R.receipt_key(r) for r in twice})


def test_a_receipt_deleted_in_tally_disappears(register):
    rs, lo, hi = register['receipts'], register['period_from'], register['period_to']
    stored = R.window_reload([], rs, lo, hi)
    gone = next(r for r in rs if r['vch_no'] == '4171')
    after = R.window_reload(stored, [r for r in rs if r is not gone], lo, hi)
    assert R.receipt_key(gone) not in {R.receipt_key(r) for r in after}
    assert len(after) == len(rs) - 1


def test_receipts_outside_the_window_are_kept(register):
    old = {'vch_no': '1', 'vch_date': date(2026, 3, 31), 'amount': D('5'), 'party': 'x'}
    after = R.window_reload([old], register['receipts'], date(2026, 9, 18), date(2026, 11, 17))
    assert old in after


# ── acceptance test 2: bounces on the dealer screen ───────────────────────────

def test_boo_bills_are_labelled_on_the_dealer_screen(master, ids, export1):
    bills = _with_ids(export1['bills'], ids)
    rows = {r['dealer_id']: r for r in R.dealer_rows(master, bills, [], [], AS_OF)}
    ms, shraddha = _dealer(master, 'M S Distributors'), _dealer(master, 'Shraddha')
    assert [(b['ref_no'], b['label']) for b in rows[ms['dealer_id']]['bounces']] == [('Boo 338558', R.BOUNCE_LABEL)]
    assert [(b['ref_no'], b['label']) for b in rows[shraddha['dealer_id']]['bounces']] == [('Boo 104059', R.BOUNCE_LABEL)]
    assert rows[shraddha['dealer_id']]['tally_os'] == D('89183')
    assert R.BOUNCE_LABEL.startswith('Bounced / reversed receipt')


def test_a_logged_payment_a_boo_reverses_is_marked_bounced(master, ids, export1):
    ms = _dealer(master, 'M S Distributors')['dealer_id']
    boos = R.bounce_bills(_with_ids(export1['bills'], ids))
    pays = [_pay(1, ms, 250000, date(2026, 9, 20)),             # 2 days before Boo 338558 (22-Sep)
            _pay(2, ms, 250000, date(2026, 9, 1)),              # 21 days before: not it
            _pay(3, ms, 249000, date(2026, 9, 21))]             # amount off by 1,000
    assert R.bounced_payments(pays, boos) == {1: 'Boo 338558'}


# ── acceptance tests 3 and 4: matching ────────────────────────────────────────

def test_kunj_bt_auto_matches_receipt_5342(master, ids, register):
    kunj = _dealer(master, 'Kunj')['dealer_id']
    receipts = _with_ids(register['receipts'], ids)
    posted, ambiguous = R.match_payments([_pay(7, kunj, 47040, date(2026, 11, 16))], receipts, set())
    assert posted == {7: ('5342', date(2026, 11, 16))} and ambiguous == {}


def test_unmatched_bt_stays_open_and_goes_stale_after_5_days(master, ids, register):
    kunj = _dealer(master, 'Kunj')['dealer_id']
    receipts = _with_ids(register['receipts'], ids)
    p = _pay(8, kunj, 12345, date(2026, 11, 16))
    posted, ambiguous = R.match_payments([p], receipts, set())
    assert posted == {} and ambiguous == {}
    assert not R.is_stale(p, date(2026, 11, 21))     # 5 days after: not yet
    assert R.is_stale(p, date(2026, 11, 22))         # more than 5 days
    assert R.stale_payments([p], date(2026, 11, 22)) == [p]


def test_two_candidates_leave_the_payment_open_as_ambiguous(master, ids, register):
    chandra = _dealer(master, 'Chandra Pharma')['dealer_id']
    receipts = _with_ids(register['receipts'], ids)              # 3458 (11-Sep) and 3701 (15-Sep), 17,196
    posted, ambiguous = R.match_payments([_pay(9, chandra, 17196, date(2026, 9, 10))], receipts, set())
    assert posted == {} and ambiguous == {9: [('3458', date(2026, 9, 11)), ('3701', date(2026, 9, 15))]}


def test_a_matched_receipt_is_not_used_twice(master, ids, register):
    kunj = _dealer(master, 'Kunj')['dealer_id']
    receipts = _with_ids(register['receipts'], ids)
    posted, _ = R.match_payments([_pay(1, kunj, 47040, date(2026, 11, 15)),
                                  _pay(2, kunj, 47040, date(2026, 11, 16))], receipts, set())
    assert posted == {1: ('5342', date(2026, 11, 16))}           # oldest first; 2 stays OPEN
    posted, _ = R.match_payments([_pay(2, kunj, 47040, date(2026, 11, 16))], receipts,
                                 {('5342', date(2026, 11, 16))})
    assert posted == {}


def test_matching_window_and_tolerance():
    r = [{'vch_no': '1', 'vch_date': date(2026, 11, 10), 'dealer_id': 'X', 'amount': D('1000'), 'vch_type': 'Receipt'}]
    def hit(day, amount):
        return bool(R.match_payments([_pay(1, 'X', amount, day)], r, set())[0])
    assert hit(date(2026, 11, 12), 1000)             # receipt 2 days before the payment
    assert not hit(date(2026, 11, 13), 1000)         # 3 days before
    assert hit(date(2026, 10, 21), 1000)             # receipt 20 days after
    assert not hit(date(2026, 10, 20), 1000)         # 21 days after
    assert hit(date(2026, 11, 10), 1010) and not hit(date(2026, 11, 10), 1011)


# ── 3.3 manual-check flags ────────────────────────────────────────────────────

def test_chandra_repeat_receipts_are_a_possible_duplicate(master, ids, export1, register):
    receipts = _with_ids(register['receipts'], ids)
    boos = R.bounce_bills(_with_ids(export1['bills'], ids))
    pairs = R.possible_duplicates(receipts, boos)
    assert [(a['vch_no'], b['vch_no']) for a, b in pairs] == [('3458', '3701')]
    flags = R.manual_check_flags(duplicates=pairs)
    assert flags[0]['flag_type'] == R.FLAG_DUPLICATE and flags[0]['amounts'] == [D('17196'), D('17196')]


def test_a_bounce_between_two_receipts_is_not_a_duplicate():
    rs = [{'vch_no': '1', 'vch_date': date(2026, 10, 1), 'dealer_id': 'X', 'amount': D('5000')},
          {'vch_no': '2', 'vch_date': date(2026, 10, 5), 'dealer_id': 'X', 'amount': D('5000')}]
    boo = {'dealer_id': 'X', 'kind': P.KIND_BOUNCE, 'ref_no': 'Boo 1', 'bill_date': date(2026, 10, 3),
           'opening_amt': D('5000'), 'pending_amt': D('5000')}
    assert R.possible_duplicates(rs, [boo]) == []
    assert len(R.possible_duplicates(rs, [])) == 1
    assert R.possible_duplicates(rs, [{**boo, 'bill_date': date(2026, 10, 9)}]) != []   # not between them


def test_credit_balance_only_when_not_explained_by_credit_notes():
    def bill(dealer, ref, amount):
        return {'dealer_id': dealer, 'ref_no': ref, 'kind': P.bill_kind(ref), 'pending_amt': D(amount)}
    bills = [bill('A', 'CN00001', '-500'), bill('A', 'A000001', '100'),      # Cr, but from a credit note
             bill('B', 'A000002', '-300'),                                     # Cr with no credit note
             bill('C', 'A000003', '400')]
    assert R.credit_balances(bills) == {'B': (D('-300'), D('0'))}


def test_flags_never_change_balances(master, ids, export1, register):
    bills = _with_ids(export1['bills'], ids)
    before = R.dealer_rows(master, bills, [], [], AS_OF)
    R.manual_check_flags(duplicates=R.possible_duplicates(_with_ids(register['receipts'], ids), R.bounce_bills(bills)))
    assert R.dealer_rows(master, bills, [], [], AS_OF) == before


# ── PDCs ──────────────────────────────────────────────────────────────────────

def _chq(no, party, amount, day, status=R.HOLDING):
    return {'cheque_no': no, 'bank': 'SBI', 'party_name': party, 'amount': D(str(amount)),
            'cheque_date': day, 'status': status}


def test_cheques_map_by_cheque_system_name_else_ledger_name(master):
    dealers = [{**d, 'cheque_system_name': 'RISHIKA PHARMA'} if d['dealer_name'].startswith('Rishika') else d
               for d in master]
    kunj = _dealer(master, 'Kunj')
    mapped, unmapped, other = R.map_cheques([_chq('1', 'RISHIKA PHARMA', 10, AS_OF),
                                             _chq('2', kunj['tally_ledger_name'], 10, AS_OF),
                                             _chq('3', 'SOMEONE ELSE', 10, AS_OF)], dealers)
    assert [c['cheque_no'] for c in mapped] == ['1', '2'] and not unmapped
    assert [c['cheque_no'] for c in other] == ['3']


def test_cheques_map_by_name_as_wareops_writes_it(master):
    # names as they appear in the wareops cheque export
    mapped, unmapped, other = R.map_cheques([_chq('1', 'MS KUNJ MEDICAL AGENCY', 10, AS_OF),
                                             _chq('2', 'M/S GULATHI MEDICAL CENTRE', 10, AS_OF),
                                             _chq('3', 'RISHIKA PHARMA', 10, AS_OF),
                                             _chq('4', 'SEHGAL AUTO SPARE', 10, AS_OF)], master)
    got = {c['cheque_no']: c['dealer_id'] for c in mapped}
    assert got == {'1': _dealer(master, 'Kunj')['dealer_id'], '2': _dealer(master, 'Gulathi')['dealer_id'],
                   '3': _dealer(master, 'Rishika')['dealer_id']}
    assert not unmapped and [c['cheque_no'] for c in other] == ['4']


def test_cheque_fitting_two_dealers_goes_to_manual_check():
    two = [{'dealer_id': 'CAD-001', 'tally_ledger_name': 'Ram Pharma | Cadila | Bareilly', 'cheque_system_name': ''},
           {'dealer_id': 'CAD-002', 'tally_ledger_name': 'Ram Pharma | Cadila | Badaun', 'cheque_system_name': ''}]
    mapped, unmapped, other = R.map_cheques([_chq('1', 'RAM PHARMA', 10, AS_OF)], two)
    assert not mapped and not other and len(unmapped) == 1
    assert R.manual_check_flags(unmapped=unmapped)[0]['flag_type'] == R.FLAG_UNMAPPED_CHEQUE


def test_wareops_rows_keep_cadila_payee_and_map_statuses():
    rows = [{'cheque_number': '000963', 'cheque_date': AS_OF, 'amount': 100, 'dealer_name': 'RISHIKA PHARMA ',
             'bank_name': 'SBI', 'payee_name': 'ANMOL ASSOCIATES', 'status': s}
            for s in ('submitted', 'presented', 'passed', 'bounced', 'draft')]
    rows.append({**rows[0], 'payee_name': 'Om Marketing'})
    out = C.to_tracker(rows, 'Anmol Associates')
    assert [c['status'] for c in out] == [R.HOLDING, R.DEPOSITED, R.CLEARED, R.CHQ_BOUNCED]
    assert out[0]['party_name'] == 'RISHIKA PHARMA' and C.normalize(out)[0]['amount'] == D('100.00')


def test_stub_adapter_returns_nothing_and_normalize_checks_records():
    adapter = C.StubChequeAdapter()
    assert adapter.fetch_cheques(None) == [] and adapter.connected is False
    assert C.normalize([{'cheque_no': 9, 'bank': 'SBI', 'party_name': 'X', 'amount': '10',
                         'cheque_date': '2026-11-18', 'status': 'holding'}])[0]['status'] == R.HOLDING
    with pytest.raises(C.ChequeAdapterError):
        C.normalize([{'cheque_no': 9, 'party_name': 'X', 'amount': 1, 'cheque_date': '2026-11-18',
                      'status': 'LOST'}])


# ── 4. dealer screen actions ──────────────────────────────────────────────────

def test_actions():
    assert R.action_for(D('0'), D('0'), None) == (R.ACTION_CLEAR, None)
    assert R.action_for(D('-5'), D('0'), None) == (R.ACTION_CLEAR, None)
    assert R.action_for(D('100'), D('100'), AS_OF) == (R.ACTION_WAIT, AS_OF)
    assert R.action_for(D('100'), D('99'), AS_OF) == (R.ACTION_CHASE, None)


def test_dealer_screen_rows(master, ids, export1):
    bills = _with_ids(export1['bills'], ids)
    kunj = _dealer(master, 'Kunj')['dealer_id']                  # Tally O/S 30,859
    janta = _dealer(master, 'Janta')['dealer_id']                # 9,347
    akansh = _dealer(master, 'Akansh')['dealer_id']              # 16,436
    pays = [_pay(1, kunj, 30859, AS_OF),                         # clears Kunj
            _pay(2, akansh, 1000, AS_OF), _pay(3, akansh, 500, AS_OF, status=R.POSTED)]
    cheques = [{**_chq('1', 'x', 9347, AS_OF + timedelta(days=3)), 'dealer_id': janta},
               {**_chq('2', 'x', 99999, AS_OF, status=R.CLEARED), 'dealer_id': akansh}]
    rows = R.dealer_rows(master, bills, pays, cheques, AS_OF)
    by = {r['dealer_id']: r for r in rows}
    assert all(d['dealer_id'] in by for d in master)
    gulathi = _dealer(master, 'Gulathi')
    excluded = [{**d, 'exclude_from_chase': True} if d is gulathi else d for d in master]
    assert gulathi['dealer_id'] not in {r['dealer_id'] for r in R.dealer_rows(excluded, bills, pays, cheques, AS_OF)}
    assert by[kunj]['action'] == R.ACTION_CLEAR and by[kunj]['effective_os'] == D('0')
    assert (by[janta]['action'], by[janta]['wait_till'], by[janta]['pdc_count']) == (R.ACTION_WAIT, AS_OF + timedelta(days=3), 1)
    assert by[akansh]['received_not_in_tally'] == D('1000')       # OPEN only
    assert by[akansh]['effective_os'] == D('15436') and by[akansh]['pdc_count'] == 0   # CLEARED is not held
    # the ₹1,000 not in Tally pays off the oldest bill (₹686, 91 days): 88 days is left
    assert by[akansh]['oldest_overdue_days'] == 88
    actions = [r['action'] for r in rows]
    assert actions == sorted(actions, key={'CHASE': 0, 'WAIT': 1, 'NOT_DUE': 2, 'CLEAR': 3}.get)
    chase = [r['effective_os'] for r in rows if r['action'] == R.ACTION_CHASE]
    assert chase == sorted(chase, reverse=True)
    katyayani = [r for r in rows if r['dealer'].startswith('Katyayani')][0]
    assert (katyayani['tally_os'], katyayani['action']) == (D('0'), R.ACTION_CLEAR)


def test_pdcs_to_deposit_are_today_and_tomorrow():
    cheques = [_chq('1', 'a', 1, AS_OF - timedelta(days=1)), _chq('2', 'a', 1, AS_OF),
               _chq('3', 'a', 1, AS_OF + timedelta(days=1)), _chq('4', 'a', 1, AS_OF + timedelta(days=2)),
               _chq('5', 'a', 1, AS_OF, status=R.DEPOSITED)]
    assert [c['cheque_no'] for c in R.pdcs_to_deposit(cheques, AS_OF)] == ['2', '3']


# ── the Outstanding download ──────────────────────────────────────────────────

def test_outstanding_download_matches_tally_and_lists_every_bill(export1, master, ids):
    from api.modules.sales.dealer_payments.exports import build_outstanding_xlsx
    bills = _with_ids(export1['bills'], ids)
    kunj = _dealer(master, 'Kunj')
    pays = [{'id': 1, 'dealer_id': kunj['dealer_id'], 'status': R.OPEN, 'mode': 'BT', 'amount': D('1000'),
             'payment_date': AS_OF, 'reference': '', 'note': '', 'created_by': 'x'}]
    chq = [{**_chq('9', 'MS KUNJ MEDICAL AGENCY', 500, AS_OF + timedelta(days=5)), 'dealer_id': kunj['dealer_id']}]
    data = build_outstanding_xlsx(as_of=export1['as_of'], dealers=master, bills=bills, payments=pays, cheques=chq,
                                  bounced_cheques={}, cheques_note='test', today=AS_OF)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ['Outstanding']
    ws = wb['Outstanding']
    rows = list(ws.iter_rows(values_only=True))
    grand = next(r for r in rows if r[2] == 'Grand Total')
    assert round(grand[5], 2) == 5195763 and grand[6] == 1000 and grand[7] == 500
    bill_rows = [r for r in rows if r[1] and r[1] != 'Ref. No.']
    assert len(bill_rows) == len(bills) and all(r[6] is None and r[7] is None for r in bill_rows)
    assert round(sum(r[5] for r in bill_rows), 2) == 5195763
    # Kunj: received and PDC sit beside Tally O/S on the party's total row
    i = next(n for n, r in enumerate(rows) if r[2] == kunj['tally_ledger_name'])
    total = next(r for r in rows[i + 1:] if r[2] and r[2].startswith('Total ('))
    assert total[6] == 1000 and total[7] == 500 and 'PDC' in total[10]
    first_bill = next(r for r in ws.iter_rows(min_row=5) if r[1].value and r[1].value != 'Ref. No.')
    assert first_bill[5].number_format == '#,##0.00 "Dr";#,##0.00 "Cr";0.00'


# ── Ebco: Tally Bills Receivable, no Opening column, plain amounts ────────────

EBCO_OUTSTANDING = 'OUTSTANDING REPORT 19-10-2026.xlsx'


def test_ebco_bills_receivable_parses_and_matches_tally():
    out = P.parse_outstanding(_sample(EBCO_OUTSTANDING))
    assert (out['period_from'], out['as_of']) == (date(2026, 4, 1), date(2026, 10, 17))
    assert not out['detail'] and not out['warnings']
    assert len(out['bills']) == 28 and out['grand_total'] == D('2428314.03')
    assert sum(b['pending_amt'] for b in out['bills']) == D('2428314.03')
    assert {b['kind'] for b in out['bills']} == {P.KIND_INVOICE}       # 26-27-EB-INV-20
    assert all(b['opening_amt'] is None for b in out['bills'])
    dealers = R.new_dealers([], [b['party'] for b in out['bills']], 'EB-')
    assert len(dealers) == 17 and dealers[0]['dealer_id'] == 'EB-001'
    assert dealers[0]['dealer_name'] == dealers[0]['tally_ledger_name'] and dealers[0]['town'] == ''


def test_overdue_days_counted_to_today():
    due = date(2026, 11, 1)
    assert R.overdue_days(due, date(2026, 11, 18)) == 17
    assert R.overdue_days(due, due) == 0
    assert R.overdue_days(due, date(2026, 10, 31)) is None          # not yet due
    assert R.overdue_days(None, date(2026, 11, 18)) is None
    bills = [{'due_on': due, 'overdue_days': 16},                    # Tally's figure, as of 17-Nov
             {'due_on': date(2026, 12, 15), 'overdue_days': None},
             {'due_on': None, 'overdue_days': 5}]                    # no due date: Tally's kept
    assert [b['overdue_days'] for b in R.age_bills(bills, date(2026, 11, 18))] == [17, None, 5]


def test_overdue_amounts_by_days():
    d = {'dealer_id': 'D1', 'dealer_name': 'X'}
    day = date(2026, 11, 1)
    bills = [{'kind': 'invoice', 'ref_no': '1', 'bill_date': day, 'pending_amt': D('10'), 'overdue_days': 2},
             {'kind': 'invoice', 'ref_no': '2', 'bill_date': day - timedelta(days=2), 'pending_amt': D('30'), 'overdue_days': 4},
             {'kind': 'invoice', 'ref_no': '3', 'bill_date': day - timedelta(days=2), 'pending_amt': D('5'), 'overdue_days': 4},
             {'kind': 'invoice', 'ref_no': '4', 'bill_date': day + timedelta(days=5), 'pending_amt': D('50'),
              'overdue_days': None, 'due_on': day + timedelta(days=30)},                       # not yet due
             {'kind': 'receipt', 'ref_no': '5', 'bill_date': day + timedelta(days=9), 'pending_amt': D('-7'),
              'overdue_days': 9}]                                                              # Cr: on account
    s = R.dealer_summary(d, bills, [], [])
    # the ₹7 credit settles the oldest bill (ref 2) first, whatever its own date
    assert s['overdue'] == [{'days': 4, 'amount': D('28')}, {'days': 2, 'amount': D('10')}]
    assert s['overdue_os'] == D('38')
    assert R.dealer_summary(d, [], [], [])['overdue'] == []


def test_credits_settle_oldest_bills_first():
    """Sasthi Plywood: ₹50,000 on account (receipt 4637, not allocated in Tally) pays INV-6 down
    to ₹8,050; nothing else changes and what is left adds up to the party's balance."""
    d = {'dealer_id': 'D1', 'dealer_name': 'Sasthi Plywood'}
    today = date(2026, 11, 18)
    inv = [('26-27-EB-INV-6', date(2026, 9, 10), '58050'), ('26-27-EB-INV-30', date(2026, 9, 18), '23128'),
           ('26-27-EB-INV-60', date(2026, 10, 7), '11399'), ('26-27-EB-INV-69', date(2026, 10, 9), '4375'),
           ('26-27-EB-INV-89', date(2026, 10, 17), '7643')]
    bills = [{'kind': 'invoice', 'ref_no': r, 'bill_date': bd, 'due_on': bd, 'pending_amt': D(a)} for r, bd, a in inv]
    bills.append({'kind': 'receipt', 'ref_no': '4637', 'bill_date': date(2026, 10, 21), 'due_on': date(2026, 10, 21),
                  'pending_amt': D('-50000')})
    bills = R.age_bills(bills, today)
    left = {b['ref_no']: b['left'] for b in R.settle_oldest_first(bills)}
    assert left['26-27-EB-INV-6'] == D('8050') and left['26-27-EB-INV-30'] == D('23128')
    assert sum(left.values()) == D('54595') and '4637' not in left
    s = R.dealer_summary(d, bills, [], [])
    assert s['tally_os'] == D('54595') and s['overdue_os'] == D('54595')
    assert s['oldest_overdue_days'] == 69
    assert s['overdue'][0] == {'days': 69, 'amount': D('8050')}
    assert sum(o['amount'] for o in s['overdue']) == D('54595')
    # a credit larger than the oldest bill runs on into the next ones
    bills[-1] = {**bills[-1], 'pending_amt': D('-60000')}
    s = R.dealer_summary(d, bills, [], [])
    assert s['oldest_overdue_days'] == 61 and s['overdue'][0] == {'days': 61, 'amount': D('21178')}


def test_cleared_cheques_not_in_tally():
    day = date(2026, 11, 10)
    start = date(2026, 4, 1)
    c = lambda no, amt, d=day, dealer='D1', status=R.CLEARED: {**_chq(no, 'x', amt, d, status), 'dealer_id': dealer}
    rcpt = lambda no, amt, d, dealer='D1': {'vch_no': no, 'vch_date': d, 'dealer_id': dealer,
                                            'vch_type': R.RECEIPT, 'amount': D(str(amt))}
    cheques = [c('1', 1000),                                   # receipt 2 days later: in Tally
               c('2', 2000),                                   # no receipt: not in Tally
               c('3', 1000, day + timedelta(days=1)),          # the one ₹1,000 receipt is taken by cheque 1
               c('4', 500, status=R.DEPOSITED),                # not cleared: PDCs held, not here
               c('5', 700, date(2026, 3, 30)),                 # before the register starts: not checked
               c('6', 900),                                    # its receipt is a logged payment's
               c('7', 300, dealer='D2')]                       # another dealer's receipt does not count
    receipts = [rcpt('R1', 1005, day + timedelta(days=2)), rcpt('R6', 900, day),
                rcpt('R7', 300, day, dealer='D1x')]
    out = R.cleared_not_in_tally(cheques, receipts, {('R6', day)}, start)
    assert sorted(x['cheque_no'] for x in out) == ['2', '3', '6', '7']
    assert R.cleared_not_in_tally(cheques, receipts, set(), None) == []                  # no register yet
    assert sorted(x['cheque_no'] for x in R.cleared_not_in_tally(cheques, receipts, set(), start, {('2', 'SBI')})) == ['3', '7']

    s = R.dealer_summary({'dealer_id': 'D1', 'dealer_name': 'X'},
                         [{'kind': 'invoice', 'ref_no': 'a', 'pending_amt': D('5000'), 'overdue_days': 3}],
                         [_pay(1, 'D1', 100, day)], cheques, cleared=out)
    assert (s['cleared_cheques'], s['cleared_cheques_amount']) == (3, D('3900'))
    assert s['received_not_in_tally'] == D('4000')             # ₹100 logged + ₹3,900 cleared cheques
    assert s['effective_os'] == D('1000')


def test_ebco_grpbills_kinds():
    out = P.parse_outstanding(_sample('EbcoGrpBills.xlsx'))
    assert out['grand_total'] == D('6474522.80') and len(out['bills']) == 180 and not out['warnings']
    kinds = {}
    for b in out['bills']:
        kinds[b['kind']] = kinds.get(b['kind'], 0) + 1
    # 26-27/EBVCN/n are credit notes; a receipt held on account (ref = its voucher no.) is a
    # receipt; the Ebco Purchase bills (AE/26-27/n) and one Payment (535) stay "other".
    assert kinds == {P.KIND_INVOICE: 156, P.KIND_CREDIT_NOTE: 14, P.KIND_RECEIPT: 6, P.KIND_OTHER: 4}
    by_ref = {b['ref_no']: b['kind'] for b in out['bills']}
    assert by_ref['26-27/EBVCN/001'] == P.KIND_CREDIT_NOTE and by_ref['4730'] == P.KIND_RECEIPT
    assert by_ref['535'] == P.KIND_OTHER and by_ref['AE/26-27/4795'] == P.KIND_OTHER


def test_name_key_ignores_leading_for():
    assert R.name_key('FOR FUTURE INDUSTRIES') == R.name_key('Future Industries | Ebco | Bareilly')
    assert R.name_key('For  Future Industries') == R.name_key('FUTURE INDUSTRIES')
    assert R.name_key('FORTUNE HARDWARE') == 'FORTUNEHARDWARE'        # only the word "For"
    assert R.name_key('M/S GULATHI MEDICAL CENTRE') == R.name_key('Gulathi Medical Centre | Cadila | Sambhal')


def test_not_due_until_a_bill_is_past_due():
    today = date(2026, 11, 18)
    bill = lambda ref, amt, due: {'kind': 'invoice', 'ref_no': ref, 'pending_amt': D(str(amt)), 'due_on': due,
                                  'overdue_days': R.overdue_days(due, today) if due else None}
    d = {'dealer_id': 'D1', 'dealer_name': 'X'}
    summ = lambda bills, pays=(), cheques=(): R.dealer_summary(d, bills, list(pays), list(cheques))

    # S.A.S: one bill, due 15-Dec, nothing paid — owed but not due.
    s = summ([bill('a', 132587, date(2026, 12, 15))])
    assert (s['action'], s['wait_till'], s['overdue_os']) == (R.ACTION_NOT_DUE, date(2026, 12, 15), D('0'))

    # Overdue ₹1,000 plus ₹5,000 not due: chase the ₹1,000 ...
    bills = [bill('a', 1000, date(2026, 11, 1)), bill('b', 5000, date(2026, 12, 1))]
    s = summ(bills)
    assert (s['action'], s['overdue_os'], s['effective_os']) == (R.ACTION_CHASE, D('1000'), D('6000'))
    # ... a payment settles the overdue bill first, so the rest is not due till 1-Dec ...
    s = summ(bills, [_pay(1, 'D1', 1000, today)])
    assert (s['action'], s['wait_till']) == (R.ACTION_NOT_DUE, date(2026, 12, 1))
    # ... and a credit balance does the same.
    s = summ(bills + [{'kind': 'invoice', 'ref_no': 'cr', 'pending_amt': D('-1000'), 'due_on': None, 'overdue_days': None}])
    assert s['action'] == R.ACTION_NOT_DUE
    # PDCs that cover the overdue part: WAIT.
    s = summ(bills, cheques=[{**_chq('9', 'x', 1000, today + timedelta(days=3)), 'dealer_id': 'D1'}])
    assert (s['action'], s['wait_till']) == (R.ACTION_WAIT, today + timedelta(days=3))
    # A bill not overdue with no due date: cannot tell, so all of it counts as due.
    s = summ([bill('a', 500, None)])
    assert (s['action'], s['overdue_os']) == (R.ACTION_CHASE, None)
    # Nothing owed: CLEAR.
    assert summ([bill('a', 0, date(2026, 11, 1))])['action'] == R.ACTION_CLEAR


def test_remind_not_due_dealers_with_a_bill_20_days_old():
    today = date(2026, 11, 18)
    d = {'dealer_id': 'D1', 'dealer_name': 'X'}
    bill = lambda billed, due, amt=1000: {'kind': 'invoice', 'ref_no': str(billed), 'pending_amt': D(str(amt)),
                                          'bill_date': billed, 'due_on': due, 'overdue_days': None}
    summ = lambda *bills: R.dealer_summary(d, R.age_bills(list(bills), today), [], [])
    s = summ(bill(date(2026, 10, 25), date(2026, 12, 4)))            # 24 days old, due 4-Dec
    assert (s['action'], s['remind'], s['oldest_bill_age_days']) == (R.ACTION_NOT_DUE, True, 24)
    s = summ(bill(date(2026, 10, 30), date(2026, 12, 4)))            # 19 days old: not yet
    assert (s['action'], s['remind']) == (R.ACTION_NOT_DUE, False)
    s = summ(bill(date(2026, 10, 29), date(2026, 12, 4)))            # exactly 20 days
    assert s['remind'] is True
    s = summ(bill(date(2026, 9, 1), date(2026, 10, 1)))              # overdue: CHASE, not REMIND
    assert (s['action'], s['remind']) == (R.ACTION_CHASE, False)
    s = summ(bill(date(2026, 9, 1), date(2026, 12, 4), amt=-500), bill(date(2026, 11, 10), date(2026, 12, 20)))
    assert (s['remind'], s['oldest_bill_age_days']) == (False, 8)      # a credit's age does not count


# ── beat-wise files (beats.py) ────────────────────────────────────────────────

def _beat_fixture():
    outlets = [
        {'outlet_name': 'M/S BANSAL HARDWARE AND PLYWOOD', 'beat_id': 'b1', 'beat_name': 'Anmol_Mathura', 'city': 'Mathura'},
        {'outlet_name': 'Ankit Traders', 'beat_id': 'b2', 'beat_name': 'Anmol_BULANDSHAHR', 'city': 'Bulandshahr'},
        {'outlet_name': 'Ankit Traders', 'beat_id': 'b3', 'beat_name': 'Anmol_PILIBHIT', 'city': 'Nawabganj'},
        {'outlet_name': 'Rudra Ply', 'beat_id': 'b4', 'beat_name': 'Anmol_UDHAM SINGH NAGAR', 'city': 'Rudrapur'},
        {'outlet_name': 'Agra One', 'beat_id': 'b5', 'beat_name': 'Anmol_Agra', 'city': 'Agra'},
        {'outlet_name': 'Agra Two', 'beat_id': 'b6', 'beat_name': 'Anmol_BAREILLY', 'city': 'Agra'},
        {'outlet_name': 'Orphan Store', 'beat_id': 'b7', 'beat_name': 'Anmol_Nowhere', 'city': 'Ramnagar'},
    ]
    exec_beats = [{'se_name': 'Arun Dixit', 'beat_name': 'Anmol_Mathura'},
                  {'se_name': 'Arun Dixit', 'beat_name': 'Anmol_Agra'},
                  {'se_name': 'Nitesh Massey', 'beat_name': 'Anmol_BULANDSHAHR'},
                  {'se_name': 'Nitesh Massey', 'beat_name': 'anmol_udham singh nagar '},
                  {'se_name': 'Kamlesh Kumar', 'beat_name': 'Anmol_PILIBHIT'},
                  {'se_name': 'Kamlesh Kumar', 'beat_name': 'Anmol_BAREILLY'}]
    dealers = [
        {'dealer_id': 'EB-1', 'dealer_name': 'Bansal Hardware And Plywood', 'town': 'Mathura',
         'tally_ledger_name': 'Bansal Hardware And Plywood | Ebco | Mathura'},
        {'dealer_id': 'EB-2', 'dealer_name': 'Ankit Traders', 'town': 'Bulandshahr', 'tally_ledger_name': 'x'},
        {'dealer_id': 'EB-3', 'dealer_name': 'Taneja Glass Store', 'town': 'Rudrapur', 'tally_ledger_name': 'x'},
        {'dealer_id': 'EB-4', 'dealer_name': 'Shri Din Dayal & Sons', 'town': 'Agra', 'tally_ledger_name': 'x'},
        {'dealer_id': 'EB-5', 'dealer_name': 'Anand Enterprises', 'town': 'Lucknow', 'tally_ledger_name': 'x'},
        {'dealer_id': 'EB-6', 'dealer_name': 'Orphan Store', 'town': 'Ramnagar', 'tally_ledger_name': 'x'},
        {'dealer_id': 'EB-7', 'dealer_name': 'Ankit Traders', 'town': 'Lucknow', 'tally_ledger_name': 'x'},
    ]
    return dealers, outlets, exec_beats


def test_beats_assign_by_name_town_and_unassigned():
    from api.modules.sales.dealer_payments import beats as B
    placed, unassigned = B.assign(*_beat_fixture())
    # by name, ignoring M/S, & and case
    assert placed['EB-1'] == {'executives': ['Arun Dixit'], 'beat_name': 'Anmol_Mathura', 'how': B.BY_NAME}
    # an outlet on two beats, settled by the dealer's town
    assert placed['EB-2']['executives'] == ['Nitesh Massey'] and placed['EB-2']['beat_name'] == 'Anmol_BULANDSHAHR'
    # not in the master by name; Rudrapur's outlets are all Nitesh's (beat names compared loosely)
    assert placed['EB-3'] == {'executives': ['Nitesh Massey'], 'beat_name': '', 'how': B.BY_TOWN}
    # Agra is split between Arun and Kamlesh: not guessed
    assert unassigned['EB-4'] == B.WHY_TOWN_SPLIT
    assert unassigned['EB-5'] == B.WHY_NOT_IN_MASTER
    assert unassigned['EB-6'].startswith(B.WHY_BEAT_UNOWNED)
    # on two beats and the town settles neither
    assert unassigned['EB-7'].startswith(B.WHY_TWO_BEATS)
    assert B.executives(_beat_fixture()[2])['Nitesh Massey'] == ['Anmol_BULANDSHAHR', 'anmol_udham singh nagar ']


def test_outstanding_xlsx_only_ids_heading_and_notes():
    from api.modules.sales.dealer_payments.exports import build_outstanding_xlsx
    dealers = [{'dealer_id': 'EB-1', 'tally_ledger_name': 'Alpha | Ebco | X', 'dealer_name': 'Alpha', 'town': 'X'},
               {'dealer_id': 'EB-2', 'tally_ledger_name': 'Beta | Ebco | Y', 'dealer_name': 'Beta', 'town': 'Y'}]
    bill = dict(ref_no='A000001', kind='invoice', bill_date=date(2026, 11, 1), opening_amt=D('100'),
                pending_amt=D('100'), due_on=date(2026, 11, 20), overdue_days=None)
    bills = [{**bill, 'dealer_id': 'EB-1'}, {**bill, 'dealer_id': 'EB-2', 'ref_no': 'A000002'}]
    data = build_outstanding_xlsx(as_of=date(2026, 11, 18), dealers=dealers, bills=bills, payments=[], cheques=[],
                                  bounced_cheques={}, cheques_note='n', today=date(2026, 11, 19), company='Ebco',
                                  only_ids={'EB-2'}, heading='Nitesh · beats: B', party_notes={'EB-2': 'Beat: B'})
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    cells = [c for r in ws.iter_rows(values_only=True) for c in r if c is not None]
    assert 'Nitesh · beats: B' in cells and 'Beat: B' in cells and 'Beta | Ebco | Y' in cells
    assert 'Alpha | Ebco | X' not in cells
    empty = build_outstanding_xlsx(as_of=date(2026, 11, 18), dealers=dealers, bills=bills, payments=[], cheques=[],
                                   bounced_cheques={}, cheques_note='n', today=date(2026, 11, 19), only_ids=set())
    cells = [c for r in openpyxl.load_workbook(io.BytesIO(empty)).active.iter_rows(values_only=True) for c in r if c]
    assert 'No dealer with outstanding.' in cells
