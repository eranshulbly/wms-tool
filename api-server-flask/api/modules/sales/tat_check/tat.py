# -*- encoding: utf-8 -*-
"""The TAT rules, as pure functions — no database, so they are testable on their own.

A SKU's quantity sits in up to three places, and each place has its own answer:

  In stock     current stock in the latest Inventory Report           -> 'In stock'
  In transit   dispatched by the supplier, GRN not yet approved       -> expected date of
                                                                          arrival: dispatch
                                                                          (billing) date + 5 days
  In PO        on a supplier PO, not yet dispatched (Open Dlv Qty)    -> 'In PO'

The SKU's overall status is the nearest place that has any quantity.
"""

from collections import defaultdict
from datetime import timedelta

TRANSIT_DAYS = 5

STATUS_IN_STOCK = 'In stock'
STATUS_IN_TRANSIT = 'In transit'
STATUS_IN_PO = 'In PO'
STATUS_NONE = 'Not available'


def in_transit(dispatch_lines, approved_grn_lines):
    """Dispatch lines still on the road, each with the quantity not yet received.

    A dispatch line (billing document x SKU) is received by the GRN lines approved
    against the same billing document and SKU. Quantities are netted rather than matched
    by existence, because the DMS can split one invoice into several GRNs (one per DMS
    order) that are approved on different days.
    """
    received = defaultdict(float)
    for g in approved_grn_lines:
        received[(g['billing_doc'], g['sku_code'])] += float(g['qty_uploaded'] or 0)
    out = []
    for d in dispatch_lines:
        key = (d['billing_doc'], d['sku_code'])
        qty = float(d['qty'] or 0)
        taken = min(qty, received[key])
        received[key] -= taken
        if qty - taken > 0:
            out.append({**d, 'qty': qty - taken, 'eta': expected_arrival(d.get('billing_date'))})
    return out


def expected_arrival(dispatch_date):
    """Expected date of arrival: TRANSIT_DAYS after the supplier's dispatch (billing) date."""
    return dispatch_date + timedelta(days=TRANSIT_DAYS) if dispatch_date else None


def summarize(stock_qty, transit_lines, po_qty):
    """The three buckets and the SKU's overall status.

    The in-transit bucket carries the expected arrival of its earliest and latest lines
    (`eta`, `eta_last`) — one SKU can be on several invoices dispatched on different days.
    """
    transit_qty = sum(float(t['qty']) for t in transit_lines)
    etas = sorted(t['eta'] for t in transit_lines if t.get('eta'))
    buckets = [
        {'key': 'stock', 'label': 'In stock', 'qty': stock_qty, 'status': STATUS_IN_STOCK},
        {'key': 'transit', 'label': 'In transit', 'qty': transit_qty, 'status': STATUS_IN_TRANSIT,
         'eta': etas[0] if etas else None, 'eta_last': etas[-1] if etas else None},
        {'key': 'po', 'label': 'In PO', 'qty': po_qty, 'status': STATUS_IN_PO},
    ]
    nearest = next((b for b in buckets if b['qty'] > 0), None)
    return {'status': nearest['status'] if nearest else STATUS_NONE,
            'eta': nearest.get('eta') if nearest else None,
            'buckets': buckets}
