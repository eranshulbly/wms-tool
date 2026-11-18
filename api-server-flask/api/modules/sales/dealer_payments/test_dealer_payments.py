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
    assert by[akansh]['oldest_overdue_days'] == 91
    actions = [r['action'] for r in rows]
    assert actions == sorted(actions, key={'CHASE': 0, 'WAIT': 1, 'CLEAR': 2}.get)
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
    bills = [{'kind': 'invoice', 'ref_no': '1', 'pending_amt': D('10'), 'overdue_days': 2},
             {'kind': 'invoice', 'ref_no': '2', 'pending_amt': D('30'), 'overdue_days': 4},
             {'kind': 'invoice', 'ref_no': '3', 'pending_amt': D('5'), 'overdue_days': 4},
             {'kind': 'invoice', 'ref_no': '4', 'pending_amt': D('50'), 'overdue_days': None},   # not yet due
             {'kind': 'invoice', 'ref_no': '5', 'pending_amt': D('-7'), 'overdue_days': 9}]      # Cr: not owed
    s = R.dealer_summary(d, bills, [], [])
    assert s['overdue'] == [{'days': 4, 'amount': D('35')}, {'days': 2, 'amount': D('10')}]
    assert R.dealer_summary(d, [], [], [])['overdue'] == []


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
