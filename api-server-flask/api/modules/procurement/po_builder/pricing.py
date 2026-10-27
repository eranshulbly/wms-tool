# -*- encoding: utf-8 -*-
"""PO pricing and scheme-slab evaluation. Pure functions — no DB, no Flask.

Price build-up per line (discounts are chained, each on the result of the last):

    DTR basic       = MRP x (1 - dtr_discount%)          51.2% by default
    after standard  = DTR basic x (1 - std_discount%)    12% by default
    landing price   = after standard x (1 - scheme%)     scheme% of the line's group
    line value      = landing x qty
    GST             = line value x the SKU's own GST%    (IGST)

Scheme slabs are evaluated per GROUP, cumulatively across every line of that group in
the PO; different groups never combine. A QTY group totals qty, a VALUE group totals
`after standard x qty` (the price before any scheme — evaluating on the post-scheme
price would make the slab depend on itself). The applied slab is the highest one the
total reaches; below slab 1 the scheme is 0%.

The React page mirrors this file in views/po-builder/pricing.js so a qty edit
re-prices instantly; this module stays the source of truth for saving, finalising and
exporting. Change both together.
"""

QTY = 'QTY'
VALUE = 'VALUE'


def unit_prices(mrp, dtr_pct, std_pct):
    """(dtr_basic, after_std) for one unit. Percentages are 0-100."""
    dtr = float(mrp) * (1 - float(dtr_pct) / 100.0)
    return dtr, dtr * (1 - float(std_pct) / 100.0)


def slab_for(total, slabs):
    """(slab_no, pct, next_slab) for a group total.

    `slabs` is a list of {slab_no, min_threshold, discount_pct} in any order. slab_no 0
    and pct 0 mean "below slab 1". `next_slab` is the first slab above the one reached,
    or None when the top slab is already reached.
    """
    ordered = sorted(slabs, key=lambda s: (float(s['min_threshold']), s['slab_no']))
    reached = None
    for s in ordered:
        if total + 1e-9 >= float(s['min_threshold']):
            reached = s
    nxt = next((s for s in ordered if float(s['min_threshold']) > total + 1e-9), None)
    if reached is None:
        return 0, 0.0, nxt
    return reached['slab_no'], float(reached['discount_pct']), nxt


def price_po(lines, groups, settings):
    """Price every line and summarise every scheme group touched.

    lines     [{id, sku_code, qty, mrp, gst_pct, scheme_group_id (or None)}, ...]
    groups    {group_id: {id, scheme_no, name, basis, slabs: [...]}}
    settings  {dtr_discount_pct, std_discount_pct}

    Returns {lines: {line_id: {...}}, groups: [...], totals: {...}}.
    """
    dtr_pct = float(settings['dtr_discount_pct'])
    std_pct = float(settings['std_discount_pct'])

    base = {}
    group_total = {}
    for ln in lines:
        qty = float(ln['qty'])
        dtr, after_std = unit_prices(ln['mrp'], dtr_pct, std_pct)
        base[ln['id']] = (qty, dtr, after_std)
        gid = ln.get('scheme_group_id')
        if gid is not None and gid in groups:
            g = groups[gid]
            amount = qty if g['basis'] == QTY else after_std * qty
            group_total[gid] = group_total.get(gid, 0.0) + amount

    group_pct = {}
    summaries = []
    for gid, total in group_total.items():
        g = groups[gid]
        slab_no, pct, nxt = slab_for(total, g['slabs'])
        group_pct[gid] = pct
        summaries.append({
            'scheme_group_id': gid,
            'scheme_no': g['scheme_no'],
            'name': g['name'],
            'basis': g['basis'],
            'total': total,
            'slab_no': slab_no,
            'slab_count': len(g['slabs']),
            'slabs': sorted(({'slab_no': s['slab_no'], 'min_threshold': float(s['min_threshold']),
                              'discount_pct': float(s['discount_pct'])} for s in g['slabs']),
                            key=lambda s: (s['min_threshold'], s['slab_no'])),
            'scheme_pct': pct,
            'next_slab_no': nxt['slab_no'] if nxt else None,
            'next_threshold': float(nxt['min_threshold']) if nxt else None,
            'next_pct': float(nxt['discount_pct']) if nxt else None,
            'gap': (float(nxt['min_threshold']) - total) if nxt else None,
            'line_count': 0,
            'value': 0.0,
            'saving': 0.0,
        })
    by_gid = {s['scheme_group_id']: s for s in summaries}

    out = {}
    totals = {'line_count': 0, 'qty': 0.0, 'mrp_value': 0.0, 'pre_scheme_value': 0.0,
              'value': 0.0, 'gst': 0.0, 'grand_total': 0.0, 'scheme_saving': 0.0}
    for ln in lines:
        qty, dtr, after_std = base[ln['id']]
        gid = ln.get('scheme_group_id')
        # A finalised PO carries its scheme % frozen on the line instead of a live group.
        fixed = ln.get('fixed_scheme_pct')
        pct = float(fixed) if fixed is not None else group_pct.get(gid, 0.0)
        landing = after_std * (1 - pct / 100.0)
        value = landing * qty
        gst = value * float(ln['gst_pct']) / 100.0
        saving = (after_std - landing) * qty
        out[ln['id']] = {
            'dtr_basic': dtr,
            'after_std': after_std,
            'scheme_pct': pct,
            'landing': landing,
            'pre_scheme_value': after_std * qty,
            'line_value': value,
            'gst': gst,
            'line_total': value + gst,
            'scheme_saving': saving,
        }
        if gid in by_gid:
            s = by_gid[gid]
            s['line_count'] += 1
            s['value'] += value
            s['saving'] += saving
        totals['line_count'] += 1
        totals['qty'] += qty
        totals['mrp_value'] += float(ln['mrp']) * qty
        totals['pre_scheme_value'] += after_std * qty
        totals['value'] += value
        totals['gst'] += gst
        totals['grand_total'] += value + gst
        totals['scheme_saving'] += saving

    summaries.sort(key=lambda s: _scheme_sort_key(s['scheme_no']))
    return {'lines': out, 'groups': summaries, 'totals': totals}


def _scheme_sort_key(scheme_no):
    """SG2 before SG10."""
    digits = ''.join(ch for ch in str(scheme_no) if ch.isdigit())
    return (int(digits) if digits else 10**9, str(scheme_no))
