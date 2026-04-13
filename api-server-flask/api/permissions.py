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
        "SELECT role_id, all_warehouses, eway_bill_admin, eway_bill_filling, supply_sheet FROM roles WHERE name = %s", (role_name,)
    )
    if not role:
        result = {'order_states': [], 'uploads': [], 'all_warehouses': False, 'eway_bill_admin': False, 'eway_bill_filling': False, 'supply_sheet': False}
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
