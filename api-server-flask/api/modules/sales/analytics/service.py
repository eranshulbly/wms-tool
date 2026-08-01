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
            f"AND pg.period = DATE_FORMAT(b.sale_date, '%%Y-%%m-01') ")


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


def month_label():
    # %% because execute_query runs `query % params`, so a literal % must be doubled.
    rows = mysql_manager.execute_query("SELECT DATE_FORMAT(CURDATE(), '%%M %%Y') AS m")
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
        f"""SELECT COALESCE(SUM(b.amount),0) AS sales, COALESCE(SUM(b.quantity),0) AS qty,
                   COUNT(DISTINCT b.item_code) AS parts,
                   COUNT(DISTINCT d.dealer_id) AS dealers,
                   COUNT(DISTINCT d.sales_executive_id) AS executives
            {_base(company_id)} WHERE {where}""", params)[0]

    by_executive = mysql_manager.execute_query(
        f"""SELECT u.id AS user_id, u.username,
                   SUM(b.amount) AS sales, SUM(b.quantity) AS qty
            {_base(company_id)} JOIN users u ON u.id = d.sales_executive_id
            WHERE {where}
            GROUP BY u.id, u.username ORDER BY sales DESC""", params) or []

    by_dealer = mysql_manager.execute_query(
        f"""SELECT d.dealer_id, d.name AS dealer,
                   SUM(b.amount) AS sales, SUM(b.quantity) AS qty
            {_base(company_id)} WHERE {where}
            GROUP BY d.dealer_id, d.name ORDER BY sales DESC""", params) or []

    by_part_group = mysql_manager.execute_query(
        f"""SELECT COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                   SUM(b.quantity) AS qty, SUM(b.amount) AS sales,
                   COUNT(DISTINCT b.item_code) AS parts
            {_base(company_id)} WHERE {where}
            GROUP BY COALESCE(pg.part_group, '(Unmapped)') ORDER BY qty DESC""", params) or []

    by_part = mysql_manager.execute_query(
        f"""SELECT b.item_code, MAX(pg.description) AS description,
                   MAX(pg.part_group) AS part_group,
                   SUM(b.quantity) AS qty, SUM(b.amount) AS sales
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
    dwhere = [f"d.company_id = {int(company_id)}", "d.sales_executive_id IS NOT NULL",
              f"mt.target_period = {target_period}"]
    dparams = []
    if executive_id:
        dwhere.append("d.sales_executive_id = %s"); dparams.append(executive_id)
    if dealer_id:
        dwhere.append("d.dealer_id = %s"); dparams.append(dealer_id)
    dclause = " AND ".join(dwhere)
    dealer_target = {r['dealer_id']: r['t'] for r in (mysql_manager.execute_query(
        f"""SELECT d.dealer_id, COALESCE(mt.value_target,0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE {dclause}""", tuple(dparams)) or [])}
    exec_target = {r['sales_executive_id']: r['t'] for r in (mysql_manager.execute_query(
        f"""SELECT d.sales_executive_id, COALESCE(SUM(mt.value_target),0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE {dclause} GROUP BY d.sales_executive_id""", tuple(dparams)) or [])}

    # Target tracker: every dealer × part-group target for this period vs qty sold.
    dgwhere = [f"d.company_id = {int(company_id)}", f"dpg.target_period = {target_period}"]
    dgparams = []
    if executive_id:
        dgwhere.append("d.sales_executive_id = %s"); dgparams.append(executive_id)
    if dealer_id:
        dgwhere.append("dpg.dealer_id = %s"); dgparams.append(dealer_id)
    if part_group:
        dgwhere.append("dpg.part_group = %s"); dgparams.append(part_group)
    by_dealer_group = mysql_manager.execute_query(
        f"""SELECT dpg.dealer_id, d.name AS dealer, dpg.part_group, dpg.target_qty,
                   COALESCE(s.sold, 0) AS sold
            FROM dealer_part_group_target dpg
            JOIN dealer d ON d.dealer_id = dpg.dealer_id
            LEFT JOIN (
                SELECT d2.dealer_id AS dealer_id,
                       COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                       SUM(b.quantity) AS sold
                FROM busy_sales_data b
                JOIN dealer d2 ON d2.name = b.particulars AND d2.company_id = {int(company_id)}
                LEFT JOIN part_groups pg ON pg.part_number = b.item_code
                    AND pg.period = DATE_FORMAT(b.sale_date, '%%Y-%%m-01')
                WHERE {sales_where}
                GROUP BY d2.dealer_id, COALESCE(pg.part_group, '(Unmapped)')
            ) s ON s.dealer_id = dpg.dealer_id AND s.part_group = dpg.part_group
            WHERE {' AND '.join(dgwhere)}
            ORDER BY d.name, dpg.part_group""", tuple(dgparams)) or []

    # Average time reps spent at dealers this period (dealer_visits check-in/out).
    visit_exec, visit_dealer, visit_total = _visit_stats(
        period, executive_id, dealer_id, company_id=company_id)

    return {
        'success': True,
        'month': month_label(),
        'period': period,
        'data_through': sales_data_through(),
        'summary': {
            'total_sales': _num(summary['sales']), 'total_qty': _num(summary['qty']),
            'parts': summary['parts'], 'dealers': summary['dealers'],
            'executives': summary['executives'],
            'visits': visit_total['visits'],
            'avg_visit_minutes': visit_total['avg_min'],
        },
        'by_dealer_group': [{
            'dealer_id': r['dealer_id'], 'dealer': r['dealer'], 'part_group': r['part_group'],
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
              AND mt.target_period = {_PERIOD}""", (executive_id,))
    return _num(rows[0]['t']) if rows else 0


def dealer_summary(dealer_id, company_id=DEFAULT_COMPANY):
    """The one dealer's this-month sales / target / %."""
    data = sales_explorer(dealer_id=dealer_id)
    row = next((d for d in data['by_dealer'] if d['dealer_id'] == dealer_id), None)
    if row:
        return {'sales': row['sales'], 'target': row['target'], 'pct': row['pct']}
    # No sales this month — still surface the dealer's target for this period.
    t = mysql_manager.execute_query(
        f"""SELECT COALESCE(mt.value_target,0) AS t FROM dealer_money_target mt
            WHERE mt.dealer_id = %s AND mt.target_period = {_PERIOD}""",
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
        f"""SELECT value_target FROM dealer_money_target
            WHERE dealer_id = %s AND target_period = {_PERIOD}""", (dealer_id,))
    if not row or row[0]['value_target'] is None:
        return []
    mine = float(row[0]['value_target'])
    if mine <= 0:
        return []
    return [r['dealer_id'] for r in (mysql_manager.execute_query(
        f"""SELECT mt.dealer_id
            FROM dealer_money_target mt
            JOIN dealer d ON d.dealer_id = mt.dealer_id AND d.company_id = {int(company_id)}
            WHERE mt.target_period = {_PERIOD}
              AND mt.dealer_id <> %s
              AND mt.value_target BETWEEN %s AND %s""",
        (dealer_id, mine * (1 - PEER_BAND), mine * (1 + PEER_BAND))) or [])]


def dealer_suggestions(dealer_id, company_id=DEFAULT_COMPANY):
    """Part suggestions for the exec visiting `dealer_id`, driven by the DEALER's own
    part-group quantity targets (dealer_part_group_target):

      * find the part groups where this dealer is BEHIND their target this month;
      * within those groups, suggest parts —
          grow[]            parts the dealer already buys (push more), and
          new_opportunity[] parts the dealer doesn't buy but comparable dealers do.

    "Comparable" (PEER_BAND) means any dealer in the company whose money target
    for the period is within ±20% of this dealer's — a size proxy, so the
    comparison is against similar-sized dealers rather than the sales
    executive's own book. Note every dealer currently carries the same money
    target, so today the band admits all of them.

    Each suggestion carries the dealer's progress on that part's GROUP target.
    """
    head = mysql_manager.execute_query(
        f"""SELECT dealer_id, name, sales_executive_id
            FROM dealer WHERE dealer_id = %s AND company_id = {int(company_id)}""", (dealer_id,))
    if not head:
        return None
    head = head[0]
    empty = {'success': True, 'month': month_label(), 'dealer_id': head['dealer_id'],
             'dealer': head['name'], 'grow': [], 'new_opportunity': []}

    # Peers: dealers of comparable size, by money target within ±20%. A dealer
    # with no money target for the period has no band, hence no peers — its
    # new_opportunity list comes back empty rather than falling back to
    # everyone, which would silently compare it against the whole company.
    peer_ids = _peer_dealer_ids(dealer_id, company_id=company_id)

    # This dealer's part-group qty targets for the month.
    targets = {r['part_group']: float(r['t']) for r in (mysql_manager.execute_query(
        f"""SELECT part_group, COALESCE(target_qty, 0) AS t
            FROM dealer_part_group_target
            WHERE dealer_id = %s AND target_period = {_PERIOD} AND target_qty > 0""",
        (dealer_id,)) or [])}
    if not targets:
        return empty

    # `IN ()` is a syntax error, so a dealer with no comparable peers gets a
    # never-true condition instead — peer_qty 0, and no new opportunities.
    peer_cond = ("d.dealer_id IN (%s)" % ",".join(["%s"] * len(peer_ids))
                 if peer_ids else "1 = 0")

    # Per-part month sales: this dealer's qty, comparable dealers' qty + count, + group.
    rows = mysql_manager.execute_query(
        f"""SELECT b.item_code,
                   MAX(pg.description) AS description,
                   MAX(pg.part_group)  AS part_group,
                   MAX(pg.scheme)      AS scheme,
                   SUM(CASE WHEN d.dealer_id = %s THEN b.quantity ELSE 0 END) AS dealer_qty,
                   SUM(CASE WHEN {peer_cond}
                            THEN b.quantity ELSE 0 END) AS peer_qty,
                   COUNT(DISTINCT CASE WHEN {peer_cond}
                            THEN d.dealer_id END) AS peer_dealers
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = {_PERIOD}
            WHERE {_MONTH}
            GROUP BY b.item_code""",
        # peer_ids twice: once for peer_qty's CASE, once for peer_dealers'.
        (dealer_id, *peer_ids, *peer_ids)) or []

    # Dealer's sold qty per (targeted) group, then the groups they're behind on.
    group_sold = {}
    for r in rows:
        g = r['part_group']
        if g in targets:
            group_sold[g] = group_sold.get(g, 0) + float(r['dealer_qty'])
    behind = {g: {'target': t, 'sold': group_sold.get(g, 0), 'gap': t - group_sold.get(g, 0)}
              for g, t in targets.items() if group_sold.get(g, 0) < t}
    if not behind:
        return empty

    # This dealer's qty per part group over the 6 months BEFORE the current month
    # (a prior baseline; the current month is excluded).
    last6m = {r['part_group']: _num(r['q']) for r in (mysql_manager.execute_query(
        f"""SELECT COALESCE(pg.part_group, '(Unmapped)') AS part_group, SUM(b.quantity) AS q
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = {_PERIOD}
            WHERE d.dealer_id = %s
              AND b.sale_date >= DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)
              AND b.sale_date <  {_PERIOD}
            GROUP BY COALESCE(pg.part_group, '(Unmapped)')""",
        (dealer_id,)) or [])}

    # This dealer's qty per PART over the same prior-6-month window (per-item
    # baseline for the expanded pivot rows).
    part_last6m = {r['item_code']: _num(r['q']) for r in (mysql_manager.execute_query(
        f"""SELECT b.item_code, SUM(b.quantity) AS q
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {int(company_id)}
            WHERE d.dealer_id = %s
              AND b.sale_date >= DATE_SUB({_PERIOD}, INTERVAL 6 MONTH)
              AND b.sale_date <  {_PERIOD}
            GROUP BY b.item_code""",
        (dealer_id,)) or [])}

    grow, new_opp = [], []
    for r in rows:
        g = r['part_group']
        if g not in behind:
            continue
        info = behind[g]
        base = {
            'item_code': r['item_code'], 'description': r['description'], 'part_group': g,
            # The commercial scheme the part sits under. 'PG' means the part is
            # targeted at part-group level, so the UI cards by part_group; any
            # other value (Basket 1, Ancillary, …) spans several part groups and
            # the UI cards by scheme. Targets/eligibility remain per part group.
            'scheme': r['scheme'],
            'group_sold': _num(info['sold']), 'group_target': _num(info['target']),
            'group_gap': _num(info['gap']), 'group_pct': _pct(info['sold'], info['target']),
            'group_last6m': last6m.get(g, 0),   # dealer's qty in this group, last 6 months
            'dealer_last6m': part_last6m.get(r['item_code'], 0),  # this part, last 6 months
        }
        dealer_qty = float(r['dealer_qty'])
        if dealer_qty > 0:
            grow.append({**base, 'dealer_qty': _num(dealer_qty)})
        elif r['peer_qty'] and r['peer_qty'] > 0:
            new_opp.append({**base, 'peer_dealers': r['peer_dealers'],
                            'peer_qty': _num(r['peer_qty'])})

    grow.sort(key=lambda x: (x['group_gap'], x['dealer_qty']), reverse=True)
    new_opp.sort(key=lambda x: (x['group_gap'], x['peer_dealers']), reverse=True)

    return {
        'success': True,
        'month': month_label(),
        'dealer_id': head['dealer_id'], 'dealer': head['name'],
        'grow': grow,
        'new_opportunity': new_opp,
    }
