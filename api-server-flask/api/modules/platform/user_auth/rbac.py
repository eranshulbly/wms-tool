# -*- encoding: utf-8 -*-
"""
Unified RBAC — one permission model for the web UI and the mobile app.

A user may hold several roles (e.g. a web role AND a mobile role); their effective
permissions are the UNION of those roles' permission codes. Codes are stored in
`permissions` and granted via `role_permissions`; membership is `user_roles`.

Backward compatibility: `users.role` is still written and, if a user has no
`user_roles` rows (or their roles carry no explicit permission grants), we fall
back to deriving codes from the legacy role flags so nothing breaks mid-migration.

See docs/V2_API_PORT.md.
"""

from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger

logger = get_logger(__name__)


class P:
    """Permission codes (mirrors wms-v2-backend, plus this app's web-specific ones)."""
    USER_READ = "user:read"
    USER_MANAGE = "user:manage"
    DEALER_READ = "dealer:read"
    DEALER_MANAGE = "dealer:manage"
    CATALOG_READ = "catalog:read"
    CATALOG_MANAGE = "catalog:manage"
    ORDER_READ = "order:read"
    # Without this, a user sees only the orders they created themselves.
    ORDER_READ_ALL = "order:read_all"
    ORDER_WRITE = "order:write"
    ORDER_APPROVE = "order:approve"
    INVENTORY_READ = "inventory:read"
    INVENTORY_PICK = "inventory:pick"
    INVENTORY_PACK = "inventory:pack"
    INVENTORY_STACK = "inventory:stack"
    INVENTORY_PUTAWAY = "inventory:putaway"
    INVENTORY_MOVE = "inventory:move"
    ASSIGNMENT_READ = "assignment:read"
    ASSIGNMENT_MANAGE = "assignment:manage"
    REPORT_VIEW = "report:view"
    WAREHOUSE_ALL = "warehouse:all"
    COMPANY_ALL = "company:all"
    # web-specific
    EWAY_FILL = "eway:fill"
    EWAY_ADMIN = "eway:admin"
    SUPPLY_SHEET_VIEW = "supply_sheet:view"
    UPLOAD_ORDERS = "upload:orders"
    UPLOAD_INVOICES = "upload:invoices"
    UPLOAD_PRODUCTS = "upload:products"


def get_user_roles(user_id):
    """All role names held by a user. Falls back to the legacy users.role string."""
    rows = mysql_manager.execute_query(
        """SELECT r.name FROM user_roles ur
           JOIN roles r ON r.role_id = ur.role_id
           WHERE ur.user_id = %s ORDER BY r.name""",
        (user_id,),
    )
    if rows:
        return [r['name'] for r in rows]

    legacy = mysql_manager.execute_query("SELECT role FROM users WHERE id = %s", (user_id,))
    if legacy and legacy[0].get('role'):
        return [legacy[0]['role']]
    return []


def get_user_permission_codes(user_id):
    """Effective permission codes = union across every role the user holds."""
    rows = mysql_manager.execute_query(
        """SELECT DISTINCT p.code FROM permissions p
           JOIN role_permissions rp ON rp.permission_id = p.permission_id
           JOIN user_roles ur       ON ur.role_id = rp.role_id
           WHERE ur.user_id = %s""",
        (user_id,),
    )
    if rows:
        return sorted({r['code'] for r in rows})

    # Fallback: user predates the RBAC tables — derive from the legacy role flags.
    return sorted(_legacy_codes_for_user(user_id))


def _legacy_codes_for_user(user_id):
    """Derive codes from the old single-role + flags model (transitional safety net)."""
    rows = mysql_manager.execute_query(
        """SELECT r.name, r.all_warehouses, r.eway_bill_admin, r.eway_bill_filling, r.supply_sheet
           FROM users u LEFT JOIN roles r ON r.name = u.role WHERE u.id = %s""",
        (user_id,),
    )
    if not rows or not rows[0].get('name'):
        return set()
    role = rows[0]

    if role['name'] == 'admin':
        return {v for k, v in vars(P).items() if not k.startswith('_') and isinstance(v, str)}

    codes = {P.ORDER_READ, P.CATALOG_READ, P.INVENTORY_READ, P.ASSIGNMENT_READ}
    if role['all_warehouses']:
        codes.add(P.WAREHOUSE_ALL)
    if role['eway_bill_admin']:
        codes.add(P.EWAY_ADMIN)
    if role['eway_bill_filling']:
        codes.add(P.EWAY_FILL)
    if role['supply_sheet']:
        codes.add(P.SUPPLY_SHEET_VIEW)

    uploads = mysql_manager.execute_query(
        """SELECT ru.upload_type FROM role_uploads ru
           JOIN roles r ON r.role_id = ru.role_id WHERE r.name = %s""",
        (role['name'],),
    )
    for u in uploads or []:
        codes.add(f"upload:{u['upload_type']}")
    return codes


def get_user_warehouse_ids(user_id):
    """(warehouse_ids, has_all). has_all short-circuits scoping (warehouse:all)."""
    codes = get_user_permission_codes(user_id)
    if P.WAREHOUSE_ALL in codes:
        return [], True

    rows = mysql_manager.execute_query(
        "SELECT DISTINCT warehouse_id FROM user_warehouse_company WHERE user_id = %s",
        (user_id,),
    )
    return [r['warehouse_id'] for r in rows or []], False


def get_user_company_ids(user_id):
    """(company_ids, has_all). Mirrors get_user_warehouse_ids; company:all overrides.

    Grants live in user_warehouse_company as (warehouse, company) pairs, so a user's
    companies are the distinct company side of their grants.
    """
    codes = get_user_permission_codes(user_id)
    if P.COMPANY_ALL in codes:
        return [], True

    rows = mysql_manager.execute_query(
        "SELECT DISTINCT company_id FROM user_warehouse_company WHERE user_id = %s",
        (user_id,),
    )
    return [r['company_id'] for r in rows or []], False


def user_has_permission(user_id, code):
    return code in get_user_permission_codes(user_id)
