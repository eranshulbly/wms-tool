# -*- encoding: utf-8 -*-
"""Order margin — what each invoiced order earned, and the running total over all of them.

Unlike margin_check.py (an ad-hoc PDF read), this reads what the app already has on
file: potential_order_product carries the batch a line actually shipped against
(uploaded with the order, see order/service.py's LINE_COLUMNS pass), and
fc_sku_price_details carries that batch's landing price. The same join
OrderDetailWithProducts (order/router.py) uses for one order's margin, run here over
every order that has a live invoice — so this screen and that one cannot disagree.

Deliberately NOT partition-pruned (see db_manager.partition_filter): the whole point of
"margin till date" is every invoiced order on file, not just the last
PARTITION_WINDOW_MONTHS. Costs more to scan; that is the trade this screen asks for.
"""

from api.shared.db_manager import mysql_manager
from api.permissions import company_filter_sql
from api.modules.fulfillment.order.pricing import order_totals


def _date_str(v):
    """DATE/DATETIME -> 'YYYY-MM-DD', so display and range comparison use one form."""
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
    """One row per order that has at least one live (non-cancelled) invoice on file."""
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    return mysql_manager.execute_query(
        f"""SELECT po.potential_order_id, po.original_order_id, po.order_date, po.status,
                   po.company_id, d.dealer_id, d.name AS dealer_name,
                   MIN(i.invoice_number) AS invoice_number,
                   MIN(i.invoice_date)   AS invoice_date
              FROM potential_order po
              JOIN invoice i ON i.potential_order_id = po.potential_order_id
                            AND i.cancellation_date IS NULL
              LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
             WHERE {cf_sql}
             GROUP BY po.potential_order_id, po.original_order_id, po.order_date,
                      po.status, po.company_id, d.dealer_id, d.name""",
        cf_params) or []


def _order_lines(order_ids):
    """Every product line of these orders, costed by the exact batch it names.

    Lines whose batch never priced in (no fc_sku_price_details row) come back with
    landing_price NULL — order_totals() then leaves them out of the margin instead of
    costing them at nothing.

    landing_price is net of cn_rate, same as margin_check.py: a credit note against the
    same receipt lowers what the batch actually cost, so the raw GRN rate alone
    overstates cost and understates margin — which is exactly why this screen and
    Margin Check disagreed on the same invoice before this was added.
    """
    if not order_ids:
        return []
    ph = ','.join(['%s'] * len(order_ids))
    return mysql_manager.execute_query(
        f"""SELECT pop.potential_order_id, pop.product_id, pop.quantity, pop.net_rate,
                   (fsp.landing_price - fsp.cn_rate) AS landing_price,
                   p.name AS product_name, p.product_string AS sku_code
              FROM potential_order_product pop
              JOIN potential_order po ON po.potential_order_id = pop.potential_order_id
              JOIN product p ON p.product_id = pop.product_id
              LEFT JOIN fc_sku_price_details fsp
                     ON fsp.entity_id = pop.product_id AND fsp.batch_id = pop.batch_id
                    AND fsp.company_id = po.company_id
             WHERE pop.potential_order_id IN ({ph})""",
        tuple(order_ids)) or []


def _order_header(order_id):
    """One order's identity + invoice info, or None if it has no live invoice."""
    rows = mysql_manager.execute_query(
        """SELECT po.potential_order_id, po.original_order_id, po.order_date, po.status,
                  po.company_id, d.dealer_id, d.name AS dealer_name,
                  MIN(i.invoice_number) AS invoice_number,
                  MIN(i.invoice_date)   AS invoice_date
             FROM potential_order po
             JOIN invoice i ON i.potential_order_id = po.potential_order_id
                           AND i.cancellation_date IS NULL
             LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
            WHERE po.potential_order_id = %s
            GROUP BY po.potential_order_id, po.original_order_id, po.order_date,
                     po.status, po.company_id, d.dealer_id, d.name""",
        (order_id,))
    return rows[0] if rows else None


def _order_line_detail(order_id):
    """Every line of one order, with the batch number so a product can be traced."""
    return mysql_manager.execute_query(
        """SELECT pop.potential_order_product_id, pop.product_id, pop.quantity, pop.net_rate,
                  (fsp.landing_price - fsp.cn_rate) AS landing_price,
                  p.name AS product_name, p.product_string AS sku_code,
                  JSON_UNQUOTE(JSON_EXTRACT(sb.batch_params, '$.batch_number')) AS batch_number
             FROM potential_order_product pop
             JOIN potential_order po ON po.potential_order_id = pop.potential_order_id
             JOIN product p ON p.product_id = pop.product_id
             LEFT JOIN fc_sku_price_details fsp
                    ON fsp.entity_id = pop.product_id AND fsp.batch_id = pop.batch_id
                   AND fsp.company_id = po.company_id
             LEFT JOIN sku_batch sb ON sb.id = pop.batch_id
            WHERE pop.potential_order_id = %s
            ORDER BY pop.potential_order_product_id""",
        (order_id,)) or []


def order_margin_detail(company_ids, order_id):
    """Product-level margin for one invoiced order — the popup behind a row.

    Returns None for an order with no live invoice, or one outside `company_ids`
    (treated by the caller as "not found" rather than 403, so a scoped admin cannot
    probe for another tenant's order ids).
    """
    header = _order_header(order_id)
    if not header:
        return None
    if company_ids is not None and header['company_id'] not in company_ids:
        return None

    rows = _order_line_detail(order_id)
    lines = []
    for r in rows:
        qty = float(r['quantity'] or 0)
        rate = float(r['net_rate']) if r['net_rate'] is not None else None
        cost = float(r['landing_price']) if r['landing_price'] is not None else None
        margin_rate = (rate - cost) if (rate is not None and cost is not None) else None

        if margin_rate is not None:
            status = 'ok'
        elif rate is None:
            status = 'no_rate'
        else:
            status = 'no_cost'

        lines.append({
            'product_id':   r['product_id'],
            'product_name': r['product_name'],
            'sku_code':     r['sku_code'],
            'batch_number': r['batch_number'],
            'quantity':     qty,
            'sale_rate':    round(rate, 4) if rate is not None else None,
            'sale_value':   round(rate * qty, 2) if rate is not None else None,
            'cost_rate':    round(cost, 4) if cost is not None else None,
            'cost_value':   round(cost * qty, 2) if cost is not None else None,
            'margin_rate':  round(margin_rate, 4) if margin_rate is not None else None,
            'margin_value': round(margin_rate * qty, 2) if margin_rate is not None else None,
            'margin_pct':   (round(margin_rate / rate * 100, 2)
                              if margin_rate is not None and rate else None),
            'status':       status,
        })

    return {
        'potential_order_id': header['potential_order_id'],
        'order_number':       header['original_order_id'] or f"PO{order_id}",
        'dealer_name':        header['dealer_name'],
        'invoice_number':     header['invoice_number'],
        'invoice_date':       _date_str(header['invoice_date']),
        'order_date':         _date_str(header['order_date']),
        'status':             header['status'],
        'lines':              lines,
        'totals':             order_totals(rows),
    }


def order_margin_report(company_ids, date_from=None, date_to=None):
    """Margin per invoiced order (optionally windowed) plus the all-time total.

    `overall` always covers every invoiced order on file, regardless of date_from/
    date_to — that is the "till date" figure. `period_totals` is the same arithmetic
    restricted to the window, so the two can be shown side by side without the window
    ever hiding the running total.
    """
    headers = _order_headers(company_ids)
    if not headers:
        empty = order_totals([])
        return {'orders': [], 'period_totals': empty, 'overall': empty, 'order_count': 0}

    order_ids = [h['potential_order_id'] for h in headers]
    lines = _order_lines(order_ids)

    lines_by_order = {}
    for l in lines:
        lines_by_order.setdefault(l['potential_order_id'], []).append(l)

    order_rows = []
    in_window_ids = set()
    for h in headers:
        oid = h['potential_order_id']
        invoice_date = _date_str(h['invoice_date'])
        t = order_totals(lines_by_order.get(oid, []))
        order_rows.append({
            'potential_order_id': oid,
            'order_number':       h['original_order_id'] or f"PO{oid}",
            'dealer_name':        h['dealer_name'],
            'invoice_number':     h['invoice_number'],
            'invoice_date':       invoice_date,
            'order_date':         _date_str(h['order_date']),
            'status':             h['status'],
            'lines':              t['lines'],
            'priced_lines':       t['priced_lines'],
            'costed_lines':       t['costed_lines'],
            'order_total':        t['order_total'],
            'landing_cost':       t['landing_cost'],
            'margin':             t['margin'],
            'margin_pct':         t['margin_pct'],
        })
        if _in_range(invoice_date, date_from, date_to):
            in_window_ids.add(oid)

    overall = order_totals(lines)

    if date_from or date_to:
        order_rows = [r for r in order_rows if r['potential_order_id'] in in_window_ids]
        period_totals = order_totals(
            [l for oid in in_window_ids for l in lines_by_order.get(oid, [])])
    else:
        period_totals = overall

    order_rows.sort(key=lambda r: r['invoice_date'] or '', reverse=True)

    return {
        'orders': order_rows,
        'period_totals': period_totals,
        'overall': overall,
        'order_count': len(headers),
    }
