# -*- encoding: utf-8 -*-
"""
Auth decorators for the mobile API (/api/v1), matching wms-v2-backend's behaviour.

  @v1_auth_required                 -> injects current_user (dict), 401 if not authenticated
  @v1_require_permission('order:read') -> 403 "Missing permission: <code>" if not granted

Permissions come from the access token's `perms` claim (fixed until the next
login/refresh, exactly like v2), while roles and warehouse scoping are re-read
live per request so changes apply immediately.

Status codes: 401 missing/invalid/expired token or inactive account;
403 authenticated but missing the required permission.
"""

from functools import wraps

import jwt
from flask import request

from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger

logger = get_logger(__name__)


def _unauthenticated(msg="Not authenticated"):
    return {"detail": msg}, 401


def _resolve_current_user():
    """Returns (current_user_dict, None) or (None, (body, status)) on failure."""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None, _unauthenticated()

    token = header.split(' ', 1)[1].strip()

    from api.modules.platform.user_auth import tokens, rbac
    try:
        payload = tokens.decode_token(token)
    except jwt.PyJWTError:
        return None, _unauthenticated("Invalid or expired token")

    if payload.get('type') != 'access':
        return None, _unauthenticated("Invalid token type")

    try:
        user_id = int(payload['sub'])
    except (KeyError, TypeError, ValueError):
        return None, _unauthenticated("Invalid or expired token")

    rows = mysql_manager.execute_query(
        "SELECT id, name AS username, email, status FROM users WHERE id = %s", (user_id,)
    )
    if not rows or rows[0]['status'] != 'active':
        return None, _unauthenticated("Account not active")

    warehouse_ids, has_all = rbac.get_user_warehouse_ids(user_id)
    company_ids, has_all_co = rbac.get_user_company_ids(user_id)
    return {
        'user_id': user_id,
        'username': rows[0]['username'],
        'email': rows[0]['email'],
        'permissions': payload.get('perms', []),      # from the token, like v2
        'roles': rbac.get_user_roles(user_id),        # live
        'warehouse_ids': None if has_all else warehouse_ids,
        'has_all_warehouses': has_all,
        # None => unscoped (sees every company). [] => scoped but granted nothing.
        'company_ids': None if has_all_co else company_ids,
        'has_all_companies': has_all_co,
    }, None


def company_scope(current_user):
    """None => the caller sees every company; a list => restrict to those ids.

    An empty list means "scoped but granted nothing", which callers must treat as
    matching no rows — never as unrestricted.
    """
    return None if current_user.get('has_all_companies') else current_user.get('company_ids')


def company_filter(current_user, column='company_id'):
    """(sql_fragment, params) to AND into a WHERE clause, or (None, []) if unscoped.

    Returns a fragment matching nothing when the user has no company grants.
    """
    scoped = company_scope(current_user)
    if scoped is None:
        return None, []
    if not scoped:
        return "1 = 0", []
    return "%s IN (%s)" % (column, ",".join(["%s"] * len(scoped))), list(scoped)


def v1_auth_required(f):
    """Require a valid access token; passes current_user as the first kwarg-ish arg."""
    @wraps(f)
    def decorated(*args, **kwargs):
        current_user, err = _resolve_current_user()
        if err:
            return err
        return f(*args, current_user=current_user, **kwargs)
    return decorated


def v1_require_permission(code):
    """Require a specific permission code (403 if the user lacks it)."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            current_user, err = _resolve_current_user()
            if err:
                return err
            if code not in (current_user.get('permissions') or []):
                return {"detail": f"Missing permission: {code}"}, 403
            return f(*args, current_user=current_user, **kwargs)
        return decorated
    return wrapper
