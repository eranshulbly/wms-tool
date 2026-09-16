# -*- encoding: utf-8 -*-
"""Margin check — what a Marg order invoice earns, product by product and overall.

Read-only by design: nothing about an uploaded invoice is stored. The PDF is parsed in
memory and every figure is computed on the way out, so checking an invoice never touches
stock, prices or upload history, and the same file can be checked any number of times.

    selling price  = line amount / quantity     after discount, before GST
    cost           = batch landing price less its credit-note rate, before GST
    margin         = selling price - cost

Both sides are ex-GST, so tax cannot inflate the margin. Cost is found by the batch
number printed on the line — the batch that actually shipped — which is sharper than
the FEFO inference used for orders, where the batch has to be guessed.
"""

from api.shared.db_manager import mysql_manager
from api.modules.inventory.ingestion import parser
from api.modules.inventory.ingestion.parser import ParseError
from api.modules.fulfillment.order.pricing import order_totals

# The Marg template's code for an outbound invoice. GRNs and credit/debit notes share
# the template but are not sales, so a margin on them would be meaningless.
ORDER_INVOICE = 'INVOICE'


class MarginCheckError(ValueError):
    """The file cannot be margin-checked: not a Marg order invoice, or unreadable."""


def _costs_by_batch(batch_numbers, company_id):
    """{BATCH NUMBER: {'cost', 'master_name', 'sku_code'} | {'ambiguous': True}}.

    Only rows with a real landing price count. A credit note that arrived before its
    invoice leaves a row with landing price 0 — reading that as a cost would put a
    negative number in the margin, and it is exactly what the duplicate product rows in
    the catalogue carry. With those set aside every known batch resolves to one cost.

    A batch that still carries two different costs is reported rather than averaged:
    picking one would present a guess as the margin.
    """
    wanted = sorted({(b or '').strip().upper() for b in batch_numbers if b})
    if not wanted:
        return {}
    ph = ','.join(['%s'] * len(wanted))
    rows = mysql_manager.execute_query(
        f"""SELECT UPPER(JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.batch_number'))) AS batch,
                   p.name AS master_name, p.product_string AS sku_code,
                   pr.landing_price, pr.cn_rate
              FROM sku_batch b
              JOIN fc_sku_price_details pr
                ON pr.entity_id = b.sku_id AND pr.batch_id = b.id AND pr.company_id = %s
              JOIN product p ON p.product_id = b.sku_id
             WHERE pr.batch_id > 0
               AND pr.landing_price > 0
               AND UPPER(JSON_UNQUOTE(JSON_EXTRACT(b.batch_params, '$.batch_number'))) IN ({ph})""",
        (company_id, *wanted)) or []

    found = {}
    for r in rows:
        cost = round(float(r['landing_price']) - float(r['cn_rate'] or 0), 4)
        found.setdefault(r['batch'], []).append(
            {'cost': cost, 'master_name': r['master_name'], 'sku_code': r['sku_code']})

    out = {}
    for batch, options in found.items():
        if len({o['cost'] for o in options}) > 1:
            out[batch] = {'ambiguous': True}
        else:
            out[batch] = options[0]
    return out


def check_invoice(stream, filename, company_id):
    """Margin for one Marg order invoice. Raises MarginCheckError if it cannot be read."""
    try:
        doc = parser.parse_pdf(stream, filename)
    except ParseError as e:
        raise MarginCheckError(f'not a readable Marg order invoice — {e}')

    if doc['doc_type'] != ORDER_INVOICE:
        raise MarginCheckError(
            f"this is a {doc.get('doc_title') or doc['doc_type']}, not an order invoice — "
            'margin is only meaningful on a sale')

    costs = _costs_by_batch([l['raw_batch'] for l in doc['lines']], company_id)

    lines = []
    for l in doc['lines']:
        qty = float(l['quantity'] or 0)
        sale_rate = float(l['rate']) if qty else None
        match = costs.get((l['raw_batch'] or '').strip().upper())

        if not match:
            status, cost = 'no_cost', None
        elif match.get('ambiguous'):
            status, cost = 'ambiguous', None
        else:
            status, cost = 'ok', match['cost']

        margin_rate = (sale_rate - cost) if (sale_rate is not None and cost is not None) else None
        lines.append({
            'line_no': l['line_no'],
            'product_name': l['raw_product_name'],
            'master_name': match.get('master_name') if match else None,
            'sku_code': match.get('sku_code') if match else None,
            'pack': l['raw_pack'],
            'batch': l['raw_batch'],
            'quantity': qty,
            'mrp': l['mrp'],
            'sale_rate': round(sale_rate, 4) if sale_rate is not None else None,
            'sale_value': round(sale_rate * qty, 2) if sale_rate is not None else None,
            'cost_rate': cost,
            'cost_value': round(cost * qty, 2) if cost is not None else None,
            'margin_rate': round(margin_rate, 4) if margin_rate is not None else None,
            'margin_value': round(margin_rate * qty, 2) if margin_rate is not None else None,
            'margin_pct': (round(margin_rate / sale_rate * 100, 2)
                           if margin_rate is not None and sale_rate else None),
            'status': status,
        })

    return {
        'filename': filename,
        'doc_number': doc['doc_number'],
        'doc_date': str(doc['doc_date'] or ''),
        'party_name': doc.get('party_name'),
        'grand_total': doc.get('grand_total'),
        'lines': lines,
        'totals': totals_for(lines),
        'warnings': doc.get('warnings') or [],
    }


def totals_for(lines):
    """Sales, cost and margin over these lines, via the same arithmetic as order margins.

    Mapped onto pricing.order_totals so this screen and Manage Orders cannot disagree:
    only lines with both a selling price and a cost count toward the margin, and the
    coverage comes back with it so the page can say how much of the invoice it covers.
    """
    return order_totals([{'quantity': l['quantity'], 'net_rate': l['sale_rate'],
                          'landing_price': l['cost_rate']} for l in lines])
