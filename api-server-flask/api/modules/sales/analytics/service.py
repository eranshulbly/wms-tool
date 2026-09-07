# -*- encoding: utf-8 -*-
"""
Sales-executive activity analytics — what the field team did, and what it produced.

Three independent record trails answer that, and they are deliberately kept apart
rather than folded into one number:

  dealer_visits     where the executive was and for how long (the app's check-in)
  submitted_orders  what they raised while there
  invoice           what was actually billed, attributed dealer -> sales_executive_id

They are joined per executive in Python rather than in one SQL statement: a single
query joining visits to orders multiplies one against the other, and an executive
with 9 visits and 3 orders would report 27 of each.

Time on site
────────────
Duration is check_out_at - check_in_at, and it is only as good as the check-out.
The app allows one active visit at a time, so an executive who forgets to check out
stays "in" the shop until they next check in somewhere — which can be days later.
Those visits are counted but their minutes are held separately (`suspect_visits`)
instead of being added to the total, because one forgotten check-out is worth more
than every real visit combined and would silently become the headline figure.
"""

from api.shared.db_manager import mysql_manager
from api.permissions import company_filter_sql

# A visit longer than a working day is a forgotten check-out, not time in a shop.
# Kept generous: a genuine long day should still be counted, only the absurd excluded.
LONG_VISIT_MINUTES = 8 * 60

# Sales figures come from invoices, matching what the mobile app shows the executive
# in their own summary (field_sales.exec_invoice_summary). A cancelled invoice is not
# a sale, so it is excluded from both.
_INVOICE_LIVE = "i.cancellation_date IS NULL"


def _num(v):
    """MySQL SUM/AVG return Decimal; the client gets plain numbers."""
    if v is None:
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _iso(v):
    return v.isoformat() if hasattr(v, 'isoformat') else v


def _range_clause(column, date_from, date_to):
    """Half-open range on a DATETIME column, with `date_to` inclusive.

    `col < date_to + 1 day` rather than `DATE(col) <= date_to` so the index on the
    column is still usable — wrapping it in DATE() would force a full scan.
    """
    sql, params = [], []
    if date_from:
        sql.append(f"{column} >= %s")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql.append(f"{column} < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(date_to)
    return sql, params


def _visit_rows(company_ids, date_from, date_to, user_id=None):
    where, params = ["1=1"], []
    cf_sql, cf_params = company_filter_sql(company_ids, alias='v')
    where.append(cf_sql)
    params.extend(cf_params)
    rng_sql, rng_params = _range_clause('v.check_in_at', date_from, date_to)
    where.extend(rng_sql)
    params.extend(rng_params)
    if user_id:
        where.append("v.user_id = %s")
        params.append(int(user_id))

    return mysql_manager.execute_query(
        f"""SELECT v.visit_id, v.user_id, v.dealer_id, v.company_id,
                   u.name  AS executive_name,
                   d.name  AS dealer_name, d.town, d.address,
                   v.check_in_at, v.check_out_at, v.status, v.notes,
                   v.check_in_latitude, v.check_in_longitude, v.check_in_accuracy_m,
                   v.check_out_latitude, v.check_out_longitude,
                   TIMESTAMPDIFF(MINUTE, v.check_in_at, v.check_out_at) AS minutes
              FROM dealer_visits v
              LEFT JOIN users  u ON u.id        = v.user_id
              LEFT JOIN dealer d ON d.dealer_id = v.dealer_id
             WHERE {' AND '.join(where)}
             ORDER BY v.check_in_at DESC""",
        tuple(params)) or []


def visit_log(company_ids, date_from=None, date_to=None, user_id=None):
    """Every visit in range, newest first — the "where and when" detail table."""
    rows = []
    for r in _visit_rows(company_ids, date_from, date_to, user_id):
        minutes = r['minutes']
        suspect = minutes is not None and minutes > LONG_VISIT_MINUTES
        rows.append({
            'visit_id':        r['visit_id'],
            'user_id':         r['user_id'],
            'executive_name':  r['executive_name'] or f"User {r['user_id']}",
            'dealer_id':       r['dealer_id'],
            'dealer_name':     r['dealer_name'] or f"Dealer {r['dealer_id']}",
            'town':            r['town'],
            'address':         r['address'],
            'check_in_at':     _iso(r['check_in_at']),
            'check_out_at':    _iso(r['check_out_at']),
            'minutes':         minutes,
            # Distinguishes "still in the shop" from "never checked out": the first is
            # a visit in progress, the second is a duration nobody should trust.
            'open':            r['check_out_at'] is None,
            'suspect':         suspect,
            'status':          r['status'],
            'notes':           r['notes'],
            'check_in_lat':    float(r['check_in_latitude'])  if r['check_in_latitude']  is not None else None,
            'check_in_lng':    float(r['check_in_longitude']) if r['check_in_longitude'] is not None else None,
            'accuracy_m':      float(r['check_in_accuracy_m']) if r['check_in_accuracy_m'] is not None else None,
        })
    return rows


def _order_stats(company_ids, date_from, date_to):
    """Orders raised in the app, per executive who raised them.

    Line value is net_rate x quantity. net_rate is NULL on the standard flow — nobody
    priced the line — so `valued_lines` reports how much of the total is actually
    backed by a rate. A value of 0 across 12 orders means unpriced, not given away.
    """
    where, params = ["1=1"], []
    cf_sql, cf_params = company_filter_sql(company_ids, alias='so')
    where.append(cf_sql)
    params.extend(cf_params)
    rng_sql, rng_params = _range_clause('so.created_at', date_from, date_to)
    where.extend(rng_sql)
    params.extend(rng_params)

    rows = mysql_manager.execute_query(
        f"""SELECT so.created_by AS user_id,
                   COUNT(DISTINCT so.submitted_order_id) AS orders,
                   COUNT(DISTINCT so.dealer_id)          AS order_dealers,
                   COALESCE(SUM(l.net_rate * l.quantity), 0) AS order_value,
                   SUM(l.net_rate IS NOT NULL)           AS valued_lines,
                   COUNT(l.submitted_order_product_id)   AS total_lines
              FROM submitted_orders so
              LEFT JOIN submitted_order_products l
                     ON l.submitted_order_id = so.submitted_order_id
             WHERE {' AND '.join(where)}
             GROUP BY so.created_by""",
        tuple(params)) or []
    return {r['user_id']: r for r in rows}


def _invoice_stats(company_ids, date_from, date_to):
    """Billed sales per executive, attributed invoice -> dealer -> sales_executive_id.

    An invoice whose dealer has no executive belongs to nobody and is counted for
    nobody, which is the same rule the executive's own app summary follows.
    """
    where, params = [_INVOICE_LIVE, "d.sales_executive_id IS NOT NULL"], []
    cf_sql, cf_params = company_filter_sql(company_ids, alias='i')
    where.append(cf_sql)
    params.extend(cf_params)
    rng_sql, rng_params = _range_clause('i.invoice_date', date_from, date_to)
    where.extend(rng_sql)
    params.extend(rng_params)

    rows = mysql_manager.execute_query(
        f"""SELECT d.sales_executive_id AS user_id,
                   COUNT(*) AS invoices,
                   COALESCE(SUM(i.total_invoice_amount), 0) AS invoiced_sales
              FROM invoice i
              JOIN dealer d ON d.dealer_id = i.dealer_id
             WHERE {' AND '.join(where)}
             GROUP BY d.sales_executive_id""",
        tuple(params)) or []
    return {r['user_id']: r for r in rows}


def _known_executives(company_ids):
    """Everyone on the team, so a rep who did nothing still appears with zeros.

    A summary built only from activity cannot show inactivity, which is exactly what
    a manager is looking for.
    """
    where, params = ["u.role = 'sales_executive'"], []
    cf_sql, cf_params = company_filter_sql(company_ids, alias='uwc')
    where.append(cf_sql)
    params.extend(cf_params)
    rows = mysql_manager.execute_query(
        f"""SELECT DISTINCT u.id AS user_id, u.name, u.status
              FROM users u
              JOIN user_warehouse_company uwc ON uwc.user_id = u.id
             WHERE {' AND '.join(where)}""",
        tuple(params)) or []
    return {r['user_id']: r for r in rows}


def executive_summary(company_ids, date_from=None, date_to=None):
    """One row per sales executive: activity, output, and what it was worth."""
    visits = _visit_rows(company_ids, date_from, date_to)
    orders = _order_stats(company_ids, date_from, date_to)
    invoiced = _invoice_stats(company_ids, date_from, date_to)
    known = _known_executives(company_ids)

    agg = {}
    for uid, row in known.items():
        agg[uid] = {'user_id': uid, 'executive_name': row['name'] or f"User {uid}",
                    'active': (row['status'] or 'active') == 'active',
                    'visits': 0, 'dealers': set(), 'open_visits': 0,
                    'minutes': 0, 'counted_visits': 0, 'suspect_visits': 0,
                    'first_seen': None, 'last_seen': None}

    for v in visits:
        uid = v['user_id']
        a = agg.setdefault(uid, {
            'user_id': uid, 'executive_name': v['executive_name'] or f"User {uid}",
            'active': True, 'visits': 0, 'dealers': set(), 'open_visits': 0,
            'minutes': 0, 'counted_visits': 0, 'suspect_visits': 0,
            'first_seen': None, 'last_seen': None})
        a['visits'] += 1
        a['dealers'].add(v['dealer_id'])
        minutes = v['minutes']
        if v['check_out_at'] is None:
            a['open_visits'] += 1
        elif minutes is not None and minutes > LONG_VISIT_MINUTES:
            a['suspect_visits'] += 1
        elif minutes is not None:
            a['minutes'] += minutes
            a['counted_visits'] += 1

        ci = v['check_in_at']
        if ci is not None:
            if a['first_seen'] is None or ci < a['first_seen']:
                a['first_seen'] = ci
            if a['last_seen'] is None or ci > a['last_seen']:
                a['last_seen'] = ci

    out = []
    for uid, a in agg.items():
        o = orders.get(uid) or {}
        i = invoiced.get(uid) or {}
        counted = a['counted_visits']
        out.append({
            'user_id':         uid,
            'executive_name':  a['executive_name'],
            'active':          a['active'],
            'visits':          a['visits'],
            'dealers_visited': len(a['dealers']),
            'open_visits':     a['open_visits'],
            'minutes_on_site': a['minutes'],
            'avg_minutes':     round(a['minutes'] / counted) if counted else None,
            # Visits whose duration is not trustworthy. Shown, not hidden: it is a
            # coaching point about using the app, and it explains why the total is
            # lower than the raw check-in/check-out spread.
            'suspect_visits':  a['suspect_visits'],
            'orders':          int(o.get('orders') or 0),
            'order_dealers':   int(o.get('order_dealers') or 0),
            'order_value':     _num(o.get('order_value')),
            'valued_lines':    int(o.get('valued_lines') or 0),
            'total_lines':     int(o.get('total_lines') or 0),
            'invoices':        int(i.get('invoices') or 0),
            'invoiced_sales':  _num(i.get('invoiced_sales')),
            'first_seen':      _iso(a['first_seen']),
            'last_seen':       _iso(a['last_seen']),
        })

    out.sort(key=lambda r: (-r['visits'], -r['invoiced_sales'], r['executive_name']))
    return out
