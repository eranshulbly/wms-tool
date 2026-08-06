# -*- encoding: utf-8 -*-
"""Target Tracker computation — every number on the Target Tracker screen.

Reads only real data: busy_sales_data (billed lines), dealer_part_group_target
(quantity targets), dealer_money_target (value targets), part_groups (monthly scheme
and part-group mapping), dealer/product/categories masters, dealer_visits.

Three rules govern everything here and are implemented in one place each, so they
cannot drift between screens:

  Pro-rating (§3.1) — a finished month contributes its whole target; the running month
  contributes only the elapsed share. `_month_rows()` computes the fraction once per
  month and every target figure is multiplied by it. A multi-month total pro-rates each
  month separately, so an unfinished month can never inflate the total.

  What carries a target (§3.2) — decided by the DATA, never by a hard-coded category
  list (§10.8): a category or scheme is "targeted" when quantity-target rows exist for
  it in scope. Everything else is sales-only and must render as "no target" / "—",
  never as a red 0% (§3.3).

  Value targets — a dealer's rupee target is its money target for the Parts category
  (the user's decision); an executive's is the sum across their dealers.
"""

import calendar
from datetime import date

from api.shared.db_manager import mysql_manager

# The rupee target lives on this category alone. Named once so the choice is visible.
VALUE_TARGET_CATEGORY = 'Parts'


# ---------------------------------------------------------------------------
# Months and pro-rating
# ---------------------------------------------------------------------------

def _elapsed(year, month, today=None):
    """Share of the month that has passed: 1.0 for a finished month.

    The current month is partial, so its target is only worth the elapsed part of it
    (§3.1). Day-granular — on the 4th of a 31-day month this is 4/31.
    """
    today = today or date.today()
    if (year, month) < (today.year, today.month):
        return 1.0
    if (year, month) > (today.year, today.month):
        return 0.0            # a future month has contributed nothing yet
    return today.day / calendar.monthrange(year, month)[1]


def available_months(company_id):
    """Every month the company has sales or targets for, newest first.

    Driven by the data — there is no month master — so the picker can only ever offer
    periods that actually have something behind them.
    """
    rows = mysql_manager.execute_query(
        """SELECT m FROM (
               SELECT DISTINCT DATE_FORMAT(sale_date, '%%Y-%%m') AS m
                 FROM busy_sales_data WHERE company_id = %s
               UNION
               SELECT DISTINCT DATE_FORMAT(target_period, '%%Y-%%m')
                 FROM dealer_money_target WHERE company_id = %s
               UNION
               SELECT DISTINCT DATE_FORMAT(target_period, '%%Y-%%m')
                 FROM dealer_part_group_target WHERE company_id = %s
           ) x WHERE m IS NOT NULL ORDER BY m DESC""",
        (company_id, company_id, company_id)) or []
    today = date.today()
    out = []
    for r in rows:
        y, mo = int(r['m'][:4]), int(r['m'][5:7])
        out.append({
            'id': r['m'],
            'label': f"{calendar.month_abbr[mo]} {y}",
            'current': (y, mo) == (today.year, today.month),
            'elapsed': round(_elapsed(y, mo, today), 4),
        })
    return out


def _month_rows(month_ids):
    """[(month_id, 'YYYY-MM-01', elapsed_fraction)] for the selected months."""
    today = date.today()
    out = []
    for m in month_ids:
        y, mo = int(m[:4]), int(m[5:7])
        out.append((m, f"{y:04d}-{mo:02d}-01", _elapsed(y, mo, today)))
    return out


# ---------------------------------------------------------------------------
# Shared scope
# ---------------------------------------------------------------------------

def _in(values):
    """A ',' placeholder list for an IN clause."""
    return ",".join(["%s"] * len(values))


class Scope:
    """One set of filter answers, resolved into SQL fragments.

    Kept as an object because every query below needs the same WHERE clause and the
    same parameter order; building it twice is how two panels end up disagreeing.
    """

    def __init__(self, company_id, months, execs=None, dealers=None, groups=None, parts=None):
        self.company_id = int(company_id)
        self.months = list(months)
        self.execs = [int(x) for x in (execs or [])]
        self.dealers = [int(x) for x in (dealers or [])]
        self.groups = list(groups or [])
        self.parts = list(parts or [])
        self.month_rows = _month_rows(self.months)
        self.periods = [p for _, p, _ in self.month_rows]
        self.elapsed = {p: e for _, p, e in self.month_rows}

    # -- sales side -------------------------------------------------------
    def sales_from(self):
        """The billed-line join: sale → dealer → executive, product → category,
        part → that month's part group and scheme."""
        return (
            "FROM busy_sales_data b "
            "JOIN dealer d ON d.name = b.particulars AND d.company_id = %s "
            "LEFT JOIN product p ON p.product_string = b.item_code AND p.company_id = %s "
            "LEFT JOIN categories c ON c.category_id = p.category_id "
            "LEFT JOIN part_groups pg ON pg.part_number = b.item_code "
            "  AND pg.time_period = DATE_FORMAT(b.sale_date, '%%Y-%%m-01') "
            "  AND pg.company_id = %s ")

    def sales_where(self):
        params = [self.company_id, self.company_id, self.company_id]
        conds = [f"DATE_FORMAT(b.sale_date, '%%Y-%%m') IN ({_in(self.months)})"]
        params += self.months
        if self.execs:
            conds.append(f"d.sales_executive_id IN ({_in(self.execs)})"); params += self.execs
        if self.dealers:
            conds.append(f"d.dealer_id IN ({_in(self.dealers)})"); params += self.dealers
        if self.groups:
            conds.append(f"pg.part_group IN ({_in(self.groups)})"); params += self.groups
        if self.parts:
            conds.append(f"b.item_code IN ({_in(self.parts)})"); params += self.parts
        return " AND ".join(conds), params

    def sql(self, select, extra="", group_by=""):
        where, params = self.sales_where()
        q = f"SELECT {select} {self.sales_from()} WHERE {where} {extra} {group_by}"
        return q, tuple(params)

    # -- dealer side ------------------------------------------------------
    def dealer_where(self, alias='d'):
        """Dealers in scope. Part / part-group filters narrow SALES, never the dealer
        list or the targets — a target is not smaller because you looked at one part."""
        conds = [f"{alias}.company_id = %s"]
        params = [self.company_id]
        if self.execs:
            conds.append(f"{alias}.sales_executive_id IN ({_in(self.execs)})"); params += self.execs
        if self.dealers:
            conds.append(f"{alias}.dealer_id IN ({_in(self.dealers)})"); params += self.dealers
        return " AND ".join(conds), params


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def value_target(scope, by=None):
    """Rupee target to date. by=None total, 'dealer' or 'exec' for a breakdown.

    Each month is pro-rated on its own before summing (§3.1).
    """
    dwhere, dparams = scope.dealer_where()
    key = {'dealer': 'd.dealer_id', 'exec': 'd.sales_executive_id'}.get(by)
    sel = f"{key} AS k, " if key else ""
    grp = f"GROUP BY {key}" if key else ""
    out = {} if key else 0.0
    for _, period, frac in scope.month_rows:
        if frac <= 0:
            continue
        rows = mysql_manager.execute_query(
            f"""SELECT {sel}COALESCE(SUM(mt.value_target), 0) AS t
                FROM dealer d
                JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
                JOIN categories c ON c.category_id = mt.category_id
                WHERE {dwhere} AND mt.target_period = %s AND c.name = %s
                {grp}""",
            tuple(dparams + [period, VALUE_TARGET_CATEGORY])) or []
        for r in rows:
            if key:
                out[r['k']] = out.get(r['k'], 0.0) + float(r['t']) * frac
            else:
                out += float(r['t']) * frac
    return out


def qty_target(scope, by=None):
    """Quantity target to date. by: None | 'category' | 'scheme' | 'group' | 'dealer'.

    Quantity targets are set per dealer × category × scheme × part_group. A part-group
    or part filter narrows which targets are in view (you asked about those groups), but
    an executive/dealer filter narrows whose targets they are.
    """
    dwhere, dparams = scope.dealer_where()
    key = {'category': 'c.name', 'scheme': 't.scheme', 'group': 't.part_group',
           'dealer': 'd.dealer_id'}.get(by)
    sel = f"{key} AS k, " if key else ""
    grp = f"GROUP BY {key}" if key else ""
    gcond, gparams = "", []
    if scope.groups:
        gcond = f" AND t.part_group IN ({_in(scope.groups)})"
        gparams = scope.groups
    out = {} if key else 0.0
    for _, period, frac in scope.month_rows:
        if frac <= 0:
            continue
        rows = mysql_manager.execute_query(
            f"""SELECT {sel}COALESCE(SUM(t.target_qty), 0) AS t
                FROM dealer_part_group_target t
                JOIN dealer d ON d.dealer_id = t.dealer_id
                LEFT JOIN categories c ON c.category_id = t.category_id
                WHERE {dwhere} AND t.target_period = %s{gcond}
                {grp}""",
            tuple(dparams + [period] + gparams)) or []
        for r in rows:
            k = r['k'] if key else None
            if key:
                out[k] = out.get(k, 0.0) + float(r['t']) * frac
            else:
                out += float(r['t']) * frac
    return out


# ---------------------------------------------------------------------------
# Per-category reporting
#
# Nothing on this screen adds the categories together. A combined figure would be
# meaningless: the categories are not measured on one scale — some carry a rupee target
# and some only a quantity target — and summing sales across them invited the old bug
# where all-category sales were shown as a percentage of a Parts-only target.
# ---------------------------------------------------------------------------

UNCATEGORISED = '(Uncategorised)'

# Which table holds each kind of target, and the column the target lives in.
_TARGET_SOURCE = {
    'value': ('dealer_money_target', 'value_target'),
    'qty': ('dealer_part_group_target', 'target_qty'),
}


def _target_by_category(scope, kind, by=None):
    """Target to date per category. kind: 'value' | 'qty'.

    Returns {category: amount}, or {key: {category: amount}} when `by` is 'exec'/'dealer'.
    Each month is pro-rated on its own before summing (§3.1).
    """
    table, col = _TARGET_SOURCE[kind]
    dwhere, dparams = scope.dealer_where()
    key = {'dealer': 'd.dealer_id', 'exec': 'd.sales_executive_id'}.get(by)
    sel = f"{key} AS k, " if key else ""
    grp = f"{key}, " if key else ""
    # A part-group filter narrows which quantity targets are in view; rupee targets have
    # no part-group grain to narrow by.
    gcond, gparams = "", []
    if kind == 'qty' and scope.groups:
        gcond = f" AND t.part_group IN ({_in(scope.groups)})"
        gparams = scope.groups

    out = {}
    for _, period, frac in scope.month_rows:
        if frac <= 0:
            continue
        rows = mysql_manager.execute_query(
            f"""SELECT {sel}c.name AS cat, COALESCE(SUM(t.{col}), 0) AS t
                FROM dealer d
                JOIN {table} t ON t.dealer_id = d.dealer_id
                JOIN categories c ON c.category_id = t.category_id
                WHERE {dwhere} AND t.target_period = %s{gcond}
                GROUP BY {grp}c.name""",
            tuple(dparams + [period] + gparams)) or []
        for r in rows:
            amount = float(r['t']) * frac
            if key:
                bucket = out.setdefault(r['k'], {})
                bucket[r['cat']] = bucket.get(r['cat'], 0.0) + amount
            else:
                out[r['cat']] = out.get(r['cat'], 0.0) + amount
    return out


def sales_by_category(scope, by=None):
    """Billed sales per category: {category: {'sales', 'qty'}}.

    With `by` = 'exec'/'dealer' the result is keyed by that id first. Sales with no
    product match fall into UNCATEGORISED rather than vanishing from the screen.
    """
    key = {'dealer': 'd.dealer_id', 'exec': 'd.sales_executive_id'}.get(by)
    sel = f"{key} AS k, " if key else ""
    grp = f"{key}, " if key else ""
    cat = f"COALESCE(c.name, '{UNCATEGORISED}')"
    q, p = scope.sql(
        f"{sel}{cat} AS cat, COALESCE(SUM(b.amount_with_gst),0) AS sales, "
        "COALESCE(SUM(b.quantity),0) AS qty",
        group_by=f"GROUP BY {grp}{cat}")
    out = {}
    for r in (mysql_manager.execute_query(q, p) or []):
        cell = {'sales': float(r['sales'] or 0), 'qty': float(r['qty'] or 0)}
        if key:
            out.setdefault(r['k'], {})[r['cat']] = cell
        else:
            out[r['cat']] = cell
    return out


def _cell(sales, qty_sold, value_target_amt, qty_target_amt):
    """One category's figures, measured against its single target scale.

    The rupee target wins when a category has both, so the headline sales figure and the
    percentage below it are always in the same unit. A category with no target of either
    kind reports its sales and no percentage — never a 0% that reads as failure.
    """
    if value_target_amt:
        kind, target, pct = 'value', value_target_amt, _pct(sales, value_target_amt)
    elif qty_target_amt:
        kind, target, pct = 'qty', qty_target_amt, _pct(qty_sold, qty_target_amt)
    else:
        kind, target, pct = None, None, None
    return {'sales': _n(sales), 'qty_sold': _n(qty_sold),
            'target_kind': kind, 'target': _n(target) if target else None, 'pct': pct}


def category_axis(scope):
    """The categories this screen reports on, in display order.

    A category appears if it has sales OR a target in scope, so a category that was
    targeted and sold nothing still shows up at 0% instead of disappearing. Rupee-targeted
    categories come first, then quantity-targeted, then untargeted — each block by sales.
    """
    sales = sales_by_category(scope)
    vt = _target_by_category(scope, 'value')
    qt = _target_by_category(scope, 'qty')
    names = set(sales) | set(vt) | set(qt)
    out = []
    for name in sorted(names):
        kind = 'value' if vt.get(name) else ('qty' if qt.get(name) else None)
        out.append({
            'category': name,
            'target_kind': kind,
            **_cell(sales.get(name, {}).get('sales', 0.0),
                    sales.get(name, {}).get('qty', 0.0),
                    vt.get(name), qt.get(name)),
        })
    out.sort(key=lambda c: ({'value': 0, 'qty': 1}.get(c['target_kind'], 2), -(c['sales'] or 0)))
    return out


OTHER_LABEL = 'Other'


def collapse(cells):
    """Per-category cells -> just Parts and Other.

    A pair of columns per category stops being readable past two or three, and the row
    tables are the widest thing on the screen. They therefore report the same two units
    the KPI row does; the full bifurcation is reached by drilling into an executive or a
    dealer, where the KPI tiles — and the Other tile's popup — break it back out.

    Other carries no target, for the same reason its tile doesn't: its categories sit on
    different scales, so a summed target would be a denominator that means nothing.
    """
    parts = cells.get(VALUE_TARGET_CATEGORY) or _cell(0, 0, None, None)
    rest = [c for k, c in cells.items() if k != VALUE_TARGET_CATEGORY]
    other = _cell(sum(c.get('sales') or 0 for c in rest),
                  sum(c.get('qty_sold') or 0 for c in rest), None, None)
    return {VALUE_TARGET_CATEGORY: parts, OTHER_LABEL: other}


def table_axis(scope, axis=None):
    """The two column groups every row table renders: Parts, then everything else."""
    axis = category_axis(scope) if axis is None else axis
    parts = next((c for c in axis if c['category'] == VALUE_TARGET_CATEGORY), None)
    return [
        {'category': VALUE_TARGET_CATEGORY,
         'target_kind': parts['target_kind'] if parts else None},
        {'category': OTHER_LABEL, 'target_kind': None},
    ]


def _cells_for(scope, entity_ids, by, axis):
    """{entity_id: {Parts|Other: cell}} — computed per category, then collapsed."""
    sales = sales_by_category(scope, by=by)
    vt = _target_by_category(scope, 'value', by=by)
    qt = _target_by_category(scope, 'qty', by=by)
    out = {}
    for eid in entity_ids:
        s, v, q = sales.get(eid, {}), vt.get(eid, {}), qt.get(eid, {})
        full = {
            c['category']: _cell(s.get(c['category'], {}).get('sales', 0.0),
                                 s.get(c['category'], {}).get('qty', 0.0),
                                 v.get(c['category']), q.get(c['category']))
            for c in axis
        }
        out[eid] = collapse(full)
    return out


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _n(v):
    if v is None:
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _pct(sold, target):
    """Achievement %, or None when there is no target. None renders '—', never 0%."""
    if not target:
        return None
    return round(float(sold) / float(target) * 100, 1)


def visit_stats(scope, by=None):
    """Visits and average minutes at dealer. Only completed visits count toward the
    average; an open check-in has no duration yet."""
    dwhere, dparams = scope.dealer_where()
    key = {'dealer': 'v.dealer_id', 'exec': 'd.sales_executive_id'}.get(by)
    sel = f"{key} AS k, " if key else ""
    grp = f"GROUP BY {key}" if key else ""
    rows = mysql_manager.execute_query(
        f"""SELECT {sel}COUNT(*) AS visits,
                   AVG(CASE WHEN v.check_out_at IS NOT NULL
                            THEN TIMESTAMPDIFF(SECOND, v.check_in_at, v.check_out_at) END) AS secs
            FROM dealer_visits v
            JOIN dealer d ON d.dealer_id = v.dealer_id
            WHERE {dwhere} AND DATE_FORMAT(v.check_in_at, '%%Y-%%m') IN ({_in(scope.months)})
            {grp}""",
        tuple(dparams + scope.months)) or []
    def one(r):
        return {'visits': r['visits'], 'avg_minutes': round(float(r['secs']) / 60, 1) if r['secs'] else None}
    if key:
        return {r['k']: one(r) for r in rows}
    return one(rows[0]) if rows else {'visits': 0, 'avg_minutes': None}


# ---------------------------------------------------------------------------
# Screen sections
# ---------------------------------------------------------------------------

def kpis(scope):
    """The KPI cards (§5.1) — Parts, Other, then the two scope-wide cards.

    Parts is the category the business steers on, so it keeps its own card and its own
    target. Everything else collapses into one "Other" card to stop the row growing a
    tile per category, and that card carries NO target: its categories are measured on
    different scales (some rupee, some quantity) and adding those targets together would
    produce the meaningless denominator this screen exists to avoid. The per-category
    detail behind it travels in `other.categories` for the breakdown popup.
    """
    # Dealers billed: every dealer in scope, and how many actually billed. Zero-sales
    # dealers stay countable (§10.4) — they are the point of this card.
    dwhere, dparams = scope.dealer_where()
    total_dealers = (mysql_manager.execute_query(
        f"SELECT COUNT(*) AS n FROM dealer d WHERE {dwhere}", tuple(dparams)) or [{'n': 0}])[0]['n']
    q3, p3 = scope.sql("COUNT(DISTINCT d.dealer_id) AS n", extra="AND b.quantity > 0")
    billed = (mysql_manager.execute_query(q3, p3) or [{'n': 0}])[0]['n']

    axis = category_axis(scope)
    parts = next((c for c in axis if c['category'] == VALUE_TARGET_CATEGORY), None)
    others = [c for c in axis if c['category'] != VALUE_TARGET_CATEGORY]

    vs = visit_stats(scope)
    return {
        'categories': axis,          # still the column axis for every table below
        'parts': parts,
        'other': {
            # A rupee total is the one thing every category here shares, so it is the only
            # figure the card can honestly headline.
            'sales': _n(sum(c['sales'] or 0 for c in others)),
            'category_count': len(others),
            'categories': others,
        },
        'dealers_total': total_dealers,
        'dealers_billed': billed,
        'visits': vs['visits'],
        'avg_minutes': vs['avg_minutes'],
    }


def by_month(scope):
    """One entry per selected month, chronological (§5.2), broken out per category."""
    out = []
    for mid, period, frac in sorted(scope.month_rows):
        sub = Scope(scope.company_id, [mid], scope.execs, scope.dealers, scope.groups, scope.parts)
        y, mo = int(mid[:4]), int(mid[5:7])
        axis = category_axis(sub)
        cols = collapse({c['category']: c for c in axis})
        out.append({
            'id': mid, 'label': f"{calendar.month_abbr[mo]} {y}",
            'current': frac < 1.0,
            'categories': [{'category': a['category'],
                            'target_kind': a['target_kind'],
                            **cols[a['category']]}
                           for a in table_axis(sub, axis)],
        })
    return out


def by_executive(scope):
    """Sales by executive (§5.3). Worst achievement first, no-target rows last (§9.1)."""
    dwhere, dparams = scope.dealer_where()
    execs = mysql_manager.execute_query(
        f"""SELECT u.id AS exec_id, u.username,
                   COUNT(DISTINCT d.dealer_id) AS dealers
            FROM dealer d JOIN users u ON u.id = d.sales_executive_id
            WHERE {dwhere} GROUP BY u.id, u.username""", tuple(dparams)) or []

    q, p = scope.sql("d.sales_executive_id AS k, "
                     "COUNT(DISTINCT CASE WHEN b.quantity > 0 THEN d.dealer_id END) AS billed",
                     group_by="GROUP BY d.sales_executive_id")
    billed = {r['k']: r for r in (mysql_manager.execute_query(q, p) or [])}
    visits = visit_stats(scope, by='exec')
    axis = category_axis(scope)
    cells = _cells_for(scope, [e['exec_id'] for e in execs], 'exec', axis)
    taxis = table_axis(scope, axis)

    out = []
    for e in execs:
        v = visits.get(e['exec_id'], {'visits': 0, 'avg_minutes': None})
        cats = cells.get(e['exec_id'], {})
        out.append({
            'id': e['exec_id'], 'name': e['username'],
            'dealers': e['dealers'], 'billed': billed.get(e['exec_id'], {}).get('billed', 0) or 0,
            'cats': cats,
            'visits': v['visits'], 'avg_minutes': v['avg_minutes'],
            **_rank_keys(cats, taxis),
        })
    return _rank(out)


def by_dealer(scope):
    """Dealers under the current scope (§6.1). Same ordering rule as executives."""
    dwhere, dparams = scope.dealer_where()
    dealers = mysql_manager.execute_query(
        f"""SELECT d.dealer_id, d.name, u.username AS exec_name
            FROM dealer d LEFT JOIN users u ON u.id = d.sales_executive_id
            WHERE {dwhere}""", tuple(dparams)) or []
    visits = visit_stats(scope, by='dealer')
    axis = category_axis(scope)
    cells = _cells_for(scope, [d['dealer_id'] for d in dealers], 'dealer', axis)
    taxis = table_axis(scope, axis)

    out = []
    for d in dealers:
        v = visits.get(d['dealer_id'], {'visits': 0, 'avg_minutes': None})
        cats = cells.get(d['dealer_id'], {})
        out.append({
            'id': d['dealer_id'], 'name': d['name'], 'exec_name': d['exec_name'],
            'cats': cats,
            'visits': v['visits'], 'avg_minutes': v['avg_minutes'],
            **_rank_keys(cats, taxis),
        })
    return _rank(out)


def _rank_keys(cats, axis):
    """Sort keys for a row, taken from the PRIMARY category (the first on the axis).

    Ranking has to pick one scale — adding the categories up is exactly what this screen
    exists to avoid — so rows are ordered by how they did on the leading targeted
    category. `sales` here is that category's sales, not a combined total, and is used
    only for ordering; the table never renders it as a standalone figure.
    """
    primary = axis[0]['category'] if axis else None
    cell = cats.get(primary, {}) if primary else {}
    return {'pct': cell.get('pct'), 'sales': cell.get('sales', 0) or 0}


def _rank(items):
    """§9.1 — targeted rows weakest first; untargeted rows after them, biggest value
    first. A row without a target must never sort in among genuine under-performers."""
    targeted = sorted([o for o in items if o.get('target')], key=lambda o: o['pct'] or 0)
    rest = sorted([o for o in items if not o.get('target')], key=lambda o: -o['sales'])
    return targeted + rest


def by_category(scope, mode='category'):
    """Sales by category or by scheme (§6.2). Targeted rows carry a target and a %;
    sales-only rows carry neither and are tagged as such (§3.3)."""
    key = 'c.name' if mode == 'category' else 'pg.scheme'
    q, p = scope.sql(
        f"COALESCE({key}, '(Unmapped)') AS k, COALESCE(SUM(b.quantity),0) AS sold, "
        f"COALESCE(SUM(b.amount_with_gst),0) AS sales, "
        # `groups` is reserved in MySQL 8 — quoted, not renamed, so the key the UI
        # reads stays the obvious one.
        f"COUNT(DISTINCT b.item_code) AS skus, COUNT(DISTINCT pg.part_group) AS `groups`",
        group_by=f"GROUP BY COALESCE({key}, '(Unmapped)')")
    rows = mysql_manager.execute_query(q, p) or []
    targets = qty_target(scope, by='category' if mode == 'category' else 'scheme')

    # §10.3 — a product that is in no scheme this month is simply absent from every
    # scheme view. (It still appears under its category, which is why this only applies
    # to scheme mode.)
    if mode == 'scheme':
        rows = [r for r in rows if r['k'] != '(Unmapped)']

    seen = {r['k'] for r in rows}
    out = []
    for r in rows:
        t = targets.get(r['k'], 0.0)
        out.append({
            'key': r['k'], 'name': r['k'], 'target_qty': _n(t), 'sold': _n(r['sold']),
            'pct': _pct(r['sold'], t), 'value': _n(r['sales']),
            'skus': r['skus'], 'groups': r['groups'],
        })
    # A target with no sales at all still has to appear — otherwise a category at 0%
    # silently vanishes instead of showing as the worst performer.
    for k, t in targets.items():
        if k and k not in seen and t:
            out.append({'key': k, 'name': k, 'target_qty': _n(t), 'sold': 0,
                        'pct': 0.0, 'value': 0, 'skus': 0, 'groups': 0})
    targeted = sorted([o for o in out if o['target_qty']], key=lambda o: o['pct'] or 0)
    rest = sorted([o for o in out if not o['target_qty']], key=lambda o: -o['value'])
    return targeted + rest


def detail(scope, key, mode):
    """The product popup (§8), for one category or one scheme.

    Targeted views are GROUPED by part group, because that is where the target lives —
    a product must never be shown with its own target or its own achievement (§8.1).
    Sales-only views are flat and carry no target columns at all (§8.2).
    """
    col = 'c.name' if mode == 'category' else 'pg.scheme'
    extra = f"AND COALESCE({col}, '(Unmapped)') = %s"
    q, p = scope.sql(
        "b.item_code AS item_code, MAX(p.name) AS name, "
        "COALESCE(MAX(pg.part_group), '(Unmapped)') AS part_group, "
        "MAX(c.name) AS category, MAX(pg.scheme) AS scheme, "
        "COALESCE(SUM(b.quantity),0) AS sold, COALESCE(SUM(b.amount_with_gst),0) AS value",
        extra=extra, group_by="GROUP BY b.item_code")
    rows = mysql_manager.execute_query(q, tuple(list(p) + [key])) or []

    # Targets for the groups this view covers, so the group rows can show one.
    gt = qty_target(scope, by='group')
    group_of = {r['part_group'] for r in rows}
    targeted = any(gt.get(g) for g in group_of)

    products = [{
        'item_code': r['item_code'], 'name': r['name'] or r['item_code'],
        'part_group': r['part_group'], 'category': r['category'], 'scheme': r['scheme'],
        'sold': _n(r['sold']), 'value': _n(r['value']),
    } for r in rows]

    groups = []
    if targeted:
        for g in sorted(group_of):
            mine = [x for x in products if x['part_group'] == g]
            sold = sum(x['sold'] for x in mine)
            t = gt.get(g, 0.0)
            groups.append({
                'part_group': g, 'category': (mine[0]['category'] if mine else None),
                'target_qty': _n(t), 'sold': sold, 'pct': _pct(sold, t),
                'value': _n(sum(x['value'] for x in mine)),
                # "N% of group" — a product's share of what its group sold, never its
                # own achievement, because a product has no target of its own.
                'products': sorted([{**x, 'share': round(x['sold'] / sold * 100, 1) if sold else 0}
                                    for x in mine], key=lambda x: -x['value']),
            })
        tg = sorted([g for g in groups if g['target_qty']], key=lambda g: g['pct'] or 0)
        groups = tg + sorted([g for g in groups if not g['target_qty']], key=lambda g: -g['value'])

    sold_total = sum(x['sold'] for x in products)
    target_total = sum(gt.get(g, 0.0) for g in group_of) if targeted else 0
    return {
        'key': key, 'mode': mode, 'targeted': targeted,
        'target_qty': _n(target_total), 'sold': sold_total,
        'pct': _pct(sold_total, target_total),
        'value': _n(sum(x['value'] for x in products)),
        'product_count': len(products), 'group_count': len(groups),
        'groups': groups,
        'products': sorted(products, key=lambda x: -x['value']),
        # A scheme basket changes month to month, so a multi-month popup is a union
        # of memberships and has to say so (§8.3).
        'union_note': mode == 'scheme' and len(scope.months) > 1,
    }


def opportunity(scope, dealer_id):
    """§7 Tab 2 — PROVISIONAL. Compares this dealer against the average of the same
    executive's other dealers for the selected months, and lists the part groups where
    it is behind. The rule is not agreed; the UI must label it as a placeholder."""
    row = mysql_manager.execute_query(
        "SELECT dealer_id, name, sales_executive_id FROM dealer WHERE dealer_id = %s AND company_id = %s",
        (dealer_id, scope.company_id))
    if not row:
        return None
    ex = row[0]['sales_executive_id']
    peers = [r['dealer_id'] for r in (mysql_manager.execute_query(
        "SELECT dealer_id FROM dealer WHERE sales_executive_id = %s AND company_id = %s AND dealer_id <> %s",
        (ex, scope.company_id, dealer_id)) or [])]
    if not peers:
        return []

    def sold_by_group(dealer_ids):
        s = Scope(scope.company_id, scope.months, dealers=dealer_ids)
        q, p = s.sql("COALESCE(pg.part_group,'(Unmapped)') AS k, COALESCE(SUM(b.quantity),0) AS qty, "
                     "COALESCE(SUM(b.amount_with_gst),0) AS val",
                     group_by="GROUP BY COALESCE(pg.part_group,'(Unmapped)')")
        return {r['k']: r for r in (mysql_manager.execute_query(q, p) or [])}

    mine, theirs = sold_by_group([dealer_id]), sold_by_group(peers)
    out = []
    for g, r in theirs.items():
        if g == '(Unmapped)':
            continue
        peer_avg = float(r['qty']) / len(peers)
        my_qty = float(mine.get(g, {}).get('qty', 0))
        gap = peer_avg - my_qty
        if gap <= 0:
            continue
        # Value the gap at the peers' own realised rate — the only price signal in the
        # data, since product.price is empty.
        rate = float(r['val']) / float(r['qty']) if r['qty'] else 0
        out.append({'part_group': g, 'sold_here': _n(my_qty), 'peer_avg': _n(round(peer_avg, 1)),
                    'gap': _n(round(gap, 1)), 'value': _n(round(gap * rate))})
    return sorted(out, key=lambda o: -o['value'])[:20]
