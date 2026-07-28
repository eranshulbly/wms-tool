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

# Attribution goes through Hero's dealers (this Busy data is Hero's).
HERO = 1

_MONTH = "YEAR(b.sale_date) = YEAR(CURDATE()) AND MONTH(b.sale_date) = MONTH(CURDATE())"

# The definitive target period = the first day of the current month (a real DATE, so
# targets never collide across years). Targets are keyed by target_period = _PERIOD.
# (%% because execute_query runs `query % params`, so a literal % must be doubled.)
_PERIOD = "DATE_FORMAT(CURDATE(), '%%Y-%%m-01')"

_BASE = (f"FROM busy_sales_data b "
         f"JOIN dealer d ON d.name = b.particulars AND d.company_id = {HERO} "
         f"LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = {_PERIOD} ")


def month_label():
    # %% because execute_query runs `query % params`, so a literal % must be doubled.
    rows = mysql_manager.execute_query("SELECT DATE_FORMAT(CURDATE(), '%%M %%Y') AS m")
    return rows[0]['m'] if rows else ''


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


def _where(executive_id=None, dealer_id=None, part_group=None, part=None):
    """Build the WHERE (this-month + any of the 4 optional filters) and its params."""
    where, params = [_MONTH], []
    if executive_id:
        where.append("d.sales_executive_id = %s"); params.append(executive_id)
    if dealer_id:
        where.append("d.dealer_id = %s"); params.append(dealer_id)
    if part:
        where.append("b.item_code = %s"); params.append(part)
    if part_group:
        where.append("COALESCE(pg.part_group, '(Unmapped)') = %s"); params.append(part_group)
    return " AND ".join(where), tuple(params)


def sales_explorer(executive_id=None, dealer_id=None, part_group=None, part=None):
    """Filtered sales analytics: summary + breakdowns by executive / dealer / part
    group / part. Targets respect only executive/dealer scoping (see module doc)."""
    where, params = _where(executive_id, dealer_id, part_group, part)

    summary = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(b.amount),0) AS sales, COALESCE(SUM(b.quantity),0) AS qty,
                   COUNT(DISTINCT b.item_code) AS parts,
                   COUNT(DISTINCT d.dealer_id) AS dealers,
                   COUNT(DISTINCT d.sales_executive_id) AS executives
            {_BASE} WHERE {where}""", params)[0]

    by_executive = mysql_manager.execute_query(
        f"""SELECT u.id AS user_id, u.username,
                   SUM(b.amount) AS sales, SUM(b.quantity) AS qty
            {_BASE} JOIN users u ON u.id = d.sales_executive_id
            WHERE {where}
            GROUP BY u.id, u.username ORDER BY sales DESC""", params) or []

    by_dealer = mysql_manager.execute_query(
        f"""SELECT d.dealer_id, d.name AS dealer,
                   SUM(b.amount) AS sales, SUM(b.quantity) AS qty
            {_BASE} WHERE {where}
            GROUP BY d.dealer_id, d.name ORDER BY sales DESC""", params) or []

    by_part_group = mysql_manager.execute_query(
        f"""SELECT COALESCE(pg.part_group, '(Unmapped)') AS part_group,
                   SUM(b.quantity) AS qty, SUM(b.amount) AS sales,
                   COUNT(DISTINCT b.item_code) AS parts
            {_BASE} WHERE {where}
            GROUP BY COALESCE(pg.part_group, '(Unmapped)') ORDER BY qty DESC""", params) or []

    by_part = mysql_manager.execute_query(
        f"""SELECT b.item_code, MAX(pg.description) AS description,
                   MAX(pg.part_group) AS part_group,
                   SUM(b.quantity) AS qty, SUM(b.amount) AS sales
            {_BASE} WHERE {where}
            GROUP BY b.item_code ORDER BY qty DESC""", params) or []

    # Part-group quantity targets are per dealer (dealer_part_group_target). For the
    # current scope they sum over the dealers in view (executive/dealer filters) — like
    # the rupee targets, a part / part-group filter narrows sold qty, not the target.
    gwhere = [f"d.company_id = {HERO}", f"dpg.target_period = {_PERIOD}"]
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
    dwhere = [f"d.company_id = {HERO}", "d.sales_executive_id IS NOT NULL",
              f"mt.target_period = {_PERIOD}"]
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
    dgwhere = [f"d.company_id = {HERO}", f"dpg.target_period = {_PERIOD}"]
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
                JOIN dealer d2 ON d2.name = b.particulars AND d2.company_id = {HERO}
                LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = {_PERIOD}
                WHERE {_MONTH}
                GROUP BY d2.dealer_id, COALESCE(pg.part_group, '(Unmapped)')
            ) s ON s.dealer_id = dpg.dealer_id AND s.part_group = dpg.part_group
            WHERE {' AND '.join(dgwhere)}
            ORDER BY d.name, dpg.part_group""", tuple(dgparams)) or []

    return {
        'success': True,
        'month': month_label(),
        'summary': {
            'total_sales': _num(summary['sales']), 'total_qty': _num(summary['qty']),
            'parts': summary['parts'], 'dealers': summary['dealers'],
            'executives': summary['executives'],
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
        } for r in by_executive],
        'by_dealer': [{
            'dealer_id': r['dealer_id'], 'dealer': r['dealer'],
            'sales': _num(r['sales']),
            'target': _num(dealer_target.get(r['dealer_id'], 0)),
            'pct': _pct(r['sales'], dealer_target.get(r['dealer_id'], 0)),
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


def exec_summary(executive_id):
    """The one executive's this-month sales / target / % — for the check-in home.

    The target is the sum of the exec's dealers' value_target and exists even with
    zero sales, so it's read straight from the dealer master, not the sales join.
    """
    data = sales_explorer(executive_id=executive_id)
    row = next((e for e in data['by_executive'] if e['user_id'] == executive_id), None)
    sales = row['sales'] if row else 0
    target = row['target'] if row else _exec_target_only(executive_id)
    return {
        'month': data['month'],
        'executive_id': executive_id,
        'sales': sales,
        'target': target,
        'pct': _pct(sales, target),
    }


def _exec_target_only(executive_id):
    rows = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(mt.value_target),0) AS t
            FROM dealer d JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
            WHERE d.company_id = {HERO} AND d.sales_executive_id = %s
              AND mt.target_period = {_PERIOD}""", (executive_id,))
    return _num(rows[0]['t']) if rows else 0


def dealer_summary(dealer_id):
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


# suggestion list caps
GROW_LIMIT = 25
NEW_LIMIT = 25


def dealer_suggestions(dealer_id):
    """Part suggestions for the exec visiting `dealer_id`, driven by the DEALER's own
    part-group quantity targets (dealer_part_group_target):

      * find the part groups where this dealer is BEHIND their target this month;
      * within those groups, suggest parts —
          grow[]            parts the dealer already buys (push more), and
          new_opportunity[] parts the dealer doesn't buy but the exec's peers do.

    Each suggestion carries the dealer's progress on that part's GROUP target.
    """
    head = mysql_manager.execute_query(
        f"""SELECT dealer_id, name, sales_executive_id
            FROM dealer WHERE dealer_id = %s AND company_id = {HERO}""", (dealer_id,))
    if not head:
        return None
    head = head[0]
    ex = head['sales_executive_id']
    empty = {'success': True, 'month': month_label(), 'dealer_id': head['dealer_id'],
             'dealer': head['name'], 'grow': [], 'new_opportunity': []}

    # This dealer's part-group qty targets for the month.
    targets = {r['part_group']: float(r['t']) for r in (mysql_manager.execute_query(
        f"""SELECT part_group, COALESCE(target_qty, 0) AS t
            FROM dealer_part_group_target
            WHERE dealer_id = %s AND target_period = {_PERIOD} AND target_qty > 0""",
        (dealer_id,)) or [])}
    if not targets:
        return empty

    # Per-part month sales: this dealer's qty, the exec's peers' qty + peer count, + group.
    rows = mysql_manager.execute_query(
        f"""SELECT b.item_code,
                   MAX(pg.description) AS description,
                   MAX(pg.part_group)  AS part_group,
                   SUM(CASE WHEN d.dealer_id = %s THEN b.quantity ELSE 0 END) AS dealer_qty,
                   SUM(CASE WHEN d.sales_executive_id = %s AND d.dealer_id <> %s
                            THEN b.quantity ELSE 0 END) AS peer_qty,
                   COUNT(DISTINCT CASE WHEN d.sales_executive_id = %s AND d.dealer_id <> %s
                            THEN d.dealer_id END) AS peer_dealers
            FROM busy_sales_data b
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {HERO}
            LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.period = {_PERIOD}
            WHERE {_MONTH}
            GROUP BY b.item_code""",
        (dealer_id, ex, dealer_id, ex, dealer_id)) or []

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
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {HERO}
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
            JOIN dealer d ON d.name = b.particulars AND d.company_id = {HERO}
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
        'grow': grow[:GROW_LIMIT],
        'new_opportunity': new_opp[:NEW_LIMIT],
    }
