# -*- encoding: utf-8 -*-
"""The Beat Outstanding rules, as pure functions — no database, so they are testable on
their own.

  1. A Tally party is placed on a beat when its name (parser.name_key) is the name of
     exactly one beat in the Outlet Master. A name on two beats (two shops with one name
     in different towns) is ambiguous and placed on neither — guessing would send one
     dealer's dues to the wrong executive.
  2. An executive's dealers on a date are the placed parties on the beats the beat plan
     gives them that date.
  3. Days overdue are counted from the bill's due date to `today`, not taken from the
     report, so an older report still shows today's age.

Parties that cannot be placed are returned too (`unplaced`), with the reason, so no
outstanding silently drops out of what is handed to the field.
"""

from collections import defaultdict

REASON_NOT_IN_MASTER = 'Not in the Outlet Master'
REASON_NO_BEAT = 'In the Outlet Master but on no beat'
REASON_AMBIGUOUS = 'Name is on more than one beat'


def place_parties(bills, outlets):
    """({name_key: placement}, [unplaced party]) for every party that has bills.

    placement = {'beat_id', 'beat_name', 'city', 'outlet_name'}.
    """
    beats = defaultdict(dict)  # name_key -> {beat_id: outlet}
    on_no_beat = set()
    for o in outlets:
        if o['beat_id']:
            beats[o['name_key']].setdefault(o['beat_id'], o)
        else:
            on_no_beat.add(o['name_key'])

    placed, unplaced = {}, []
    for key, party in _parties(bills).items():
        found = beats.get(key) or {}
        if len(found) == 1:
            o = next(iter(found.values()))
            placed[key] = {'beat_id': o['beat_id'], 'beat_name': o['beat_name'],
                           'city': o.get('city') or '', 'outlet_name': o['outlet_name']}
            continue
        if found:
            reason = REASON_AMBIGUOUS
            party['beats'] = sorted(o['beat_name'] for o in found.values())
        elif key in on_no_beat:
            reason = REASON_NO_BEAT
        else:
            reason = REASON_NOT_IN_MASTER
        unplaced.append({**party, 'reason': reason})
    unplaced.sort(key=lambda p: -p['amount'])
    return placed, unplaced


def _parties(bills):
    out = {}
    for b in bills:
        p = out.setdefault(b['name_key'], {'party_name': b['party_name'],
                                           'distributor': b.get('distributor') or '',
                                           'bill_count': 0, 'amount': 0.0})
        p['bill_count'] += 1
        p['amount'] = round(p['amount'] + float(b['amount']), 2)
    return out


def dealers_on(beat_ids, bills, placed, today):
    """Dealers on `beat_ids` that owe something, each with its bills — worst first:
    the oldest overdue money, then the largest amount."""
    beat_ids = set(beat_ids)
    dealers = {}
    for b in bills:
        where = placed.get(b['name_key'])
        if not where or where['beat_id'] not in beat_ids:
            continue
        d = dealers.setdefault(b['name_key'], {
            'party_name': b['party_name'], 'beat_id': where['beat_id'],
            'beat_name': where['beat_name'], 'city': where['city'],
            'bills': [], 'amount': 0.0, 'max_days_overdue': None})
        days = (today - b['due_on']).days
        d['bills'].append({'bill_date': b['bill_date'], 'ref_no': b['ref_no'],
                           'due_on': b['due_on'], 'days_overdue': days,
                           'amount': float(b['amount'])})
        d['amount'] = round(d['amount'] + float(b['amount']), 2)
        # A credit's own age is not something to chase a dealer over.
        if float(b['amount']) > 0:
            d['max_days_overdue'] = max(d['max_days_overdue'] or 0, days)
    out = list(dealers.values())
    for d in out:
        d['bills'].sort(key=lambda x: x['due_on'])
        d['bill_count'] = len(d['bills'])
    out.sort(key=lambda d: (-(d['max_days_overdue'] if d['max_days_overdue'] is not None else -1),
                            -d['amount']))
    return out


def executives_on(plan_rows):
    """The beat plan for one date grouped by executive, in the plan's own order."""
    execs = {}
    for r in plan_rows:
        e = execs.setdefault((r['user_id'], r['se_name']), {
            'user_id': r['user_id'], 'se_name': r['se_name'], 'beats': []})
        if r['beat_id'] not in {b['beat_id'] for b in e['beats']}:
            e['beats'].append({'beat_id': r['beat_id'], 'beat_name': r['beat_name']})
    return list(execs.values())
