# -*- encoding: utf-8 -*-
"""Which sales executive each dealer belongs to (pure: data in, data out).

The beats come from Beat Outstanding: the Outlet Master (`bo_outlet`, outlet -> beat and
city, read only) and Executive Beats (`dpt_exec_beat`, this module's executive -> beats, the User Beats
list). A dealer is placed on a beat, then handed to whoever owns that beat:

  1. by name — the dealer's name (Tally's ledger name without " | Ebco | Town") is an
     outlet's name, compared as Beat Outstanding compares them (parser.name_key). An outlet
     listed on two beats is settled by the dealer's town when only one of the two is in it.
  2. by town — otherwise, when every outlet in the dealer's town is on beats one executive
     owns, the dealer is that executive's. A town split between executives is not guessed.

Everything else is unassigned, with the reason. No fuzzy matching: a near miss would send
one dealer's dues to another executive.
"""

from collections import defaultdict

from api.modules.sales.beat_outstanding.parser import name_key

BY_NAME, BY_TOWN = 'name', 'town'
WHY_NOT_IN_MASTER = 'Not in the Outlet Master, and its town is not a city there'
WHY_TOWN_SPLIT = 'Not in the Outlet Master by name, and its town is on more than one executive\'s beats'
WHY_TWO_BEATS = 'In the Outlet Master on more than one beat'
WHY_BEAT_UNOWNED = 'Its beat is in nobody\'s Executive Beats'


def _names(dealer):
    """The names the dealer may go by in the Outlet Master: its dealer name, and the first
    part of the Tally ledger name ('Bharat Timber Store | Ebco | Meerut')."""
    out = []
    for n in (dealer.get('dealer_name'), (dealer.get('tally_ledger_name') or '').split('|')[0]):
        k = name_key(n)
        if k and k not in out:
            out.append(k)
    return out


def assign(dealers, outlets, exec_beats):
    """({dealer_id: placement}, {dealer_id: reason}).

    placement = {'executives': [se_name, …], 'beat_name', 'how': BY_NAME | BY_TOWN}. A beat
    two executives own puts the dealer in both their files. `outlets` rows carry outlet_name,
    beat_id, beat_name and city; `exec_beats` rows se_name and beat_name.
    """
    owners = defaultdict(list)                    # beat name key -> executives, in list order
    for e in exec_beats:
        k = name_key(e['beat_name'])
        if e['se_name'] not in owners[k]:
            owners[k].append(e['se_name'])

    on_beats = defaultdict(dict)                  # outlet name key -> {beat_id: outlet}
    town_execs = defaultdict(set)                 # city key -> executives owning its outlets' beats
    for o in outlets:
        if not o.get('beat_id'):
            continue
        on_beats[name_key(o['outlet_name'])].setdefault(o['beat_id'], o)
        city = name_key(o.get('city'))
        if city:
            town_execs[city].update(owners.get(name_key(o['beat_name'])) or ['—'])

    placed, unassigned = {}, {}
    for d in dealers:
        town = name_key(d.get('town'))
        found = {}
        for k in _names(d):
            found = on_beats.get(k) or {}
            if found:
                break
        if len(found) > 1:
            in_town = {i: o for i, o in found.items() if town and name_key(o.get('city')) == town}
            found = in_town if len(in_town) == 1 else found
        if len(found) == 1:
            beat = next(iter(found.values()))['beat_name']
            execs = owners.get(name_key(beat))
            if execs:
                placed[d['dealer_id']] = {'executives': list(execs), 'beat_name': beat, 'how': BY_NAME}
            else:
                unassigned[d['dealer_id']] = f'{WHY_BEAT_UNOWNED} ({beat})'
            continue
        execs = town_execs.get(town) or set()
        if len(execs) == 1 and '—' not in execs:
            placed[d['dealer_id']] = {'executives': sorted(execs), 'beat_name': '', 'how': BY_TOWN}
        elif found:
            unassigned[d['dealer_id']] = WHY_TWO_BEATS + ' (' + ', '.join(
                sorted(o['beat_name'] for o in found.values())) + ')'
        elif execs == {'—'}:
            unassigned[d['dealer_id']] = 'Not in the Outlet Master by name, and its town\'s beats are in ' \
                                         'nobody\'s Executive Beats'
        elif execs:
            unassigned[d['dealer_id']] = WHY_TOWN_SPLIT
        else:
            unassigned[d['dealer_id']] = WHY_NOT_IN_MASTER
    return placed, unassigned


def executives(exec_beats):
    """{se_name: [beat_name, …]} in the order Executive Beats lists them."""
    out = {}
    for e in exec_beats:
        beats = out.setdefault(e['se_name'], [])
        if e['beat_name'] not in beats:
            beats.append(e['beat_name'])
    return out


def note_for(placement):
    """The line beside a dealer in an executive's file: how it was placed."""
    if placement['how'] == BY_NAME:
        return f"Beat: {placement['beat_name']}"
    return 'Placed by town (not in the Outlet Master by name)'
