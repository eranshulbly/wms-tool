# -*- encoding: utf-8 -*-
"""
Sales-analytics computation — the single source of truth shared by the web
dashboards (/api/analytics/*, legacy auth) and the mobile app (/api/v1/analytics/*,
JWT auth). Both routers are thin wrappers over the functions here.

Attribution: a Busy sale (busy_sales_data) → dealer by name string-match
(dealer.name = busy_sales_data.particulars, Hero company) → executive by
dealer.sales_executive_id. Part → group/target via part_groups.

"This month" = the current calendar month. Sales targets come from
dealer.value_target and reflect only executive/dealer scoping — a part or
part-group filter narrows sales but NOT the target, so % legitimately drops when
you slice by part.
"""

from api.shared.db_manager import mysql_manager

# Attribution goes through the company's dealers. The Busy feed is loaded per company
# (see router_uploads), so every query here is scoped to one company at a time.
# DEFAULT_COMPANY is the fallback for callers that do not pass one — it is NOT a licence
# to read across tenants; routes resolve the caller's own company and pass it in.
DEFAULT_COMPANY = 1

# Every rupee figure the dashboards show is GST-INCLUSIVE. `amount` from the Busy feed is
# the net line value; `amount_with_gst` is the generated 18% gross (see schema.py). Named
# once here so no query can quietly go back to reporting net — targets are set in gross
# rupees, so measuring net against them would understate achievement by ~15%.
_SALES = "b.amount_with_gst"

_MONTH = "YEAR(b.sale_date) = YEAR(CURDATE()) AND MONTH(b.sale_date) = MONTH(CURDATE())"

# The definitive target period = the first day of the current month (a real DATE, so
# targets never collide across years). Targets are keyed by target_period = _PERIOD.
# (%% because execute_query runs `query % params`, so a literal % must be doubled.)
_PERIOD = "DATE_FORMAT(CURDATE(), '%%Y-%%m-01')"

# The part-group mapping is monthly, so each sale maps to ITS OWN month's mapping —
# this keeps multi-month period filters (last 7 days, 6 months, …) correct. For a
# single current month it is identical to joining on _PERIOD.
def _base(company_id):
    """Sales -> dealer -> part-group join, scoped to one company."""
    return (f"FROM busy_sales_data b "
            f"JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)} "
            f"LEFT JOIN part_groups pg ON pg.part_number = b.item_code "
            f"AND pg.time_period = DATE_FORMAT(b.sale_date, '%%Y-%%m-01') ")


# Named period filters for the analytics tab. Each maps to (sales-date WHERE clause,
# target-month DATE). Targets are monthly, so rolling windows measure sold-in-window
# against the CURRENT month's target; last_month uses last month's target.
def _period_window(period):
    """(sales_where_sql, target_period_sql) for a named period. Unknown -> this_month.
    (%% survives execute_query's `query % params`.)"""
    THIS = "DATE_FORMAT(CURDATE(), '%%Y-%%m-01')"
    LAST = "DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%%Y-%%m-01')"
    return {
        'last_24h':   ("b.sale_date >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)", THIS),
        'yesterday':  ("b.sale_date = DATE_SUB(CURDATE(), INTERVAL 1 DAY)", THIS),
        'last_7d':    ("b.sale_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)", THIS),
        'this_month': (_MONTH, THIS),
        'last_month': (f"(b.sale_date >= {LAST} AND b.sale_date < {THIS})", LAST),
        'last_6m':    ("b.sale_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)", THIS),
    }.get(period, (_MONTH, THIS))


# A visit longer than this is treated as a forgotten check-out and excluded from the
# average time-at-dealer, so one stale visit can't skew the number.
_VISIT_CAP_SEC = 8 * 3600


def _visit_where(period):
    """WHERE clause on dealer_visits.check_in_at for a named period (mirrors the
    sales window but on the visit's check-in time). Unknown -> this month."""
    THIS = "DATE_FORMAT(CURDATE(), '%%Y-%%m-01')"
    LAST = "DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%%Y-%%m-01')"
    this_month = "YEAR(v.check_in_at)=YEAR(CURDATE()) AND MONTH(v.check_in_at)=MONTH(CURDATE())"
    return {
        'last_24h':   "v.check_in_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)",
        'yesterday':  "DATE(v.check_in_at) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)",
        'last_7d':    "v.check_in_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)",
        'this_month': this_month,
        'last_month': f"(v.check_in_at >= {LAST} AND v.check_in_at < {THIS})",
        'last_6m':    "v.check_in_at >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)",
    }.get(period, this_month)


def _visit_stats(period, executive_id=None, dealer_id=None, company_id=DEFAULT_COMPANY):
    """Average time reps spent at dealers (from dealer_visits check-in/out) for the
    period, honouring the executive/dealer filters. Returns (by_exec, by_dealer, total)
    where each stat is {'visits': n, 'avg_min': m|None}. Only completed visits (with a
    check-out) shorter than _VISIT_CAP_SEC count toward the average."""
    conds = [_visit_where(period), f"v.company_id = {int(company_id)}", "v.check_out_at IS NOT NULL",
             f"TIMESTAMPDIFF(SECOND, v.check_in_at, v.check_out_at) BETWEEN 0 AND {_VISIT_CAP_SEC}"]
    params = []
    if executive_id:
        conds.append("v.user_id = %s"); params.append(executive_id)
    if dealer_id:
        conds.append("v.dealer_id = %s"); params.append(dealer_id)
    wc = " AND ".join(conds)
    avg_min = "ROUND(AVG(TIMESTAMPDIFF(SECOND, v.check_in_at, v.check_out_at)) / 60, 1)"

    def _fmin(v):  # MySQL AVG returns Decimal; keep None (no visits) as None.
        return float(v) if v is not None else None

    by_exec = {r['user_id']: {'visits': r['visits'], 'avg_min': _fmin(r['avg_min'])}
               for r in (mysql_manager.execute_query(
                   f"SELECT v.user_id, COUNT(*) AS visits, {avg_min} AS avg_min "
                   f"FROM dealer_visits v WHERE {wc} GROUP BY v.user_id", tuple(params)) or [])}
    by_dealer = {r['dealer_id']: {'visits': r['visits'], 'avg_min': _fmin(r['avg_min'])}
                 for r in (mysql_manager.execute_query(
                     f"SELECT v.dealer_id, COUNT(*) AS visits, {avg_min} AS avg_min "
                     f"FROM dealer_visits v WHERE {wc} GROUP BY v.dealer_id", tuple(params)) or [])}
    tot = mysql_manager.execute_query(
        f"SELECT COUNT(*) AS visits, {avg_min} AS avg_min FROM dealer_visits v WHERE {wc}",
        tuple(params))
    total = {'visits': tot[0]['visits'] if tot else 0,
             'avg_min': _fmin(tot[0]['avg_min']) if tot else None}
    return by_exec, by_dealer, total


def month_label(period='this_month'):
    """The month the figures actually cover, for the UI's period caption.

    Must follow `period`, not the wall clock: captioning last_month's numbers
    "August" while they are July's is how the dashboard ends up lying about
    which month it is showing. Rolling windows (last_7d, last_6m, …) are
    anchored to the current month, matching the target they are measured against.
    """
    # %% because execute_query runs `query % params`, so a literal % must be doubled.
    anchor = ("DATE_SUB(CURDATE(), INTERVAL 1 MONTH)" if period == 'last_month'
              else "CURDATE()")
    rows = mysql_manager.execute_query(f"SELECT DATE_FORMAT({anchor}, '%%M %%Y') AS m")
    return rows[0]['m'] if rows else ''


def sales_data_through():
    """The most recent sale_date loaded into busy_sales_data, as 'YYYY-MM-DD'.

    Sales are imported in batches, so the figures usually lag today by a few
    days. The app shows this date so a rep reading "this month" knows how
    current it actually is. None when no sales have been loaded at all.
    """
    rows = mysql_manager.execute_query(
        "SELECT MAX(sale_date) AS d FROM busy_sales_data")
    d = rows[0]['d'] if rows else None
    return d.isoformat() if d else None


def _num(v):
    """MySQL SUM returns Decimal; hand the client plain floats/ints."""
    if v is None:
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _pct(sales, target):
    """% of target achieved, or None when there is no target to measure against."""
    if not target:
        return None
    return round(float(sales) / float(target) * 100, 1)


def _where(sales_where, executive_id=None, dealer_id=None, part_group=None, part=None):
    """Build the WHERE (period window + any of the 4 optional filters) and its params."""
    where, params = [sales_where], []
    if executive_id:
        where.append("d.sales_executive_id = %s"); params.append(executive_id)
    if dealer_id:
        where.append("d.dealer_id = %s"); params.append(dealer_id)
    if part:
        where.append("b.item_code = %s"); params.append(part)
    if part_group:
        where.append("COALESCE(pg.part_group, '(Unmapped)') = %s"); params.append(part_group)
    return " AND ".join(where), tuple(params)


def sales_explorer(executive_id=None, dealer_id=None, part_group=None, part=None, company_id=DEFAULT_COMPANY,
                   period='this_month'):
    """Filtered sales analytics: summary + breakdowns by executive / dealer / part
    group / part. `period` selects the sales-date window (this_month, last_month,
    last_7d, last_24h, yesterday, last_6m). Targets respect only executive/dealer
    scoping (see module doc)."""
    sales_where, target_period = _period_window(period)
    where, params = _where(sales_where, executive_id, dealer_id, part_group, part)

    summary = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM({_SALES}),0) AS sales, COALESCE(SUM(b.quantity),0) AS qty,
                   COUNT(DISTINCT b.item_code) AS parts,
                   COUNT(DISTINCT d.dealer_id) AS selling_dealers,
                   COUNT(DISTINCT d.sales_executive_id) AS executives
            {_base(company_id)} WHERE {where}""", params)[0]

    # How many dealers are in scope is a property of the SCOPE, not of the sales inside
    # it: a dealer that bought nothing this period is still one of the executive's
    # dealers. Counting it off the sales join (an INNER join from busy_sales_data) made
    # the card read 0 for any period with no sales loaded yet — an executive with 52
    # dealers appeared to have none. So it is counted from `dealer` instead, honouring
    # only the dealer-scoping filters; part / part-group narrow the sales, not the
    # dealer list, exactly as they already behave for targets.
    dcwhere = [f"d.company_id = {int(company_id)}"]
    dcparams = []
    if executive_id:
        dcwhere.append("d.sales_executive_id = %s"); dcparams.append(executive_id)
    if dealer_id:
        dcwhere.append("d.dealer_id = %s"); dcparams.append(dealer_id)
    dealer_count = (mysql_manager.execute_query(
        f"SELECT COUNT(*) AS n FROM dealer d WHERE {' AND '.join(dcwhere)}",
        tuple(dcparams)) or [{'n': 0}])[0]['n']

    by_executive = mysql_manager.execute_query(
        f"""SELECT u.id AS user_id, u.name,
                   SUM({_SALES}) AS sales, SUM(b.quantity) AS qty
            {_base(company_id)} JOIN users u ON u.id = d.sales_executive_id
            WHERE {where}
            GROUP BY u.id, u.name ORDER BY sales DESC""", params) or []

    by_dealer = mysql_manager.execute_query(
        f"""SELECT d.dealer_id, d.name AS dealer,
                   SUM({_SALES}) AS sales, SUM(b.quantity) AS qty
            {_base(company_id)} WHERE {where}
            GROUP BY d.dealer_id, d.name ORDER BY sales DESC""", params) or []

    by_part_group = mysql_manager.execute_query(
        f"""SELECT COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                   SUM(b.quantity) AS qty, SUM({_SALES}) AS sales,
                   COUNT(DISTINCT b.item_code) AS parts
            {_base(company_id)} WHERE {where}
            GROUP BY COALESCE(pg.part_group, '(Unmapped)') ORDER BY qty DESC""", params) or []

    by_part = mysql_manager.execute_query(
        f"""SELECT b.item_code, MAX(pg.description) AS description,
                   MAX(pg.part_group) AS part_group,
                   SUM(b.quantity) AS qty, SUM({_SALES}) AS sales
            {_base(company_id)} WHERE {where}
            GROUP BY b.item_code ORDER BY qty DESC""", params) or []

    # Part-group quantity targets are per dealer (dealer_part_group_target). For the
    # current scope they sum over the dealers in view (executive/dealer filters) — like
    # the rupee targets, a part / part-group filter narrows sold qty, not the target.
    gwhere = [f"d.company_id = {int(company_id)}", f"dpg.target_period = {target_period}"]
    gparams = []
    if executive_id:
        gwhere.append("d.sales_executive_id = %s"); gparams.append(executive_id)
    if dealer_id:
        gwhere.append("d.dealer_id = %s"); gparams.append(dealer_id)
    group_target = {r['part_group']: r['t'] for r in (mysql_manager.execute_query(
        f"""SELECT dpg.part_group, COALESCE(SUM(dpg.target_qty),0) AS t
            FROM dealer_part_group_target dpg
            JOIN dealer d ON d.dealer_id = dpg.dealer_id
            WHERE {' AND '.join(gwhere)}
            GROUP BY dpg.part_group""", tuple(gparams)) or [])}

    # Rupee targets come from dealer_money_target for THIS period. They honour only the
    # dealer-scoping filters (executive / dealer), never part / part-group.
    #
    # Targets are held PER CATEGORY (dealer_money_target rows naming a category).
    # A dealer's own target is the sum of its categories, and an executive's is the
    # sum across their dealers — there is no separate whole-dealer row to read, and
    # summing indiscriminately would double-count if one were reintroduced.
    dwhere = [f"d.company_id = {int(company_id)}", "d.sales_executive_id IS NOT NULL",
              f"mt.target_period = {target_period}", "mt.category_id IS NOT NULL"]
    dparams = []
    if executive_id:
        dwhere.append("d.sales_executive_id = %s"); dparams.append(executive_id)
    if dealer_id:
        dwhere.append("d.dealer_id = %s"); dparams.append(dealer_id)
    dclause = " AND ".join(dwhere)
    dealer_target = {r['dealer_id']: r['t'] for r in (mysql_manager.execute_query(
        f"""SELECT d.dealer_id, COALESCE(SUM(mt.value_target),0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE {dclause} GROUP BY d.dealer_id""", tuple(dparams)) or [])}
    exec_target = {r['sales_executive_id']: r['t'] for r in (mysql_manager.execute_query(
        f"""SELECT d.sales_executive_id, COALESCE(SUM(mt.value_target),0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE {dclause} GROUP BY d.sales_executive_id""", tuple(dparams)) or [])}

    # Target tracker: every quantity target for this period vs the qty sold AGAINST IT.
    #
    # A target is set at one of three levels and the row says which by what it leaves
    # blank (mirroring how the mobile app groups suggestions — see the web's
    # suggestionGrouping.js):
    #
    #   part_group <> ''                  -> part-group level  (scheme is usually 'PG')
    #   part_group  = '', scheme <> ''    -> scheme level      (Basket 1/2, Chainsets, …)
    #   part_group  = '', scheme  = ''    -> category level    (e.g. all of Oil)
    #
    # Each level has to be measured against the sales that roll up to IT: matching only
    # on part_group would leave every scheme- and category-level target sitting at zero
    # sold, which reads as "sold nothing" rather than "measured at a different level".
    # The sales CTE therefore carries all three keys and the join picks the one the
    # target is defined by.
    dgwhere = [f"d.company_id = {int(company_id)}", f"dpg.target_period = {target_period}"]
    dgparams = []
    if executive_id:
        dgwhere.append("d.sales_executive_id = %s"); dgparams.append(executive_id)
    if dealer_id:
        dgwhere.append("dpg.dealer_id = %s"); dgparams.append(dealer_id)
    if part_group:
        dgwhere.append("dpg.part_group = %s"); dgparams.append(part_group)
    by_dealer_group = mysql_manager.execute_query(
        f"""WITH sales AS (
                SELECT d2.dealer_id AS dealer_id,
                       COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                       COALESCE(pg.scheme, '') AS scheme,
                       p.category_id AS category_id,
                       b.quantity AS quantity
                FROM busy_sales_data b
                JOIN dealer d2 ON d2.name = b.particulars AND d2.company_id = {int(company_id)}
                LEFT JOIN part_groups pg ON pg.part_number = b.item_code
                    AND pg.time_period = DATE_FORMAT(b.sale_date, '%%Y-%%m-01')
                LEFT JOIN product p ON p.product_string = b.item_code
                    AND p.company_id = {int(company_id)}
                WHERE {sales_where}
            )
            SELECT dpg.id, dpg.dealer_id, d.name AS dealer, dpg.part_group, dpg.scheme,
                   dpg.category_id, c.name AS category, dpg.target_qty,
                   CASE WHEN dpg.part_group <> '' THEN 'part_group'
                        WHEN dpg.scheme <> ''     THEN 'scheme'
                        ELSE 'category' END AS level,
                   COALESCE(SUM(s.quantity), 0) AS sold
            FROM dealer_part_group_target dpg
            JOIN dealer d ON d.dealer_id = dpg.dealer_id
            LEFT JOIN categories c ON c.category_id = dpg.category_id
            LEFT JOIN sales s ON s.dealer_id = dpg.dealer_id AND (
                    (dpg.part_group <> '' AND s.part_group = dpg.part_group)
                 OR (dpg.part_group  = '' AND dpg.scheme <> '' AND s.scheme = dpg.scheme)
                 OR (dpg.part_group  = '' AND dpg.scheme  = ''
                     AND s.category_id = dpg.category_id))
            WHERE {' AND '.join(dgwhere)}
            GROUP BY dpg.id, dpg.dealer_id, d.name, dpg.part_group, dpg.scheme,
                     dpg.category_id, c.name, dpg.target_qty
            ORDER BY d.name, level, dpg.scheme, dpg.part_group""", tuple(dgparams)) or []

    # Average time reps spent at dealers this period (dealer_visits check-in/out).
    visit_exec, visit_dealer, visit_total = _visit_stats(
        period, executive_id, dealer_id, company_id=company_id)

    return {
        'success': True,
        'month': month_label(period),
        'period': period,
        'data_through': sales_data_through(),
        'summary': {
            'total_sales': _num(summary['sales']), 'total_qty': _num(summary['qty']),
            'parts': summary['parts'],
            # Every dealer in scope; `selling_dealers` is the subset that actually
            # bought in the period, kept so the UI can show "52 (51 active)".
            'dealers': dealer_count,
            'selling_dealers': summary['selling_dealers'],
            'executives': summary['executives'],
            'visits': visit_total['visits'],
            'avg_visit_minutes': visit_total['avg_min'],
        },
        'by_dealer_group': [{
            'dealer_id': r['dealer_id'], 'dealer': r['dealer'],
            'part_group': r['part_group'], 'scheme': r['scheme'],
            'category_id': r['category_id'], 'category': r['category'],
            # 'part_group' | 'scheme' | 'category' — what this target is set at, so the
            # UI can label it instead of showing a blank part-group column.
            'level': r['level'],
            # The thing the target is actually on, whatever its level.
            'target_of': (r['part_group'] or r['scheme'] or r['category'] or '—'),
            'target_qty': _num(r['target_qty']), 'sold': _num(r['sold']),
            'pct': _pct(r['sold'], r['target_qty']),
        } for r in by_dealer_group],
        'by_executive': [{
            'user_id': r['user_id'], 'username': r['username'],
            'sales': _num(r['sales']),
            'target': _num(exec_target.get(r['user_id'], 0)),
            'pct': _pct(r['sales'], exec_target.get(r['user_id'], 0)),
            'visits': visit_exec.get(r['user_id'], {}).get('visits', 0),
            'avg_visit_minutes': visit_exec.get(r['user_id'], {}).get('avg_min'),
        } for r in by_executive],
        'by_dealer': [{
            'dealer_id': r['dealer_id'], 'dealer': r['dealer'],
            'sales': _num(r['sales']),
            'target': _num(dealer_target.get(r['dealer_id'], 0)),
            'pct': _pct(r['sales'], dealer_target.get(r['dealer_id'], 0)),
            'visits': visit_dealer.get(r['dealer_id'], {}).get('visits', 0),
            'avg_visit_minutes': visit_dealer.get(r['dealer_id'], {}).get('avg_min'),
        } for r in by_dealer],
        'by_part_group': [{
            'part_group': r['part_group'], 'qty': _num(r['qty']),
            'sales': _num(r['sales']), 'parts': r['parts'],
            'target_qty': _num(group_target.get(r['part_group'], 0)),
            'pct': _pct(r['qty'], group_target.get(r['part_group'], 0)),
        } for r in by_part_group],
        'by_part': [{
            'item_code': r['item_code'], 'description': r['description'],
            'part_group': r['part_group'], 'qty': _num(r['qty']), 'sales': _num(r['sales']),
        } for r in by_part],
    }


def exec_summary(executive_id, company_id=DEFAULT_COMPANY):
    """The one executive's this-month sales / target / % — for the check-in home.

    The target is the sum of the exec's dealers' value_target and exists even with
    zero sales, so it's read straight from the dealer master, not the sales join.
    """
    data = sales_explorer(executive_id=executive_id)
    row = next((e for e in data['by_executive'] if e['user_id'] == executive_id), None)
    sales = row['sales'] if row else 0
    target = row['target'] if row else _exec_target_only(executive_id, company_id=company_id)
    return {
        'month': data['month'],
        'executive_id': executive_id,
        'sales': sales,
        'target': target,
        'pct': _pct(sales, target),
        'data_through': sales_data_through(),
    }


def _exec_target_only(executive_id, company_id=DEFAULT_COMPANY):
    rows = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(mt.value_target),0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE d.company_id = {int(company_id)} AND d.sales_executive_id = %s
              AND mt.target_period = {_PERIOD}
              AND mt.category_id IS NOT NULL""", (executive_id,))
    return _num(rows[0]['t']) if rows else 0


def dealer_summary(dealer_id, company_id=DEFAULT_COMPANY):
    """The one dealer's this-month sales / target / %."""
    data = sales_explorer(dealer_id=dealer_id)
    row = next((d for d in data['by_dealer'] if d['dealer_id'] == dealer_id), None)
    if row:
        return {'sales': row['sales'], 'target': row['target'], 'pct': row['pct']}
    # No sales this month — still surface the dealer's target for this period.
    t = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(mt.value_target),0) AS t FROM dealer_money_target mt
            WHERE mt.dealer_id = %s AND mt.target_period = {_PERIOD}
              AND mt.category_id IS NOT NULL""",
        (dealer_id,))
    target = _num(t[0]['t']) if t else 0
    return {'sales': 0, 'target': target, 'pct': _pct(0, target)}


# Suggestions are returned uncapped. A gap-sorted global cap used to truncate
# these lists, which silently dropped whole part groups the dealer was behind on
# — small-target groups sort last, so they never survived. The UI cards them
# collapsed by default, so the full list costs no screen space.


# Half-width of the peer band around a dealer's money target: 0.20 => ±20%.
PEER_BAND = 0.20


def _peer_dealer_ids(dealer_id, company_id=DEFAULT_COMPANY):
    """Dealers comparable in size to `dealer_id` — money target within ±PEER_BAND,
    company-wide, excluding the dealer itself. Empty when the dealer has no
    money target for the period (no band can be derived).
    """
    row = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(value_target),0) AS t FROM dealer_money_target
            WHERE dealer_id = %s AND target_period = {_PERIOD}
              AND category_id IS NOT NULL""", (dealer_id,))
    if not row or row[0]['t'] is None:
        return []
    mine = float(row[0]['t'])
    if mine <= 0:
        return []
    return [r['dealer_id'] for r in (mysql_manager.execute_query(
        f"""SELECT mt.dealer_id
            FROM dealer_money_target mt
            JOIN dealer d ON d.dealer_id = mt.dealer_id AND d.company_id = {int(company_id)}
            WHERE mt.target_period = {_PERIOD}
              AND mt.category_id IS NOT NULL
              AND mt.dealer_id <> %s
            GROUP BY mt.dealer_id
            HAVING SUM(mt.value_target) BETWEEN %s AND %s""",
        (dealer_id, mine * (1 - PEER_BAND), mine * (1 + PEER_BAND))) or [])]


def _peer_product_opportunities(dealer_id, peer_ids, company_id=DEFAULT_COMPANY,
                                category_ids=None, limit=10):
    """The products comparable dealers spend most on that `dealer_id` doesn't buy.

    Ranked by peers' total SPEND over the 6-month window — quantity and price
    together, so a staple that peers reorder outranks a one-off expensive part.
    Spend comes from the Busy feed (`busy_sales_data.amount`); the product master's
    own `price` column is empty for every row, so it can't be used to cost anything.

    "Doesn't buy" is measured over THIS MONTH only: the question a rep is
    answering in the shop is what to sell today, and a part the dealer last took
    in March is as much an opening as one they have never stocked. Peers' spend
    still looks back six months, because a month of peer buying is too thin a
    basis to rank on.

    Unlike the target sheet, this is per PRODUCT and independent of schemes — a
    product qualifies on what peers spend, not on whether it feeds a target.

    Returns at most `limit` rows, biggest peer spend first, or [] when the dealer
    has no comparable peers.
    """
    if not peer_ids:
        return []

    cat_cond, cat_params = "", ()
    if category_ids is not None:
        if category_ids:
            ph = ",".join(["%s"] * len(category_ids))
            cat_cond = f"AND p.category_id IN ({ph}) "
            cat_params = tuple(category_ids)
        else:
            cat_cond = "AND 1 = 0 "

    peer_ph = ",".join(["%s"] * len(peer_ids))
    window = f"DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)"
    rows = mysql_manager.execute_query(
        f"""SELECT b.item_code,
                   MAX(p.name) AS description,
                   MAX(pg.part_group) AS part_group,
                   MAX(pg.scheme) AS scheme,
                   SUM({_SALES}) AS peer_amount,
                   SUM(b.quantity) AS peer_qty,
                   COUNT(DISTINCT d.dealer_id) AS peer_dealers
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            JOIN product p ON p.product_string = b.item_code
            -- Which scheme the part feeds, when it feeds one; shown as context on
            -- the row. LEFT so an unscheme'd part is still an opportunity.
            LEFT JOIN part_groups pg
                   ON pg.part_number = b.item_code AND pg.time_period = {_PERIOD}
            WHERE d.dealer_id IN ({peer_ph})
              AND b.sale_date >= {window}
              {cat_cond}
              AND NOT EXISTS (
                    SELECT 1 FROM busy_sales_data mb
                    JOIN dealer md ON md.name = mb.particulars
                                  AND md.company_id = {int(company_id)}
                    WHERE md.dealer_id = %s
                      AND mb.item_code = b.item_code
                      -- this month only; >= the 1st is the whole of it, and is
                      -- an index range rather than a function on the column
                      AND mb.sale_date >= {_PERIOD})
            GROUP BY b.item_code
            HAVING peer_amount > 0
            ORDER BY peer_amount DESC
            LIMIT %s""",
        (*peer_ids, *cat_params, dealer_id, int(limit))) or []

    # Shaped like the target rows so the app parses one product model for both;
    # the target fields are zero because a product here answers to no target.
    return [{
        'item_code': r['item_code'],
        'description': r['description'] or r['item_code'],
        'part_group': r['part_group'],
        'scheme': r['scheme'],
        'group_sold': 0, 'group_target': 0, 'group_gap': 0, 'group_pct': None,
        'group_last6m': 0, 'dealer_qty': 0, 'dealer_last6m': 0,
        'peer_dealers': int(r['peer_dealers'] or 0),
        'peer_qty': _num(r['peer_qty']),
        'peer_amount': _num(r['peer_amount']),
    } for r in rows]


def dealer_suggestions(dealer_id, company_id=DEFAULT_COMPANY, category_ids=None):
    """What to sell at this dealer, in two independent lists.

    grow[] — THE FULL TARGET SHEET, at the level each scheme is tracked
    (dealer_part_group_target):

      * scheme 'PG' is targeted per PART GROUP — each part group is one unit;
      * every other scheme (Basket 1, Basket 2, …) is targeted at SCHEME level —
        the whole scheme is one unit, its target the sum of its part groups'.

    Every unit the dealer carries a target for appears, hit or not: a target that
    has been reached is still a target, and a rep reading the sheet should see the
    ones that are done as well as the ones that aren't. Nothing is diverted into
    the other list — the two no longer partition one set of units, which is what
    used to make a target vanish from the target list.

    new_opportunity[] — the TOP PRODUCTS comparable dealers spend on that this
    dealer doesn't buy at all, biggest peer spend first (see
    _peer_product_opportunities). These are individual products, not units, and
    they are independent of targets: a product qualifies by what peers buy, not by
    whether it feeds a scheme this dealer is behind on.

    "Comparable" (PEER_BAND) means any dealer in the company whose money target for
    the period is within ±20% of this dealer's — a size proxy. Every dealer currently
    carries the same money target, so today the band admits all of them.

    `category_ids` (product.category_id list) restricts both lists to those
    categories — the app scopes to Parts / Pro Parts. None means every category.
    """
    # Optional product-category restriction (Parts / Pro Parts). Joins the candidate
    # parts to the product master by product_string = Busy item_code and keeps only
    # the requested categories. An empty list means "a category that resolved to
    # nothing" — a never-true condition, so no parts qualify.
    cat_join, cat_cond, cat_params = "", "", ()
    if category_ids is not None:
        if category_ids:
            ph = ",".join(["%s"] * len(category_ids))
            cat_join = "JOIN product cp ON cp.product_string = b.item_code "
            cat_cond = f"AND cp.category_id IN ({ph}) "
            cat_params = tuple(category_ids)
        else:
            cat_cond = "AND 1 = 0 "
    head = mysql_manager.execute_query(
        f"""SELECT dealer_id, name, sales_executive_id
            FROM dealer WHERE dealer_id = %s AND company_id = {int(company_id)}""", (dealer_id,))
    if not head:
        return None
    head = head[0]

    # Peers: dealers of comparable size, by money target within ±20%. A dealer
    # with no money target for the period has no band, hence no peers — its
    # new_opportunity list comes back empty rather than falling back to
    # everyone, which would silently compare it against the whole company.
    peer_ids = _peer_dealer_ids(dealer_id, company_id=company_id)

    # ── Targeted UNITS, at the level each scheme is tracked ──────────────────
    # Targets live per (part_group, scheme) in dealer_part_group_target, but the
    # level a target is MEASURED at depends on the scheme:
    #   * scheme 'PG'  — targeted per PART GROUP; each part group is its own unit.
    #   * every other scheme (Basket 1, Basket 2, …) — targeted at SCHEME level;
    #     the unit is the whole scheme and its target is the SUM of its part
    #     groups' targets.
    # Suggestions are defined at this UNIT level, never per individual product.
    # Quantity targets carry their OWN category_id, so the category filter is a
    # plain column test. It used to be inferred by joining part_groups -> product,
    # which could only ever match a scheme'd unit — a target set on a whole
    # category (blank part group and scheme, e.g. all of Oil) matched nothing and
    # was silently dropped from the sheet.
    tcat_cond, tcat_params = "", ()
    if category_ids is not None:
        if category_ids:
            ph = ",".join(["%s"] * len(category_ids))
            tcat_cond = f"AND dpg.category_id IN ({ph}) "
            tcat_params = tuple(category_ids)
        else:
            tcat_cond = "AND 1 = 0 "
    trows = mysql_manager.execute_query(
        f"""SELECT dpg.part_group, COALESCE(dpg.scheme, '') AS scheme,
                   COALESCE(dpg.target_qty, 0) AS t, dpg.category_id,
                   c.name AS category
            FROM dealer_part_group_target dpg
            LEFT JOIN categories c ON c.category_id = dpg.category_id
            WHERE dpg.dealer_id = %s AND dpg.target_period = {_PERIOD}
              AND dpg.target_qty > 0 {tcat_cond}""",
        (dealer_id, *tcat_params)) or []
    units = {}  # unit_key -> {name, scheme, is_pg, target}
    for r in trows:
        is_pg = (r['scheme'] or '').upper() == 'PG'
        # A target with neither scheme nor part group is set on the CATEGORY as a whole
        # (e.g. all of Oil). Naming it after its category keeps the row renderable —
        # falling through to the blank scheme would put an unlabelled row on the sheet.
        if not is_pg and not (r['scheme'] or '').strip() and not (r['part_group'] or '').strip():
            key = f"cat:{r['category'] or ''}"
            name = r['category'] or 'Other parts'
        elif is_pg:
            key, name = f"pg:{r['part_group']}", r['part_group']
        else:
            key, name = f"sc:{r['scheme']}", r['scheme']
        u = units.setdefault(key, {
            'name': name, 'scheme': 'PG' if is_pg else r['scheme'],
            'is_pg': is_pg, 'target': 0.0,
            # A category-level unit is measured against the category's own sales,
            # not against any part-group mapping.
            'category_id': r['category_id'] if key.startswith('cat:') else None})
        u['target'] += float(r['t'])

    # Per-UNIT sales: this dealer's this-month qty (progress) and the prior-6-months
    # baseline. A part maps to its unit by the same PG-vs-scheme rule as the targets,
    # using this month's mapping; unscheme'd parts have no unit. The category filter
    # (Parts / Pro Parts) applies. Skipped entirely when the dealer carries no
    # targets in this category — the opportunities below don't depend on it.
    sales = {}
    if units:
        unit_expr = ("CASE WHEN pg.scheme = 'PG' THEN CONCAT('pg:', pg.part_group) "
                     "ELSE CONCAT('sc:', pg.scheme) END")
        srows = mysql_manager.execute_query(
            f"""SELECT {unit_expr} AS unit_key,
                       SUM(CASE WHEN d.dealer_id = %s AND {_MONTH}
                                THEN b.quantity ELSE 0 END) AS dealer_qty,
                       SUM(CASE WHEN d.dealer_id = %s AND b.sale_date < {_PERIOD}
                                THEN b.quantity ELSE 0 END) AS dealer_last6m
                FROM busy_sales_data b
                JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
                {cat_join}
                JOIN part_groups pg ON pg.part_number = b.item_code AND pg.time_period = {_PERIOD}
                WHERE b.sale_date >= DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)
                  AND pg.scheme IS NOT NULL {cat_cond}
                GROUP BY unit_key""",
            # two dealer_id (this-month, prior-6m), then the category ids.
            (dealer_id, dealer_id, *cat_params)) or []
        sales = {r['unit_key']: r for r in srows}

        # A category-level unit (blank part group and scheme) has no part-group
        # mapping to sum through, so its progress is the dealer's sales in that
        # whole category — the same grain the target was set at.
        cat_units = {k: u for k, u in units.items() if u.get('category_id')}
        if cat_units:
            ids = sorted({u['category_id'] for u in cat_units.values()})
            ph = ",".join(["%s"] * len(ids))
            crows = mysql_manager.execute_query(
                f"""SELECT p.category_id,
                           SUM(CASE WHEN {_MONTH} THEN b.quantity ELSE 0 END) AS dealer_qty,
                           SUM(CASE WHEN b.sale_date < {_PERIOD}
                                    THEN b.quantity ELSE 0 END) AS dealer_last6m
                    FROM busy_sales_data b
                    JOIN dealer d ON d.name = b.particulars
                                 AND d.company_id = {int(company_id)}
                    JOIN product p ON p.product_string = b.item_code
                    WHERE d.dealer_id = %s
                      AND b.sale_date >= DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)
                      AND p.category_id IN ({ph})
                    GROUP BY p.category_id""",
                (dealer_id, *ids)) or []
            by_cat = {r['category_id']: r for r in crows}
            for key, u in cat_units.items():
                row = by_cat.get(u['category_id'])
                if row:
                    sales[key] = row

    # EVERY targeted unit, hit or not. On day one nothing has sold, so the rep sees
    # the whole sheet at "0 / N"; later in the month the hit ones simply read 100%+.
    # Widest gap first, so what still needs selling leads and the finished units
    # settle at the bottom.
    grow = []
    for key, u in units.items():
        s = sales.get(key)
        sold = float(s['dealer_qty']) if s else 0.0
        last6m = _num(s['dealer_last6m']) if s else 0
        grow.append({
            'item_code': '', 'description': u['name'], 'part_group': u['name'],
            # 'PG' keeps a part-group unit carding by part group in the app; a
            # scheme unit carries its scheme name and cards by scheme. Either is one
            # row — the target is the unit, not the products beneath it.
            'scheme': u['scheme'],
            'group_sold': _num(sold), 'group_target': _num(u['target']),
            'group_gap': _num(u['target'] - sold), 'group_pct': _pct(sold, u['target']),
            'group_last6m': last6m,
            'dealer_qty': _num(sold), 'dealer_last6m': last6m,
        })
    grow.sort(key=lambda x: x['group_gap'], reverse=True)

    return {
        'success': True,
        'month': month_label(),
        'dealer_id': head['dealer_id'], 'dealer': head['name'],
        'grow': grow,
        'new_opportunity': _peer_product_opportunities(
            dealer_id, peer_ids, company_id=company_id, category_ids=category_ids),
    }


# ── Category-split analytics (mobile dealer session) ─────────────────────────────
#
# The Busy feed carries sales across every product category (Parts, Pro Parts, Oil,
# Battery, …), but money targets are set for only three of them, and it is those
# three the app works against: each gets its own sales, its own target, its target
# sheet and its peer-spend opportunities. Every other category is reported as plain
# month / last-6-months sales — no target, no detail. Category comes from
# product.category_id, joined to the Busy row by
# product.product_string = busy_sales_data.item_code.

# The categories that carry money targets and therefore detail, in display order.
# Keep this in step with what dealer_money_target actually holds: a category listed
# here with no target rows costs a few pointless queries per dealer view, and one
# omitted silently loses its target sheet and opportunities in the app.
TARGETED_CATEGORY_NAMES = ('Parts', 'Pro Parts', 'Oil')

# Kept for callers that still name it; the two parts categories are a subset.
PARTS_CATEGORY_NAMES = ('Parts', 'Pro Parts')


def _category_ids_by_name():
    """{category name -> category_id} for the whole catalogue."""
    return {r['name']: r['category_id'] for r in (mysql_manager.execute_query(
        "SELECT category_id, name FROM categories") or [])}


def _dealer_category_sales(dealer_id, category_ids, company_id=DEFAULT_COMPANY,
                           sales_where=_MONTH):
    """This-month rupee sales for `dealer_id` restricted to `category_ids`
    (product.category_id). Empty list -> 0."""
    if not category_ids:
        return 0
    ph = ",".join(["%s"] * len(category_ids))
    row = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM({_SALES}), 0) AS s
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            JOIN product p ON p.product_string = b.item_code
            WHERE d.dealer_id = %s AND p.category_id IN ({ph}) AND {sales_where}""",
        (dealer_id, *category_ids))
    return _num(row[0]['s']) if row else 0


def dealer_other_stats(dealer_id, exclude_names=PARTS_CATEGORY_NAMES,
                       company_id=DEFAULT_COMPANY):
    """Per-category rupee sales for a dealer — this-month and prior-6-months (the six
    calendar months before the current one, current month excluded, matching the
    suggestions baseline). Categories with no sales in either window are dropped, and
    the result is ordered biggest-first. `exclude_names` drops categories by name;
    pass () to include every category (the Sales-tab distribution does this), or the
    parts categories (the default) for a non-parts breakdown. No targets, no
    suggestions — a plain sales readout."""
    excl = tuple(exclude_names) or ('',)
    ph = ",".join(["%s"] * len(excl))
    rows = mysql_manager.execute_query(
        f"""SELECT c.category_id, c.name,
                   COALESCE(SUM(CASE WHEN {_MONTH} THEN {_SALES} END), 0) AS this_month,
                   COALESCE(SUM(CASE WHEN b.sale_date >= DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)
                                       AND b.sale_date <  {_PERIOD}
                                     THEN {_SALES} END), 0) AS last6m
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            JOIN product p ON p.product_string = b.item_code
            JOIN categories c ON c.category_id = p.category_id
            WHERE d.dealer_id = %s AND c.name NOT IN ({ph})
            GROUP BY c.category_id, c.name
            HAVING this_month <> 0 OR last6m <> 0
            ORDER BY (this_month + last6m) DESC""",
        (dealer_id, *excl)) or []
    return [{'category_id': r['category_id'], 'category': r['name'],
             'this_month': _num(r['this_month']), 'last6m': _num(r['last6m'])}
            for r in rows]


def _dealer_category_targets(dealer_id):
    """{category_id -> money target} for this dealer and period.

    dealer_money_target carries the dealer's own target on the row with no
    category, and the split across categories on rows that name one. Only the
    split is returned here; the whole-dealer figure comes from dealer_summary.
    A category with no row simply has no target, which is not the same as zero —
    callers report it as "no target set" rather than 0% achieved.
    """
    return {r['category_id']: _num(r['value_target']) for r in (
        mysql_manager.execute_query(
            f"""SELECT category_id, value_target FROM dealer_money_target
                WHERE dealer_id = %s AND target_period = {_PERIOD}
                  AND category_id IS NOT NULL""", (dealer_id,)) or [])}


def dealer_category_analytics(dealer_id, company_id=DEFAULT_COMPANY):
    """The mobile dealer session's full analytics payload:

      * `target`     — the dealer's own money target for the period;
      * `categories` — one block per parts category (Parts, Pro Parts): its own rupee
                       sales, its OWN money target where one is set, and the target
                       sheet / peer-spend opportunities drawn from that category;
      * `category_sales` — every category's month + last-6-months sales, each with
                       its own target where dealer_money_target names that category.

    Category targets are real, from dealer_money_target rows that carry a
    category_id. A category with no such row reports target 0 / pct None, which
    the app shows as "no target set" rather than inventing a denominator.

    Returns None when the dealer doesn't exist (mirrors dealer_suggestions)."""
    head = mysql_manager.execute_query(
        f"""SELECT dealer_id, name FROM dealer
            WHERE dealer_id = %s AND company_id = {int(company_id)}""", (dealer_id,))
    if not head:
        return None
    head = head[0]

    ids_by_name = _category_ids_by_name()
    target = dealer_summary(dealer_id, company_id=company_id)['target']
    cat_targets = _dealer_category_targets(dealer_id)

    categories = []
    for name in TARGETED_CATEGORY_NAMES:
        cid = ids_by_name.get(name)
        ids = [cid] if cid is not None else []
        sales = _dealer_category_sales(dealer_id, ids, company_id=company_id)
        cat_target = cat_targets.get(cid, 0)
        sug = dealer_suggestions(dealer_id, company_id=company_id, category_ids=ids) \
            or {'grow': [], 'new_opportunity': []}
        categories.append({
            'category': name,
            'category_id': cid,
            'sales': sales,
            'target': cat_target,
            'pct': _pct(sales, cat_target) if cat_target else None,
            'grow': sug['grow'],
            'new_opportunity': sug['new_opportunity'],
        })

    # Every category's sales, each carrying its own target where one is set.
    sales_by_category = dealer_other_stats(
        dealer_id, exclude_names=(), company_id=company_id)
    for row in sales_by_category:
        t = cat_targets.get(row['category_id'], 0)
        row['target'] = t
        row['pct'] = _pct(row['this_month'], t) if t else None

    # dealer_other_stats lists only categories the dealer has bought in. A category
    # the dealer is TARGETED on but has bought nothing in is the most important row
    # on the sheet — nothing sold against a real target — so it is added here rather
    # than silently missing.
    names_by_id = {cid: name for name, cid in ids_by_name.items()}
    listed = {row['category_id'] for row in sales_by_category}
    for cid, t in cat_targets.items():
        if cid in listed or t <= 0:
            continue
        sales_by_category.append({
            'category_id': cid, 'category': names_by_id.get(cid, f'Category {cid}'),
            'this_month': 0, 'last6m': 0, 'target': t, 'pct': _pct(0, t),
        })

    # Every category is listed, even ones this dealer has neither bought in nor
    # carries a target for — they round out the sheet at 0 sales / no target so a
    # rep sees the whole catalogue, not just what's already moving. Sales- and
    # target-bearing categories keep their place above these (ordered first).
    all_cats = mysql_manager.execute_query(
        "SELECT category_id, name FROM categories WHERE is_active = 1 "
        "ORDER BY name") or []
    listed = {row['category_id'] for row in sales_by_category}
    for c in all_cats:
        if c['category_id'] in listed:
            continue
        sales_by_category.append({
            'category_id': c['category_id'], 'category': c['name'],
            'this_month': 0, 'last6m': 0, 'target': 0, 'pct': None,
        })

    return {
        'success': True,
        'month': month_label(),
        'dealer_id': head['dealer_id'],
        'dealer': head['name'],
        'target': target,
        'data_through': sales_data_through(),
        'categories': categories,
        # Sales across EVERY category (Parts, Pro Parts, Oil, …), this month + the
        # prior 6 months, with each category's own target where it has one.
        'category_sales': sales_by_category,
    }
