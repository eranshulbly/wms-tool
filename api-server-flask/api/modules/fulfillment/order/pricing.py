# -*- encoding: utf-8 -*-
"""Order value, landing cost and margin — shared by every screen that shows them.

Kept in one place deliberately: the moment two screens compute margin separately they
start disagreeing, and a margin that differs by screen is worse than no margin at all.
"""


def order_totals(lines):
    """Totals for a list of line dicts carrying quantity / net_rate / landing_price.

    value   = sum(net_rate x qty) over PRICED lines
    landing = sum(landing_price x qty) over lines that also carry a cost
    margin  = value of those lines - landing

    Only lines with BOTH a rate and a landing price count toward the margin. Comparing a
    priced line against a missing cost understates cost and overstates margin, which is
    the one error worth refusing to make here — so the counts come back too, and the UI
    says how much of the order the margin actually covers.
    """
    value = landing = covered = 0.0
    priced = costed = 0
    for ln in lines:
        qty = float(ln.get('quantity') or 0)
        rate = ln.get('net_rate')
        land = ln.get('landing_price')
        if rate is None:
            continue
        priced += 1
        value += float(rate) * qty
        if land is None:
            continue
        # Only the quantity batches could actually cover is costed; the rest of the line
        # is left out of the margin rather than costed at a price nothing was found for.
        cqty = float(ln.get('costed_quantity', qty) or 0)
        costed += 1
        landing += float(land) * cqty
        covered += float(rate) * cqty

    margin = covered - landing
    return {
        'lines': len(lines),
        'priced_lines': priced,
        'costed_lines': costed,
        'order_total': round(value, 2) if priced else None,
        'landing_cost': round(landing, 2) if costed else None,
        'margin': round(margin, 2) if costed else None,
        'margin_pct': round(margin / covered * 100, 2) if costed and covered else None,
    }


# ---------------------------------------------------------------------------
# FEFO landing cost
# ---------------------------------------------------------------------------

def _batches_for(product_ids, company_id):
    """{product_id: [batch dicts]} — earliest expiry first, with stock on hand.

    Availability is LIVE stock (fc_entity_stock), not the quantity originally received:
    FEFO is a picking rule, so an order should be costed against what would actually
    ship. A batch already sold out contributes nothing, where received-quantity would
    have let it keep absorbing quantity at its old price.

    fc_entity_stock holds one row per bin, so quantities are summed per batch. The
    'RATE LIST' pseudo-batch (batch_id 0) is excluded — it is a price list, not stock.
    """
    from api.shared.db_manager import mysql_manager
    if not product_ids:
        return {}
    ph = ",".join(["%s"] * len(product_ids))
    rows = mysql_manager.execute_query(
        f"""SELECT s.entity_id AS product_id, s.batch_id,
                   SUM(s.quantity) AS on_hand,
                   JSON_UNQUOTE(JSON_EXTRACT(sb.batch_params, '$.expiry'))      AS expiry,
                   JSON_UNQUOTE(JSON_EXTRACT(sb.batch_params, '$.batch_number')) AS batch_number,
                   MAX(f.landing_price) AS landing_price
            FROM fc_entity_stock s
            JOIN sku_batch sb ON sb.id = s.batch_id
            LEFT JOIN fc_sku_price_details f
                   ON f.entity_id = s.entity_id AND f.batch_id = s.batch_id
            WHERE s.entity_id IN ({ph}) AND s.company_id = %s AND s.batch_id <> 0
            GROUP BY s.entity_id, s.batch_id, expiry, batch_number
            HAVING SUM(s.quantity) > 0""",
        tuple(list(product_ids) + [company_id])) or []

    out = {}
    for r in rows:
        if r['landing_price'] is None:
            continue          # no cost on record — cannot be costed against
        out.setdefault(r['product_id'], []).append({
            'batch_id': r['batch_id'],
            'batch_number': r['batch_number'],
            # A batch with no expiry sorts last: it cannot be claimed to expire soonest.
            'expiry': r['expiry'] or '9999-12-31',
            'on_hand': float(r['on_hand'] or 0),
            'landing_price': float(r['landing_price']),
        })
    for batches in out.values():
        batches.sort(key=lambda b: (b['expiry'], b['batch_id']))
    return out


def apply_fefo_landing(lines, company_id):
    """Fill each line's landing cost by consuming batches earliest-expiry first.

    A line's quantity is walked across its product's batches in expiry order, taking
    what each can cover. The line's `landing_price` becomes the WEIGHTED unit cost over
    the quantity that batches could actually cover, and `costed_quantity` records how
    much that was — so a line only partly covered contributes only its covered part to
    the margin instead of being costed as if the whole of it were.

    Lines that already name a batch are left untouched: an invoice stating which batch
    landed is a fact, and replacing it with an inference would be a downgrade.

    Mutates and returns `lines`.
    """
    need = [ln for ln in lines
            if ln.get('landing_price') is None and ln.get('product_id')]
    if not need:
        return lines

    batches = _batches_for({ln['product_id'] for ln in need}, company_id)
    # Stock is consumed across the whole order, not per line: two lines for the same
    # product must not both be costed against the same units of the oldest batch.
    remaining = {pid: [dict(b) for b in bs] for pid, bs in batches.items()}

    for ln in need:
        want = float(ln.get('quantity') or 0)
        if want <= 0:
            continue
        cost = 0.0
        covered = 0.0
        picked = []
        for b in remaining.get(ln['product_id'], []):
            if want <= 0:
                break
            take = min(want, b['on_hand'])
            if take <= 0:
                continue
            cost += take * b['landing_price']
            covered += take
            b['on_hand'] -= take
            want -= take
            picked.append({'batch_number': b['batch_number'], 'expiry': b['expiry'],
                           'quantity': round(take, 4), 'landing_price': b['landing_price']})
        if covered > 0:
            ln['landing_price'] = round(cost / covered, 4)
            ln['costed_quantity'] = round(covered, 4)
            ln['landing_batches'] = picked
    return lines
