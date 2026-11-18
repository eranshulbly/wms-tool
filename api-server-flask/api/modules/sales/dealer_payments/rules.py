# -*- encoding: utf-8 -*-
"""Dealer Payment Tracker — the rules, as pure functions over plain dicts (no database).
Section numbers refer to Cadila/dealer_payment_tracker_spec.md.

Amounts are Decimal, signed the Tally way: Dr (the dealer owes) positive, Cr negative.
"""

import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from api.modules.sales.dealer_payments.parser import KIND_BOUNCE, KIND_CREDIT_NOTE

ZERO = Decimal('0.00')

# Payment log statuses (2.4). STALE is not a status: an OPEN payment more than
# STALE_AFTER_DAYS old is shown as stale (3.2).
OPEN, POSTED, CANCELLED, BOUNCED = 'OPEN', 'POSTED', 'CANCELLED', 'BOUNCED'
MODES = ('BT', 'CASH')

# Cheque statuses from the cheque system (2.5).
HOLDING, DEPOSITED, CLEARED, CHQ_BOUNCED = 'HOLDING', 'DEPOSITED', 'CLEARED', 'BOUNCED'
HELD = (HOLDING, DEPOSITED)

MATCH_AMOUNT_TOLERANCE = Decimal('10')      # 3.2: ±₹10
MATCH_DAYS_BEFORE, MATCH_DAYS_AFTER = 2, 20  # 3.2: payment_date − 2 … + 20
STALE_AFTER_DAYS = 5                         # 3.2
BOUNCE_AMOUNT_TOLERANCE = Decimal('1')      # 3.1: ±₹1
BOUNCE_DAYS_BEFORE = 10                      # 3.1: within 10 days before the Boo date
DUPLICATE_AMOUNT_TOLERANCE = Decimal('1')   # 3.3: ±₹1
DUPLICATE_DAYS = 7                           # 3.3

RECEIPT = 'Receipt'
BOUNCE_LABEL = 'Bounced / reversed receipt'

# Manual check types (4).
FLAG_DUPLICATE = 'possible_duplicate'
FLAG_CREDIT = 'credit_balance'
FLAG_AMBIGUOUS = 'ambiguous_match'
FLAG_UNMAPPED_CHEQUE = 'unmapped_cheque'
FLAG_NEW_DEALER = 'new_dealer'   # no longer raised: dealers come from Tally; kept to clear old ones
FLAG_LABELS = {
    FLAG_DUPLICATE: 'Possible duplicate',
    FLAG_CREDIT: 'Credit balance',
    FLAG_AMBIGUOUS: 'Ambiguous match',
    FLAG_UNMAPPED_CHEQUE: 'Unmapped cheque',
    FLAG_NEW_DEALER: 'New dealer',
}

ACTION_CHASE, ACTION_WAIT, ACTION_CLEAR = 'CHASE', 'WAIT', 'CLEAR'


def receipt_key(r):
    """A Tally receipt's identity: (vch_no, date)."""
    return (str(r['vch_no']), r['vch_date'])


def _money(x):
    return f'{x:,.2f}'


# ── dealers, created from the Tally uploads ──────────────────────────────────

def next_dealer_ids(existing_ids, count, prefix='CAD-'):
    """`count` new IDs after the highest CAD-nnn in use (CAD-036, CAD-037, …)."""
    nums = [int(m.group(1)) for i in existing_ids for m in [re.match(re.escape(prefix) + r'(\d+)$', i or '')] if m]
    start = max(nums, default=0) + 1
    width = max([len(m.group(1)) for i in existing_ids
                 for m in [re.match(re.escape(prefix) + r'(\d+)$', i or '')] if m], default=3)
    return [f'{prefix}{n:0{width}d}' for n in range(start, start + count)]


def new_dealers(known_dealers, party_names):
    """Dealers to create for party names not seen before, matched EXACTLY — every dealer
    comes from a Tally upload. Name, principal and town come from the ledger name
    ("Name | Cadila | Town"). [{dealer_id, tally_ledger_name, dealer_name, principal, town}]
    in first-seen order, numbered after the highest CAD-nnn in use."""
    known = {d['tally_ledger_name'] for d in known_dealers}
    unknown = []
    for name in party_names:
        if name not in known and name not in unknown:
            unknown.append(name)
    ids = next_dealer_ids([d['dealer_id'] for d in known_dealers], len(unknown))
    out = []
    for dealer_id, name in zip(ids, unknown):
        parts = [p.strip() for p in name.split('|')]
        out.append({'dealer_id': dealer_id, 'tally_ledger_name': name,
                    'dealer_name': parts[0] or name,
                    'principal': parts[1] if len(parts) >= 3 else '',
                    'town': parts[-1] if len(parts) >= 2 else '',
                    'cheque_system_name': '', 'exclude_from_chase': False, 'active': True})
    return out


def cheque_name(dealer):
    """The name a dealer goes by in the cheque system: Cheque System Name, else the ledger name."""
    return dealer.get('cheque_system_name') or dealer['tally_ledger_name']


# ── Export 2: window reload (2.3) ─────────────────────────────────────────────

def window_reload(stored, incoming, period_from, period_to):
    """The receipts after an upload: every stored receipt dated inside the file's period
    is dropped, then the file's receipts are added. Mirrors service.load_receipts, which
    does the same in SQL in one transaction."""
    kept = [r for r in stored if not (period_from <= r['vch_date'] <= period_to)]
    return kept + list(incoming)


# ── 3.1 bounces ───────────────────────────────────────────────────────────────

def bounce_bills(bills):
    """The Boo bills of a snapshot (bills made by a Payment voucher)."""
    return [b for b in bills if b['kind'] == KIND_BOUNCE]


def bounce_amount(bill):
    """What a Boo bill reverses: its opening amount (the receipt that bounced)."""
    return abs(bill['opening_amt'] if bill.get('opening_amt') is not None else bill['pending_amt'])


def bounced_payments(payments, boo_bills):
    """{payment_id: boo ref_no} for logged payments a Boo bill reverses (3.1): same dealer,
    amount within ±₹1, dated within 10 days before (or on) the Boo date. One payment per
    Boo — the closest before it. CANCELLED and already-BOUNCED payments are left alone."""
    out = {}
    for boo in sorted(boo_bills, key=lambda b: (b['bill_date'], b['ref_no'])):
        amount = bounce_amount(boo)
        hits = [p for p in payments
                if p['dealer_id'] == boo['dealer_id'] and p['status'] in (OPEN, POSTED)
                and p['id'] not in out
                and abs(p['amount'] - amount) <= BOUNCE_AMOUNT_TOLERANCE
                and boo['bill_date'] - timedelta(days=BOUNCE_DAYS_BEFORE) <= p['payment_date'] <= boo['bill_date']]
        if hits:
            best = max(hits, key=lambda p: (p['payment_date'], p['id']))
            out[best['id']] = boo['ref_no']
    return out


def bounced_cheques(cheques, boo_bills):
    """{(cheque_no, bank): boo ref_no} for mapped cheques a Boo bill reverses (3.1). Only
    labels the cheque here; its status belongs to the cheque system."""
    out = {}
    for boo in sorted(boo_bills, key=lambda b: (b['bill_date'], b['ref_no'])):
        amount = bounce_amount(boo)
        hits = [c for c in cheques
                if c.get('dealer_id') == boo['dealer_id'] and (c['cheque_no'], c['bank']) not in out
                and abs(c['amount'] - amount) <= BOUNCE_AMOUNT_TOLERANCE
                and boo['bill_date'] - timedelta(days=BOUNCE_DAYS_BEFORE) <= c['cheque_date'] <= boo['bill_date']]
        if hits:
            best = max(hits, key=lambda c: c['cheque_date'])
            out[(best['cheque_no'], best['bank'])] = boo['ref_no']
    return out


# ── 3.2 matching logged payments to Tally receipts ───────────────────────────

def match_payments(payments, receipts, matched_keys):
    """Match OPEN payments, oldest first, to Tally Receipt vouchers (3.2).

    A candidate: same dealer, a Receipt, amount within ±₹10, dated payment_date − 2 …
    + 20 days, and not already matched (`matched_keys`, or earlier in this run).

    Returns (posted, ambiguous):
      posted     {payment_id: receipt key}  — exactly one candidate
      ambiguous  {payment_id: [receipt key]} — more than one; the payment stays OPEN
    """
    taken = set(matched_keys)
    posted, ambiguous = {}, {}
    by_dealer = defaultdict(list)
    for r in receipts:
        if r.get('vch_type', RECEIPT) == RECEIPT:
            by_dealer[r['dealer_id']].append(r)
    for p in sorted((p for p in payments if p['status'] == OPEN),
                    key=lambda p: (p['payment_date'], p['id'])):
        lo = p['payment_date'] - timedelta(days=MATCH_DAYS_BEFORE)
        hi = p['payment_date'] + timedelta(days=MATCH_DAYS_AFTER)
        cands = [r for r in by_dealer.get(p['dealer_id'], [])
                 if receipt_key(r) not in taken and lo <= r['vch_date'] <= hi
                 and abs(r['amount'] - p['amount']) <= MATCH_AMOUNT_TOLERANCE]
        if len(cands) == 1:
            key = receipt_key(cands[0])
            posted[p['id']] = key
            taken.add(key)
        elif len(cands) > 1:
            ambiguous[p['id']] = sorted(receipt_key(r) for r in cands)
    return posted, ambiguous


def is_stale(payment, today):
    """An OPEN payment more than 5 days after its payment date (3.2)."""
    return payment['status'] == OPEN and (today - payment['payment_date']).days > STALE_AFTER_DAYS


# ── 3.3 manual-check flags (never change a balance) ───────────────────────────

def possible_duplicates(receipts, boo_bills):
    """Pairs of Tally receipts that look like the same money posted twice (3.3): same
    dealer, amount within ±₹1, dates within 7 days — unless the dealer has a Boo bill of
    that amount dated between or on the two (a bounce and a re-payment, not a duplicate).

    Returns [(r1, r2)], r1 the earlier."""
    boos = defaultdict(list)
    for b in boo_bills:
        boos[b['dealer_id']].append(b)
    by_dealer = defaultdict(list)
    for r in receipts:
        if r.get('vch_type', RECEIPT) == RECEIPT:
            by_dealer[r['dealer_id']].append(r)
    pairs = []
    for dealer_id, rs in by_dealer.items():
        rs = sorted(rs, key=lambda r: (r['vch_date'], str(r['vch_no'])))
        for i, r1 in enumerate(rs):
            for r2 in rs[i + 1:]:
                if (r2['vch_date'] - r1['vch_date']).days > DUPLICATE_DAYS:
                    break
                if abs(r1['amount'] - r2['amount']) > DUPLICATE_AMOUNT_TOLERANCE:
                    continue
                explained = any(
                    abs(bounce_amount(b) - r1['amount']) <= DUPLICATE_AMOUNT_TOLERANCE
                    and r1['vch_date'] <= b['bill_date'] <= r2['vch_date']
                    for b in boos.get(dealer_id, []))
                if not explained:
                    pairs.append((r1, r2))
    return pairs


def credit_balances(bills):
    """{dealer_id: (total, credit_note_total)} for dealers whose signed Export 1 total is Cr
    and is not explained by their credit notes (CN/SC bills): Cr even without them (3.3)."""
    total, notes = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for b in bills:
        total[b['dealer_id']] += b['pending_amt']
        if b['kind'] == KIND_CREDIT_NOTE:
            notes[b['dealer_id']] += b['pending_amt']
    return {d: (t, notes[d]) for d, t in total.items() if t < 0 and t - notes[d] < 0}


def name_key(name):
    """A party name reduced for matching across systems: the part before the first '|',
    upper case, a leading M/S or MS dropped, letters and digits only.
    'M/S GULATHI MEDICAL CENTRE' and 'Gulathi Medical Centre | Cadila | Sambhal' agree."""
    s = str(name or '').split('|')[0].upper().strip()
    s = re.sub(r'^(M\s*/\s*S\.?|M\.S\.|MS\.?)\s+', '', s)
    return re.sub(r'[^A-Z0-9]', '', s)


def map_cheques(cheques, dealers):
    """Attach dealer_id to each cheque. A dealer's Cheque System Name matches exactly; failing
    that, the cheque's party name matches a dealer by name_key of its Cheque System Name or
    Tally ledger name.

    Returns (mapped, unmapped, other):
      mapped    cheques tied to one dealer
      unmapped  cheques whose name fits two or more dealers — a person must decide (Manual check)
      other     cheques matching no Cadila dealer at all. The cheque system serves other
                businesses under the same payee, so these are counted, not flagged."""
    exact = {d['cheque_system_name']: d['dealer_id'] for d in dealers if d.get('cheque_system_name')}
    by_key = {}
    for d in dealers:
        for k in {name_key(cheque_name(d)), name_key(d['tally_ledger_name'])}:
            if k:
                by_key.setdefault(k, set()).add(d['dealer_id'])
    mapped, unmapped, other = [], [], []
    for c in cheques:
        dealer_id = exact.get(c['party_name'])
        if not dealer_id:
            ids = by_key.get(name_key(c['party_name']), set())
            if len(ids) > 1:
                unmapped.append(c)
                continue
            dealer_id = next(iter(ids), None)
        if dealer_id:
            mapped.append({**c, 'dealer_id': dealer_id})
        else:
            other.append(c)
    return mapped, unmapped, other


def manual_check_flags(*, duplicates=(), credits=None, ambiguous=None, unmapped=(),
                       payments_by_id=None, receipts_by_key=None):
    """The Manual check list as [{fingerprint, flag_type, dealer_id, vouchers, dates, amounts,
    reason}]. The fingerprint names the underlying records, so a reviewed flag is not raised
    again unless they change (4)."""
    flags = []
    for r1, r2 in duplicates:
        flags.append({
            'flag_type': FLAG_DUPLICATE, 'dealer_id': r1['dealer_id'],
            'fingerprint': f"dup|{r1['dealer_id']}|{r1['vch_no']}@{r1['vch_date']}={r1['amount']}"
                           f"|{r2['vch_no']}@{r2['vch_date']}={r2['amount']}",
            'vouchers': [r1['vch_no'], r2['vch_no']],
            'dates': [r1['vch_date'], r2['vch_date']],
            'amounts': [r1['amount'], r2['amount']],
            'reason': (f"Receipts {r1['vch_no']} and {r2['vch_no']} of {_money(r1['amount'])} are "
                       f"{(r2['vch_date'] - r1['vch_date']).days} day(s) apart, with no bounce "
                       f"between them. Check whether the same money was posted twice."),
        })
    for dealer_id, (total, notes) in (credits or {}).items():
        flags.append({
            'flag_type': FLAG_CREDIT, 'dealer_id': dealer_id,
            'fingerprint': f'cr|{dealer_id}|{total}|{notes}',
            'vouchers': [], 'dates': [], 'amounts': [total],
            'reason': (f'Tally shows {_money(-total)} Cr owed TO the dealer'
                       + (f', more than their credit notes ({_money(-notes)})' if notes else '')
                       + '. Check for an over-payment or a mis-posted receipt.'),
        })
    for payment_id, keys in (ambiguous or {}).items():
        p = (payments_by_id or {}).get(payment_id, {})
        rs = [(receipts_by_key or {}).get(k, {'vch_no': k[0], 'vch_date': k[1], 'amount': None}) for k in keys]
        flags.append({
            'flag_type': FLAG_AMBIGUOUS, 'dealer_id': p.get('dealer_id'),
            'fingerprint': f"amb|{payment_id}|" + '|'.join(f'{k[0]}@{k[1]}' for k in keys),
            'payment_id': payment_id,
            'vouchers': [r['vch_no'] for r in rs], 'dates': [p.get('payment_date')] + [r['vch_date'] for r in rs],
            'amounts': [p.get('amount')] + [r['amount'] for r in rs],
            'reason': (f"Logged payment of {_money(p.get('amount') or ZERO)} on {p.get('payment_date')} "
                       f"fits {len(keys)} Tally receipts; left OPEN. Pick the right one by hand."),
        })
    for c in unmapped:
        flags.append({
            'flag_type': FLAG_UNMAPPED_CHEQUE, 'dealer_id': None,
            'fingerprint': f"chq|{c['cheque_no']}|{c['bank']}|{c['party_name']}|{c['amount']}",
            'vouchers': [c['cheque_no']], 'dates': [c['cheque_date']], 'amounts': [c['amount']],
            'party_name': c['party_name'],
            'reason': (f"Cheque {c['cheque_no']} ({c['bank']}) from \"{c['party_name']}\" fits more than one "
                       f"dealer, so it was not counted in PDCs held. Check whose cheque it is."),
        })
    return flags


# ── 4. the daily dealer screen ────────────────────────────────────────────────

def action_for(effective, pdc_amount, next_pdc):
    """(action, wait_till) — CLEAR if Effective O/S ≤ 0; WAIT till the next PDC if PDCs
    held cover it; else CHASE (4)."""
    if effective <= 0:
        return ACTION_CLEAR, None
    if pdc_amount >= effective:
        return ACTION_WAIT, next_pdc
    return ACTION_CHASE, None


_ACTION_ORDER = {ACTION_CHASE: 0, ACTION_WAIT: 1, ACTION_CLEAR: 2}


def dealer_summary(d, dbills, payments, cheques, bounced_cheque_keys=()):
    """One dealer's line on the dealer screen (4): `dbills` its bills in the latest Export 1
    snapshot; `payments` / `cheques` may be everyone's (filtered here)."""
    bounced = set(bounced_cheque_keys)
    tally = sum((b['pending_amt'] for b in dbills), ZERO)
    open_pays = [p for p in payments if p['dealer_id'] == d['dealer_id'] and p['status'] == OPEN]
    received = sum((p['amount'] for p in open_pays), ZERO)
    held = sorted((c for c in cheques if c.get('dealer_id') == d['dealer_id'] and c['status'] in HELD
                   and (c['cheque_no'], c['bank']) not in bounced),
                  key=lambda c: c['cheque_date'])
    pdc_amount = sum((c['amount'] for c in held), ZERO)
    next_pdc = held[0]['cheque_date'] if held else None
    effective = tally - received
    action, wait_till = action_for(effective, pdc_amount, next_pdc)
    overdue = [b['overdue_days'] for b in dbills if b['pending_amt'] > 0 and b.get('overdue_days') is not None]
    return {
        'dealer_id': d['dealer_id'],
        'dealer': f"{d['dealer_name']} ({d['town']})" if d.get('town') else d['dealer_name'],
        'tally_os': tally,
        'received_not_in_tally': received,
        'open_payments': len(open_pays),
        'pdc_count': len(held), 'pdc_amount': pdc_amount, 'next_pdc_date': next_pdc,
        'effective_os': effective,
        'oldest_overdue_days': max(overdue) if overdue else None,
        'action': action, 'wait_till': wait_till,
        'bounces': [{'ref_no': b['ref_no'], 'bill_date': b['bill_date'], 'amount': bounce_amount(b),
                     'pending_amt': b['pending_amt'], 'label': BOUNCE_LABEL}
                    for b in dbills if b['kind'] == KIND_BOUNCE],
    }


def dealer_rows(dealers, bills, payments, cheques, today, bounced_cheque_keys=()):
    """One row per active dealer not excluded from chasing (4), sorted CHASE first, each
    group by Effective O/S descending.

    `bills` the latest Export 1 snapshot; `payments` the payment log; `cheques` mapped
    cheques (with dealer_id). A cheque labelled bounced by a Boo bill is not counted as held.
    """
    by_dealer_bills = defaultdict(list)
    for b in bills:
        by_dealer_bills[b['dealer_id']].append(b)
    rows = [dealer_summary(d, by_dealer_bills.get(d['dealer_id'], []), payments, cheques, bounced_cheque_keys)
            for d in dealers if d.get('active', True) and not d.get('exclude_from_chase')]
    rows.sort(key=lambda r: (_ACTION_ORDER[r['action']], -r['effective_os'], r['dealer']))
    return rows


def pdcs_to_deposit(cheques, today, bounced_cheque_keys=()):
    """HOLDING cheques dated today or tomorrow: the ones to deposit (4)."""
    bounced = set(bounced_cheque_keys)
    tomorrow = today + timedelta(days=1)
    return sorted((c for c in cheques if c['status'] == HOLDING and today <= c['cheque_date'] <= tomorrow
                   and (c['cheque_no'], c['bank']) not in bounced),
                  key=lambda c: (c['cheque_date'], c['party_name']))


def stale_payments(payments, today):
    return sorted((p for p in payments if is_stale(p, today)), key=lambda p: (p['payment_date'], p['id']))
