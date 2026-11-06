# -*- encoding: utf-8 -*-
"""Which companies this deployment serves.

This branch (ebco) is the Ebco-only build of Warehub. A database can still hold other
companies' rows — the local dev database is shared with the Hero/Cadila branches — so the
app never shows or uses them: every company list and every company scope is narrowed to
instance_company_ids(). Nothing is deleted; the other companies are simply out of reach.

The Ebco company is found by name, not id: it is company 1 on the Ebco server and
company 2 in the local dev database.
"""

from api.shared.db_manager import mysql_manager

INSTANCE_COMPANY_PREFIX = 'ebco'


def instance_company_ids():
    """Ids of the companies this deployment serves — those named "Ebco…". On a database
    whose only company is named otherwise, that one company (a fresh install)."""
    try:
        from flask import g
        cached = g.get('_instance_company_ids')
        if cached is not None:
            return cached
    except RuntimeError:
        g = None
    rows = mysql_manager.execute_query(
        "SELECT company_id FROM company WHERE LOWER(TRIM(name)) LIKE %s ORDER BY company_id",
        (INSTANCE_COMPANY_PREFIX + '%',)) or []
    ids = [r['company_id'] for r in rows]
    if not ids:
        only = mysql_manager.execute_query('SELECT company_id FROM company') or []
        if len(only) == 1:
            ids = [only[0]['company_id']]
    if g is not None:
        g._instance_company_ids = ids
    return ids


def narrow_to_instance(company_ids):
    """A company scope (None = every company, or a list) narrowed to this instance's
    companies. Always a list, so a caller's "unrestricted" never reaches other tenants."""
    allowed = instance_company_ids()
    if company_ids is None:
        return list(allowed)
    return [int(c) for c in company_ids if int(c) in allowed]


def instance_filter_sql(column, keep_null=True):
    """(sql_fragment, params) limiting `column` to this instance's companies, for queries
    that do not go through resolve_company_scope. `keep_null` keeps rows with no company
    — an unassigned dealer is still this instance's (every dealer on the Ebco server has
    none) and is exactly the row an admin needs to see to fix."""
    ids = instance_company_ids()
    marks = ', '.join(['%s'] * len(ids))
    inside = f"{column} IN ({marks})" if ids else '1=0'
    if keep_null:
        return f"({column} IS NULL OR {inside})", tuple(ids)
    return inside, tuple(ids)
