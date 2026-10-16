# -*- encoding: utf-8 -*-
"""tracking module — SQL. Read-only, every query company-scoped by the caller's
own resolved scope.

potential_order and order_state_history are both partitioned on a date, so every
query here carries partition_filter(). Without it MySQL touches all ~13 monthly
partitions to answer a question about one order.
"""

from api.db_manager import mysql_manager, partition_filter
from api.permissions import company_filter_sql

# Enough to fill a card each, and few enough that a packer scrolls rather than
# hunts. A dealer with more than this gets the newest, which is what someone
# standing at a bench is asking about.
SEARCH_LIMIT = 40

_SUMMARY_COLS = """
    po.potential_order_id, po.original_order_id, po.status, po.order_date,
    po.box_count, d.name AS dealer_name
"""


def _summary_sql(where_extra: str) -> str:
    return f"""
        SELECT {_SUMMARY_COLS}
          FROM potential_order po
          LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
         WHERE {{pf}} AND {{cf}} AND {where_extra}
         ORDER BY po.order_date DESC, po.potential_order_id DESC
         LIMIT %s
    """


def _scoped(sql_template: str, company_ids, params: tuple, limit: int):
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    sql = sql_template.format(pf=pf_sql, cf=cf_sql)
    return mysql_manager.execute_query(
        sql, tuple(pf_params) + tuple(cf_params) + params + (limit,)) or []


def by_order_no_exact(order_no: str, company_ids):
    return _scoped(_summary_sql("UPPER(po.original_order_id) = %s"),
                   company_ids, (order_no.upper(),), 6)


def by_order_suffix(suffix: str, company_ids):
    """Orders whose number ends in this exact final segment.

    Exact-segment equality, not LIKE '%3002' — a trailing wildcard would also
    match ...-13002, so "one result" would stop meaning one order. Same rule the
    pick-list lookup uses.
    """
    return _scoped(
        _summary_sql("SUBSTRING_INDEX(po.original_order_id, '-', -1) = %s"),
        company_ids, (suffix.upper(),), 6)


def by_dealer(name: str, company_ids, limit: int = SEARCH_LIMIT):
    """Orders for dealers whose name contains this text, newest first."""
    return _scoped(_summary_sql("d.name LIKE %s"),
                   company_ids, ('%' + name + '%',), limit)


def by_potential_order_id(potential_order_id: int, company_ids):
    return _scoped(_summary_sql("po.potential_order_id = %s"),
                   company_ids, (potential_order_id,), 1)


def picklist_for_order(potential_order_id: int):
    """The sheet attached to this order, if one was ever uploaded.

    LEFT-join territory: an order can exist without a pick list (uploaded from a
    spreadsheet), and the screen has to say "no pick list" rather than show
    blanks that read like missing data.
    """
    rows = mysql_manager.execute_query(
        """SELECT pl.picklist_id, pl.picklist_code, pl.line_count,
                  pl.picker_code, pl.picker_raw, pl.picker_assigned_at,
                  pl.printed_at, pl.print_count, pl.created_at AS uploaded_at,
                  u.name AS uploaded_by_name
             FROM order_picklist pl
             LEFT JOIN users u ON u.id = pl.created_by
            WHERE pl.potential_order_id = %s
            ORDER BY pl.created_at
            LIMIT 1""",
        (potential_order_id,),
    )
    return rows[0] if rows else None


def history_for_order(potential_order_id: int):
    """Every status this order has been in, oldest first, with who moved it.

    `changed_by` is a user id and may be null on rows written by an import, so
    the name is LEFT-joined and the caller renders what it gets.
    """
    pf_sql, pf_params = partition_filter('order_state_history', alias='osh')
    return mysql_manager.execute_query(
        f"""SELECT os.state_name, osh.changed_at, osh.changed_by,
                   u.name AS changed_by_name
              FROM order_state_history osh
              JOIN order_state os ON os.state_id = osh.state_id
              LEFT JOIN users u ON u.id = osh.changed_by
             WHERE {pf_sql} AND osh.potential_order_id = %s
             ORDER BY osh.changed_at, osh.order_state_history_id""",
        tuple(pf_params) + (potential_order_id,),
    ) or []
