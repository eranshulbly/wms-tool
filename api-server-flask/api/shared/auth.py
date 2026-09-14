# -*- encoding: utf-8 -*-
"""
Authentication and authorization decorators.

Moved here from routes.py so they can be imported by any route module
without creating circular imports.

Usage:
    from .core.auth import token_required, active_required, upload_permission_required

    @rest_api.route('/api/orders/upload')
    class OrderUpload(Resource):
        @token_required
        @active_required
        @upload_permission_required('orders')
        def post(self, current_user):
            ...
"""

import re
from functools import wraps

import jwt
from flask import request

from ..config import BaseConfig
from .db_manager import (mysql_manager, partition_filter,
                         _PART_CONVERTOR_ROLE_NAME, _DMS_OPERATOR_ROLE_NAME,
                         _OPS_MANAGER_ROLE_NAME)
from .logging import get_logger

logger = get_logger(__name__)


# ── part_convertor: confined to the Submitted Orders screen ───────────────────────
#
# The UI already hides everything else from this role (the launcher shows one tile, the
# sidebar one item, and AuthGuard bounces every other path). None of that is access
# control: the role's token is a normal bearer token that works against every endpoint,
# so anyone holding it could still call the DMS download, the inventory upload or the
# admin routes directly. The restriction is therefore enforced HERE — token_required is
# the one place every web route passes through, so nothing can be added later that
# accidentally skips the check.
#
# An allowlist rather than a blocklist, and matched exactly rather than by prefix: a
# prefix test on '/api/orders/submitted' would also admit .../dms-file, .../reject and
# .../manual, which are precisely the things this role must not reach.
# Paths every signed-in user keeps, whatever their scope. Signing out must never be
# blocked, or a restricted user is stuck in the app with no way out.
_ALWAYS_ALLOWED = (
    ('POST', r'^/api/users/logout/?$'),
)

# role -> (screen name, allowed (method, path) pairs). A role listed here can reach
# NOTHING else; a role absent from this map is unrestricted and pays only a dict lookup.
#
# Matched exactly, never by prefix. A prefix test on '/api/orders/submitted' would admit
# .../dms-file, .../reject and .../manual — precisely the calls that separate these two
# roles from each other.
_ROLE_SCOPES = {
    # Transcription only: read a paper order's photo, upload the sheet that becomes its
    # lines. Cannot download a DMS file or touch stock.
    _PART_CONVERTOR_ROLE_NAME: ('Submitted Orders', (
        ('GET',  r'^/api/orders/submitted/?$'),
        ('GET',  r'^/api/orders/submitted/\d+/photo/\d+/?$'),
        ('POST', r'^/api/orders/submitted/\d+/part-convertor/?$'),
        ('GET',  r'^/api/warehouses/?$'),
        ('GET',  r'^/api/companies/?$'),
    )),
    # The DMS screen end to end: stock in, DMS files out, manual orders raised, bad ones
    # rejected. Cannot upload a part-convertor sheet — that is the other role's job.
    _DMS_OPERATOR_ROLE_NAME: ('Download DMS Input', (
        ('GET',  r'^/api/orders/submitted/?$'),
        ('GET',  r'^/api/orders/submitted/\d+/photo/\d+/?$'),
        ('GET',  r'^/api/orders/submitted/\d+/dms-file/?$'),
        ('POST', r'^/api/orders/submitted/\d+/reject/?$'),
        ('POST', r'^/api/orders/submitted/manual/?$'),
        ('GET',  r'^/api/orders/inventory/?$'),
        ('POST', r'^/api/orders/inventory/?$'),
        ('GET',  r'^/api/orders/dealers/?$'),
        ('GET',  r'^/api/warehouses/?$'),
        ('GET',  r'^/api/companies/?$'),
    )),
    # The order desk: orders in, through their states, picked, and billed. Five screens
    # rather than one — dashboard, upload orders, upload invoice, manage orders, download
    # picklist — so this list is longer than the two above, but it is still an allowlist:
    # analytics, admin, inventory, e-way bill and supply sheet are all absent, and so is
    # the product master.
    _OPS_MANAGER_ROLE_NAME: ('Order Tracking', (
        # Dashboard
        ('GET',  r'^/api/orders/status/?$'),
        ('GET',  r'^/api/orders/recent/?$'),
        # Manage Orders
        ('GET',  r'^/api/orders/?$'),
        ('GET',  r'^/api/orders/\d+/details/?$'),
        ('PUT',  r'^/api/orders/\d+/status/?$'),
        ('POST', r'^/api/orders/\d+/status/?$'),
        ('POST', r'^/api/orders/\d+/complete-dispatch/?$'),
        # Upload Orders / Upload Invoice
        ('POST', r'^/api/orders/upload/?$'),
        ('POST', r'^/api/invoices/upload/?$'),
        # Download Picklist
        ('GET',  r'^/api/orders/picklist/options/?$'),
        ('GET',  r'^/api/orders/picklist/?$'),
        # The warehouse/company pickers every one of those screens loads
        ('GET',  r'^/api/warehouses/?$'),
        ('GET',  r'^/api/companies/?$'),
    )),
}

# Compiled once at import; matching runs on every authenticated request.
_COMPILED_SCOPES = {
    role: (screen, tuple((m, re.compile(p)) for m, p in patterns))
    for role, (screen, patterns) in _ROLE_SCOPES.items()
}
_COMPILED_ALWAYS = tuple((m, re.compile(p)) for m, p in _ALWAYS_ALLOWED)


def role_scope_error(current_user):
    """403 payload when a single-screen role asks for anything outside its screen.

    Returns None for unrestricted roles and for the paths a restricted role needs.
    """
    scope = _COMPILED_SCOPES.get(getattr(current_user, 'role', None) or '')
    if scope is None:
        return None
    screen, patterns = scope
    path, method = request.path, request.method.upper()
    for allowed_method, pattern in patterns + _COMPILED_ALWAYS:
        if method == allowed_method and pattern.match(path):
            return None
    logger.warning("role blocked outside its scope", extra={
        'path': path, 'method': method, 'role': current_user.role,
        'user_id': getattr(current_user, 'id', None)})
    message = f"Your account only has access to {screen}."
    # `detail` as well, so a client that reads that key shows the reason rather than
    # falling back to a bare "HTTP 403".
    return {"success": False, "msg": message, "detail": message}, 403


def token_required(f):
    """
    Validates the JWT bearer token from the Authorization header.

    On success, injects `current_user` (a Users model instance) as the
    second positional argument (after `self` for class-based views).
    """
    @wraps(f)
    def decorator(*args, **kwargs):
        token = None

        if "authorization" in request.headers:
            raw = request.headers["authorization"]
            # Strip 'Bearer ' prefix before decoding and blocklist lookup
            token = raw[7:] if raw.lower().startswith("bearer ") else raw

        if not token:
            return {"success": False, "msg": "Valid JWT token is missing"}, 400

        try:
            from ..models import Users

            data = jwt.decode(token, BaseConfig.SECRET_KEY, algorithms=["HS256"])
            current_user = Users.get_by_email(data["email"])

            if not current_user:
                return {"success": False, "msg": "User does not exist."}, 401

            pf_sql, pf_params = partition_filter('jwt_token_blocklist')
            blocked_token = mysql_manager.execute_query(
                f"SELECT id FROM jwt_token_blocklist WHERE jwt_token = %s AND {pf_sql}",
                (token, *pf_params)
            )
            if blocked_token:
                return {"success": False, "msg": "Token revoked."}, 401

            if not current_user.check_jwt_auth_active():
                return {"success": False, "msg": "Token expired."}, 401

            if current_user.status == 'blocked':
                return {"success": False, "msg": "Account has been blocked."}, 403

            # Role-scoping: refuse before the view runs, so a restricted role cannot
            # reach a handler at all.
            scope_error = role_scope_error(current_user)
            if scope_error is not None:
                return scope_error

        except jwt.ExpiredSignatureError:
            return {"success": False, "msg": "Token has expired."}, 401
        except jwt.InvalidTokenError:
            return {"success": False, "msg": "Token is invalid."}, 401
        except Exception as e:
            logger.exception("Unexpected authentication error")
            return {"success": False, "msg": f"Authentication error: {str(e)}"}, 500

        # For Flask-RESTX class-based views, args = (self, ...)
        # Inject current_user as the second argument.
        if args:
            return f(args[0], current_user, *args[1:], **kwargs)
        return f(current_user, **kwargs)

    return decorator


def active_required(f):
    """Ensures user is active (not pending). Returns 403 with status='pending' if not."""
    @wraps(f)
    def decorator(*args, **kwargs):
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        if current_user and current_user.status == 'pending':
            return {"success": False, "msg": "pending", "status": "pending"}, 403
        return f(*args, **kwargs)
    return decorator


def supply_sheet_required(f):
    """
    Decorator that checks whether the authenticated user's role has the
    supply_sheet boolean permission set to True.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        from ..permissions import get_permissions
        if current_user and not get_permissions(current_user.role).get('supply_sheet', False):
            return {
                "success": False,
                "msg": "You do not have permission to access supply sheet."
            }, 403
        return f(*args, **kwargs)
    return wrapper


def upload_permission_required(upload_type: str):
    """
    Decorator factory that checks whether the authenticated user's role
    has permission to perform uploads of `upload_type`.

    Example:
        @upload_permission_required('orders')
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
            from ..permissions import can_upload
            if current_user and not can_upload(current_user.role, upload_type):
                return {
                    "success": False,
                    "msg": f"You do not have permission to perform {upload_type} uploads."
                }, 403
            return f(*args, **kwargs)
        return wrapper
    return decorator
