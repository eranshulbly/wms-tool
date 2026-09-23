# -*- encoding: utf-8 -*-
"""
Sales report — what sold, to whom, and (where the batch is on file) at what margin.

Same source as the Order Margin tab: an invoiced order's lines live in
potential_order_product, priced at pop.net_rate and costed by the exact batch it names
(fc_sku_price_details, net of any credit note — see order/pricing.py). Grouped here by
product, by dealer, and by batch instead of by order.

invoice itself carries no product lines any more — it became a header-only record
(dealer, amount, date) in the order/invoice schema migration, which is why this reads
potential_order_product rather than invoice for line-item detail; invoice is only
consulted for "was this order actually billed" and its date.

The batch breakdown groups by pop.batch_id directly (one row per named batch, never a
mix of two) — batch_number/expiry come off sku_batch.batch_params, the same
JSON_UNQUOTE(JSON_EXTRACT(...)) idiom the ingestion batch-costing report already uses.
Lines with no batch on file (batch_id NULL) are simply absent from that view, same as
_aggregate already drops any other ungrouped id.

Everything — the summary, the product table, the dealer table, the batch table, the
trend — is built from ONE filtered line list, so none of them can disagree with each
other or with the Order Margin tab.
"""

from api.shared.db_manager import mysql_manager
from api.permissions import company_filter_sql
from api.modules.fulfillment.order.pricing import order_totals


def _date_str(v):
    if v is None:
        return None
    s = v.isoformat() if hasattr(v, 'isoformat') else str(v)
    return s[:10]


def _in_range(date_str, date_from, date_to):
    if date_str is None:
        return False
    if date_from and date_str < date_from:
        return False
    if date_to and date_str > date_to:
        return False
    return True


def _order_headers(company_ids):
    """One row per order with a live (non-cancelled) invoice: dealer + invoice date."""
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    return mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.company_id,
                   d.dealer_id, d.name AS dealer_name, d.town, d.sales_executive_id,
                   u.name AS executive_name,
                   MIN(i.invoice_number) AS invoice_number,
                   MIN(i.invoice_date)   AS invoice_date
              FROM potential_order po
              JOIN invoice i ON i.potential_order_id = po.potential_order_id
                            AND i.cancellation_date IS NULL
              LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
              LEFT JOIN users u ON u.id = d.sales_executive_id
             WHERE {cf_sql}
             GROUP BY po.potential_order_id, po.company_id, d.dealer_id, d.name,
                      d.town, d.sales_executive_id, u.name""",
        cf_params) or []


def _order_lines(order_ids):
    """Every product line of these orders, priced and costed by its named batch."""
    if not order_ids:
        return []
    ph = ','.join(['%s'] * len(order_ids))
    return mysql_manager.execute_query(
        f"""SELECT pop.potential_order_id, pop.product_id, pop.quantity, pop.net_rate,
                   pop.batch_id,
                   (fsp.landing_price - fsp.cn_rate) AS landing_price,
                   p.name AS product_name, p.product_string AS sku_code,
                   c.name AS category,
                   JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.batch_number')) AS batch_number,
                   JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.expiry')) AS expiry
              FROM potential_order_product pop
              JOIN potential_order po ON po.potential_order_id = pop.potential_order_id
              JOIN product p ON p.product_id = pop.product_id
              LEFT JOIN categories c ON c.category_id = p.category_id
              LEFT JOIN fc_sku_price_details fsp
                     ON fsp.entity_id = pop.product_id AND fsp.batch_id = pop.batch_id
                    AND fsp.company_id = po.company_id
              LEFT JOIN sku_batch b ON b.id = pop.batch_id AND b.company_id = po.company_id
             WHERE pop.potential_order_id IN ({ph})""",
        tuple(order_ids)) or []


def _aggregate(lines, key, label_fields):
    """Group `lines` by `key` (product_id or dealer_id), one summary row per group."""
    groups = {}
    for l in lines:
        gid = l.get(key)
        if gid is None:
            continue
        groups.setdefault(gid, []).append(l)

    out = []
    for gid, group_lines in groups.items():
        t = order_totals(group_lines)
        first = group_lines[0]
        row = {'id': gid, **{f: first.get(f) for f in label_fields}}
        row['orders'] = len({l['potential_order_id'] for l in group_lines})
        row['lines'] = t['lines']
        row['costed_lines'] = t['costed_lines']
        row['quantity'] = round(sum(l['quantity'] or 0 for l in group_lines), 2)
        row['revenue'] = t['order_total']
        row['landing_cost'] = t['landing_cost']
        row['margin'] = t['margin']
        row['margin_pct'] = t['margin_pct']
        row['avg_rate'] = (round(row['revenue'] / row['quantity'], 2)
                           if row['revenue'] and row['quantity'] else None)
        dates = [l['invoice_date'] for l in group_lines if l['invoice_date']]
        row['last_sale'] = max(dates) if dates else None
        # Breadth: how many distinct counterpart entities this group reached — a product
        # (or a single batch of it) sold to one dealer 1000 times tells a different story
        # than one sold to 20. Dealer groups get the inverse: how many products they buy.
        if key == 'dealer_id':
            row['products_bought'] = len({l['product_id'] for l in group_lines})
        else:
            row['dealers_reached'] = len({l['dealer_id'] for l in group_lines
                                          if l['dealer_id'] is not None})
        out.append(row)

    out.sort(key=lambda r: -(r['revenue'] or 0))
    return out


def _monthly_trend(lines):
    months = {}
    for l in lines:
        if not l['invoice_date']:
            continue
        months.setdefault(l['invoice_date'][:7], []).append(l)

    out = []
    for month, group_lines in sorted(months.items()):
        t = order_totals(group_lines)
        out.append({
            'month': month,
            'revenue': t['order_total'],
            'margin': t['margin'],
            'quantity': round(sum(l['quantity'] or 0 for l in group_lines), 2),
            'orders': len({l['potential_order_id'] for l in group_lines}),
        })
    return out


def sales_report(company_ids, date_from=None, date_to=None, product_ids=None, dealer_ids=None):
    """Product, dealer, and batch sales breakdowns over invoiced orders in range.

    product_ids / dealer_ids narrow the report to those entities — applied after the
    date window, so `*_options` (the full picklist for the filter dropdowns) reflects
    everything the date range has, not just what survived the OTHER filter. Margin is
    never recomputed client-side (see order_margin.py's own note on this): a product
    or dealer filter is just a narrower `lines` list fed through the same order_totals
    the unfiltered report uses, so a filtered view can never disagree with what it
    would show unfiltered.

    `lines` comes back too — the raw, filtered line list — so the UI can drill a
    product down to the dealers who bought it (or a dealer down to what they bought)
    entirely client-side, without a second round trip per click.
    """
    headers = _order_headers(company_ids)
    if not headers:
        empty = order_totals([])
        return {'summary': empty, 'products': [], 'dealers': [], 'batches': [], 'trend': [],
                'lines': [], 'order_count': 0, 'dealer_count': 0, 'product_count': 0,
                'batch_count': 0, 'product_options': [], 'dealer_options': []}

    header_by_id = {h['potential_order_id']: h for h in headers}
    raw_lines = _order_lines(list(header_by_id))

    date_filtered = []
    for l in raw_lines:
        h = header_by_id.get(l['potential_order_id'])
        if not h:
            continue
        invoice_date = _date_str(h['invoice_date'])
        if not _in_range(invoice_date, date_from, date_to):
            continue
        date_filtered.append({
            'potential_order_id': l['potential_order_id'],
            'product_id': l['product_id'],
            'product_name': l['product_name'],
            'sku_code': l['sku_code'],
            'category': l['category'],
            'batch_id': l['batch_id'],
            'batch_number': l['batch_number'],
            'expiry': l['expiry'],
            'quantity': float(l['quantity']) if l['quantity'] is not None else 0.0,
            'net_rate': float(l['net_rate']) if l['net_rate'] is not None else None,
            'landing_price': (float(l['landing_price'])
                              if l['landing_price'] is not None else None),
            'invoice_date': invoice_date,
            'dealer_id': h['dealer_id'],
            'dealer_name': h['dealer_name'] or (
                f"Dealer {h['dealer_id']}" if h['dealer_id'] else 'Unknown dealer'),
            'town': h['town'],
            'executive_name': h['executive_name'],
        })

    product_options = sorted(
        {(l['product_id'], l['product_name'], l['sku_code']) for l in date_filtered},
        key=lambda x: (x[1] or ''))
    dealer_options = sorted(
        {(l['dealer_id'], l['dealer_name'], l['town']) for l in date_filtered
         if l['dealer_id'] is not None},
        key=lambda x: (x[1] or ''))

    lines = date_filtered
    if product_ids:
        wanted_p = set(product_ids)
        lines = [l for l in lines if l['product_id'] in wanted_p]
    if dealer_ids:
        wanted_d = set(dealer_ids)
        lines = [l for l in lines if l['dealer_id'] in wanted_d]

    return {
        'summary': order_totals(lines),
        'order_count': len({l['potential_order_id'] for l in lines}),
        'dealer_count': len({l['dealer_id'] for l in lines if l['dealer_id'] is not None}),
        'product_count': len({l['product_id'] for l in lines}),
        'batch_count': len({l['batch_id'] for l in lines if l['batch_id'] is not None}),
        'products': _aggregate(lines, 'product_id',
                               ('product_name', 'sku_code', 'category')),
        'dealers': _aggregate(lines, 'dealer_id',
                              ('dealer_name', 'town', 'executive_name')),
        'batches': _aggregate(lines, 'batch_id',
                              ('batch_number', 'expiry', 'product_name', 'sku_code')),
        'trend': _monthly_trend(lines),
        'lines': lines,
        'product_options': [{'id': i, 'name': n, 'sku_code': s} for i, n, s in product_options],
        'dealer_options': [{'id': i, 'name': n, 'town': t} for i, n, t in dealer_options],
    }
