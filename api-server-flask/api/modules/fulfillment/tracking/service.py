# -*- encoding: utf-8 -*-
"""tracking module — what one search means, and what an order's story looks like."""

import re

from api.core.logging import get_logger
from api.modules.fulfillment.tracking import repository as repo

logger = get_logger(__name__)

# The last digits off a printed sheet. Three at minimum — two would match a
# dozen orders and reading the disambiguation list takes longer than typing the
# rest of the number.
_RE_SUFFIX = re.compile(r'^[0-9]{3,10}$')

# A whole order number: at least three hyphen-separated alphanumeric parts.
_RE_ORDER_NO = re.compile(r'^[0-9A-Z]+(?:-[0-9A-Z]+){2,}$')


def _iso(value):
    return value.isoformat() if value else None


def _summary(row: dict) -> dict:
    return {
        'potential_order_id': row['potential_order_id'],
        'order_no': row['original_order_id'] or '',
        'dealer_name': row['dealer_name'] or '',
        'status': row['status'] or '',
        'order_date': _iso(row.get('order_date')),
        'box_count': int(row.get('box_count') or 0),
    }


def search(q: str, company_ids) -> dict:
    """Resolve what the operator scanned or typed.

    Four inputs, because that is what a person at a bench actually has:

      1. a scanned pick-list QR, or the token printed under it — the sheet in
         their hand is the fastest way in
      2. the whole order number
      3. the last few digits of it
      4. a dealer's name, when they have the trolley but not the paperwork

    Returns `{'mode': 'order', ...}` when exactly one order answers, and
    `{'mode': 'list', 'items': [...]}` when several do. Ambiguity is shown, not
    guessed at: suffixes repeat across order series, and quietly opening the
    newest match would be a confident wrong answer.
    """
    text = (q or '').strip()
    if not text:
        return {'mode': 'list', 'items': [], 'total': 0, 'query': ''}

    # 1. A scan. Resolved through the pick-list token, never by reading the
    #    order number out of the payload text — the token is the part that
    #    proves the sheet is real.
    from api.modules.fulfillment.packing.service import resolve_scanned_query
    scanned = resolve_scanned_query(text)
    if scanned:
        text = scanned

    upper = text.upper()
    rows = []
    if _RE_ORDER_NO.match(upper):
        rows = repo.by_order_no_exact(upper, company_ids)
    elif _RE_SUFFIX.match(upper):
        rows = repo.by_order_suffix(upper, company_ids)

    # Nothing numeric matched, so treat it as a dealer. Done last rather than
    # first: an order number is an exact thing and should never be diluted into
    # a name search that happens to contain the same digits.
    if not rows and not _RE_SUFFIX.match(upper):
        rows = repo.by_dealer(text, company_ids)

    if len(rows) == 1:
        return {'mode': 'order', 'order': detail(rows[0]['potential_order_id'],
                                                 company_ids), 'query': text}

    return {
        'mode': 'list',
        'items': [_summary(r) for r in rows],
        'total': len(rows),
        'query': text,
    }


def detail(potential_order_id: int, company_ids):
    """Everything known about one order's journey, or None if out of scope."""
    rows = repo.by_potential_order_id(potential_order_id, company_ids)
    if not rows:
        return None

    order = _summary(rows[0])
    picklist = repo.picklist_for_order(potential_order_id)
    history = repo.history_for_order(potential_order_id)

    # The first time each status was entered. First rather than last because a
    # re-scan or a correction can write a second row, and "when was this
    # picked" means the moment it started being picked.
    seen = {}
    for h in history:
        seen.setdefault(h['state_name'], h)

    def milestone(state):
        h = seen.get(state)
        if not h:
            return None
        return {
            'at': _iso(h['changed_at']),
            'by': h.get('changed_by_name') or '',
        }

    order.update({
        'picked': milestone('Picking'),
        'packed': milestone('Packed'),
        'dispatch_ready': milestone('Dispatch Ready'),
        'completed': milestone('Completed'),
        'cancelled': milestone('Cancelled'),
        'opened': milestone('Open'),
        # The whole trail, so the screen can show anything the milestones above
        # do not name without another round trip.
        'history': [
            {'status': h['state_name'], 'at': _iso(h['changed_at']),
             'by': h.get('changed_by_name') or ''}
            for h in history
        ],
    })

    if picklist:
        order['picklist'] = {
            'picklist_id': picklist['picklist_id'],
            'picklist_code': picklist['picklist_code'] or '',
            'line_count': int(picklist['line_count'] or 0),
            # Who physically took the sheet, from the card scanned at Picking.
            # Distinct from `picked.by`, which is the ACCOUNT that made the
            # move — usually a supervisor's handheld, not the picker.
            'picker_code': picklist['picker_code'] or '',
            'picker_assigned_at': _iso(picklist['picker_assigned_at']),
            'printed_at': _iso(picklist['printed_at']),
            'print_count': int(picklist['print_count'] or 0),
            'uploaded_at': _iso(picklist['uploaded_at']),
            'uploaded_by': picklist['uploaded_by_name'] or '',
        }
    else:
        order['picklist'] = None

    return order
