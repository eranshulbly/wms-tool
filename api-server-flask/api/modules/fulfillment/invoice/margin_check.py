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

A batch number is only guaranteed unique WITHIN one product — sku_batch.batch_hash is
(sku_id, batch_number), not batch_number alone (see ingestion/service.py:batch_hash) —
so the same printed text can genuinely belong to two different products, and does: e.g.
"MP26056" or "JKBD26062" on this company's own data. In every real case found so far
that's because the catalogue holds two rows for what is really one product — a name
typo ("CIPRODAC-500 TABLET" vs "...TAABLET") meant a later feed couldn't match the
existing product by name and created a new one instead, and that new row went on to
receive its own stock under a batch number that happens to coincide with the original's.
Treating the batch number alone as a lookup key (the previous version of this module did)
either wrongly calls a line "ambiguous" when the real product is obvious from its printed
name, or — worse, and silently — attributes the wrong product's cost to a line whenever
the two candidates' costs happen to agree. _costs_by_batch keeps every distinct product a
batch resolves to; _resolve_line_cost below is what actually picks between them.
"""

import difflib
import re

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
    """{BATCH NUMBER: [{'cost', 'master_name', 'sku_code'}, ...]}.

    One entry per distinct PRODUCT the batch number resolves to — never collapsed into
    one, since two different products can share a batch number (see module docstring).
    Only rows with a real landing price count: a credit note that arrived before its
    invoice leaves a row with landing price 0, and reading that as a cost would put a
    negative number in the margin — it is also exactly what an unstocked duplicate
    product row carries, so this filter incidentally keeps most duplicate-row collisions
    out of the picture entirely (only one candidate is ever costed, so there is nothing
    to disambiguate). It does not help when both rows actually have stock, which is
    exactly when _resolve_line_cost is needed.
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

    by_batch = {}
    for r in rows:
        cost = round(float(r['landing_price']) - float(r['cn_rate'] or 0), 4)
        opt = {'cost': cost, 'master_name': r['master_name'], 'sku_code': r['sku_code']}
        options = by_batch.setdefault(r['batch'], [])
        if opt not in options:  # same product, same cost — not a second candidate
            options.append(opt)
    return by_batch


def _norm_name(name):
    """Loose product-name key for matching an invoice's own printed description
    against the catalogue name — case/whitespace only, since the invoice never spells
    a product exactly like the master (pack size, spacing, abbreviations)."""
    return re.sub(r'\s+', ' ', (name or '').strip().upper())


def _resolve_line_cost(raw_product_name, options):
    """Which of a batch's candidate products (see _costs_by_batch) this invoice line
    actually means. Returns (option_or_None, was_multi_product).

    One candidate: unambiguous regardless of name — the normal case, and every batch
    that isn't caught up in a duplicate-product collision. More than one candidate: the
    line's own printed product name picks between them via a high-confidence fuzzy
    match — the same difflib.get_close_matches/0.85-cutoff idiom already used for the
    product-master upload's category matching (sales/uploads/router.py), which resolves
    a clear near-miss (a typo'd duplicate row, the cause behind every real collision
    seen so far) and refuses to guess between two names that are actually different.
    Two candidates sharing the exact same printed name can't be told apart by name at
    all and are always left ambiguous, never silently picked.
    """
    if not options:
        return None, False
    if len(options) == 1:
        return options[0], False

    by_key, collided = {}, set()
    for o in options:
        key = _norm_name(o['master_name'])
        if key in by_key:
            collided.add(key)
        by_key[key] = o

    target = _norm_name(raw_product_name)
    close = difflib.get_close_matches(target, list(by_key), n=1, cutoff=0.85)
    if close and close[0] not in collided:
        return by_key[close[0]], True
    return None, True


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
    collision_warnings = []  # one per (batch, printed name) actually seen on this invoice
    for l in doc['lines']:
        qty = float(l['quantity'] or 0)
        sale_rate = float(l['rate']) if qty else None
        batch_key = (l['raw_batch'] or '').strip().upper()
        options = costs.get(batch_key, [])
        match, was_multi = _resolve_line_cost(l['raw_product_name'], options)

        if not options:
            status, cost = 'no_cost', None
        elif match is None:
            status, cost = 'ambiguous', None
        else:
            status, cost = 'ok', match['cost']

        if was_multi:
            others = ', '.join(sorted({o['master_name'] for o in options}
                                      - ({match['master_name']} if match else set())))
            note = (f"line {l['line_no']}: batch {l['raw_batch']} is also on record for "
                    f"{others}" + (f" — matched to {match['master_name']} by name"
                                    if match else " — could not tell which by name, so no cost was used"))
            collision_warnings.append(note)

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
        # Parser warnings first, then batch/product collisions — the collisions are
        # about a specific line's cost, so they read as a continuation of the same list
        # rather than a separate concern.
        'warnings': list(doc.get('warnings') or []) + collision_warnings,
    }


def totals_for(lines):
    """Sales, cost and margin over these lines, via the same arithmetic as order margins.

    Mapped onto pricing.order_totals so this screen and Manage Orders cannot disagree:
    only lines with both a selling price and a cost count toward the margin, and the
    coverage comes back with it so the page can say how much of the invoice it covers.
    """
    return order_totals([{'quantity': l['quantity'], 'net_rate': l['sale_rate'],
                          'landing_price': l['cost_rate']} for l in lines])
