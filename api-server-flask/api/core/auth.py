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

from functools import wraps

import jwt
from flask import request

from ..config import BaseConfig
from ..db_manager import mysql_manager, partition_filter
from ..core.logging import get_logger

logger = get_logger(__name__)


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
