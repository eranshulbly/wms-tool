"""
Dynamic role-based permissions — all stored in DB, managed via Flask-Admin.
No code changes needed to add/edit roles.
"""

from .db_manager import mysql_manager

ALL_ORDER_STATES = ['Open', 'Picking', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed']
ALL_UPLOAD_TYPES = ['orders', 'invoices', 'products']


def get_permissions(role_name):
    """Fetch role permissions from DB. Returns safe empty defaults if role not found.

    Bug 22 fix: results are cached on Flask's request context (g) so repeated calls
    within the same request (from @active_required, @upload_permission_required, and
    manual checks) only hit the DB once.
    """
    try:
        from flask import g
        cache = g.get('_permissions_cache')
        if cache is None:
            g._permissions_cache = {}
            cache = g._permissions_cache
        if role_name in cache:
            return cache[role_name]
    except RuntimeError:
        # Outside a request context (e.g. tests) — skip the cache
        cache = None

    role = mysql_manager.execute_query(
        "SELECT role_id, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet, analytics FROM roles WHERE name = %s", (role_name,)
    )
    if not role:
        result = {'order_states': [], 'uploads': [], 'all_warehouses': False, 'eway_bill_admin': False, 'eway_bill_filling': False, 'supply_sheet': False, 'analytics': False}
    else:
        role_id = role[0]['role_id']
        order_states = mysql_manager.execute_query(
            "SELECT state_name FROM role_order_states WHERE role_id = %s", (role_id,)
        )
        uploads = mysql_manager.execute_query(
            "SELECT upload_type FROM role_uploads WHERE role_id = %s", (role_id,)
        )
        result = {
            'order_states': [r['state_name'] for r in order_states],
            'uploads': [r['upload_type'] for r in uploads],
            'all_warehouses': bool(role[0]['all_warehouses']),
            'eway_bill_admin': bool(role[0]['eway_bill_admin']),
            'eway_bill_filling': bool(role[0]['eway_bill_filling']),
            'supply_sheet': bool(role[0]['supply_sheet']),
            'analytics': bool(role[0]['analytics']),
        }

    if cache is not None:
        cache[role_name] = result
    return result


def can_see_order_state(role_name, state):
    return state in get_permissions(role_name)['order_states']


def can_upload(role_name, upload_type):
    return upload_type in get_permissions(role_name)['uploads']


def has_all_warehouse_access(role_name):
    return get_permissions(role_name)['all_warehouses']


def get_all_roles():
    """Return all role names from DB (used to populate dropdowns)."""
    rows = mysql_manager.execute_query("SELECT name FROM roles ORDER BY name")
    return [r['name'] for r in rows]


# ---------------------------------------------------------------------------
# Multi-tenant scoping
# ---------------------------------------------------------------------------
# The app serves several companies out of one database, so every read of a
# tenant-scoped table must be constrained to the companies the caller may see.
#
# The rule: the ALLOWED SET COMES FROM THE USER, never from the request. A
# client-supplied company_id may only *narrow* that set — it can never widen it,
# and its absence must never mean "no filter".


class CompanyAccessDenied(Exception):
    """Raised when a caller asks for a company they are not mapped to."""


def get_user_company_ids(user_id):
    """The distinct company ids this user is mapped to, via user_warehouse_company."""
    rows = mysql_manager.execute_query(
        "SELECT DISTINCT company_id FROM user_warehouse_company WHERE user_id = %s",
        (user_id,)) or []
    return [r['company_id'] for r in rows if r.get('company_id') is not None]


def resolve_company_scope(current_user, requested_company_id=None):
    """Resolve the company ids a request may read. Returns None for 'unrestricted'.

    * Roles with all_warehouses (admin) are unrestricted; a requested company simply
      narrows them to it.
    * Everyone else is limited to their user_warehouse_company mappings. Asking for a
      company outside that set raises CompanyAccessDenied rather than silently returning
      someone else's rows.
    * With no company requested, the caller's full allowed set is returned — so the query
      is still filtered. This is the case the old `if company_id:` code got wrong: omitting
      the parameter dropped the WHERE clause and exposed every tenant.

    Returning None (unrestricted) only ever happens for all_warehouses roles.
    """
    role = getattr(current_user, 'role', None) or ''
    is_unrestricted = has_all_warehouse_access(role)

    if is_unrestricted:
        return [int(requested_company_id)] if requested_company_id else None

    allowed = get_user_company_ids(getattr(current_user, 'id', None))
    if requested_company_id:
        if int(requested_company_id) not in allowed:
            raise CompanyAccessDenied(
                f'You do not have access to company {requested_company_id}.')
        return [int(requested_company_id)]

    # No company asked for -> every company this user may see. Never unfiltered.
    return allowed


def company_filter_sql(company_ids, column='company_id', alias=None):
    """(sql_fragment, params) constraining `column` to `company_ids`.

    Mirrors db_manager.partition_filter's contract so it can be dropped into a WHERE list:
      * None (unrestricted, admin)  -> ('1=1', ())
      * []   (user maps to nothing) -> ('1=0', ())  — deliberately matches no rows rather
        than falling open, which is the safe failure direction for a tenant filter.
    """
    if company_ids is None:
        return '1=1', ()
    qualified = f"{alias}.{column}" if alias else column
    if not company_ids:
        return '1=0', ()
    if len(company_ids) == 1:
        return f"{qualified} = %s", (company_ids[0],)
    placeholders = ','.join(['%s'] * len(company_ids))
    return f"{qualified} IN ({placeholders})", tuple(company_ids)
