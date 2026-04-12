# -*- encoding: utf-8 -*-
"""
Authentication routes: Register, Login, EditUser, LogoutUser.
"""

from datetime import datetime, timezone, timedelta

import jwt
from flask import request
from flask_restx import Resource, fields

from ..extensions import rest_api
from ..core.auth import token_required
from ..config import BaseConfig
from ..models import Users, JWTTokenBlocklist
from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Request / Response Models ────────────────────────────────────────────────

signup_model = rest_api.model('SignUpModel', {
    "username": fields.String(required=True, min_length=2, max_length=32),
    "email":    fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16),
})

login_model = rest_api.model('LoginModel', {
    "email":    fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16),
})

user_edit_model = rest_api.model('UserEditModel', {
    "userID":   fields.String(required=True, min_length=1, max_length=32),
    "username": fields.String(required=True, min_length=2, max_length=32),
    "email":    fields.String(required=True, min_length=4, max_length=64),
})

# ── Endpoints ────────────────────────────────────────────────────────────────

@rest_api.route('/api/users/register')
class Register(Resource):
    """Creates a new user by taking 'signup_model' input."""

    @rest_api.expect(signup_model, validate=True)
    def post(self):
        req_data = request.get_json()

        _username = req_data.get("username")
        _email    = req_data.get("email")
        _password = req_data.get("password")

        if Users.get_by_email(_email):
            return {"success": False, "msg": "Email already taken"}, 400

        new_user = Users(username=_username, email=_email, status='pending', role='viewer')
        new_user.set_password(_password)
        new_user.save()

        return {"success": True,
                "userID": new_user.id,
                "msg": "Registration successful. Your account is pending admin approval."}, 200


@rest_api.route('/api/users/login')
class Login(Resource):
    """Login user by taking 'login_model' input and return JWT token."""

    @rest_api.expect(login_model, validate=True)
    def post(self):
        req_data = request.get_json()

        _email    = req_data.get("email")
        _password = req_data.get("password")

        user_exists = Users.get_by_email(_email)

        if not user_exists:
            return {"success": False, "msg": "Wrong credentials."}, 400

        if not user_exists.check_password(_password):
            return {"success": False, "msg": "Wrong credentials."}, 400

        # Bug 9 fix: reject blocked users before issuing a token
        if user_exists.status == 'blocked':
            return {"success": False, "msg": "Account has been blocked."}, 403

        # Build warehouse/company access list
        from ..models import UserWarehouseCompany
        from ..permissions import get_permissions, has_all_warehouse_access
        perms = get_permissions(user_exists.role)
        if has_all_warehouse_access(user_exists.role):
            wh_access = []  # empty = all access for admin
        else:
            wh_access = UserWarehouseCompany.get_for_user(user_exists.id)
            wh_access = [{'warehouse_id': r['warehouse_id'], 'company_id': r['company_id']} for r in wh_access]

        token = jwt.encode({
            "email":   user_exists.email,
            "user_id": user_exists.id,
            "role":    user_exists.role,
            "status":  user_exists.status,
            "exp":     datetime.utcnow() + timedelta(hours=8)
        }, BaseConfig.SECRET_KEY, algorithm="HS256")

        user_exists.set_jwt_auth_active(True)
        user_exists.save()

        return {"success": True,
                "token": token,
                "user": {
                    **user_exists.toJSON(),
                    "status": user_exists.status,
                    "role":   user_exists.role,
                    "permissions": {
                        "order_states":             perms['order_states'],
                        "uploads":                  perms['uploads'],
                        "all_warehouses":           perms['all_warehouses'],
                        "eway_bill_admin":          perms.get('eway_bill_admin',   False),
                        "eway_bill_filling":        perms.get('eway_bill_filling', False),
                        "warehouse_company_access": wh_access,
                    }
                }}, 200


@rest_api.route('/api/users/edit')
class EditUser(Resource):
    """Edit User's username or email using 'user_edit_model' input."""

    @rest_api.expect(user_edit_model)
    @token_required
    def post(self, current_user):
        req_data = request.get_json()

        _new_username = req_data.get("username")
        _new_email    = req_data.get("email")

        # Bug 47 fix: reject if the new email/username is already taken
        if _new_username and _new_username != current_user.username:
            if Users.get_by_username(_new_username):
                return {"success": False, "msg": "Username already taken."}, 400
            current_user.update_username(_new_username)

        if _new_email and _new_email != current_user.email:
            if Users.get_by_email(_new_email):
                return {"success": False, "msg": "Email already taken."}, 400
            current_user.update_email(_new_email)

        current_user.save()
        return {"success": True}, 200


@rest_api.route('/api/users/logout')
class LogoutUser(Resource):
    """Logs out User using JWT token."""

    @token_required
    def post(self, current_user):
        # Bug 28 fix: strip 'Bearer ' prefix so the stored token matches what
        # token_required checks against the blocklist.
        raw = request.headers.get("authorization", "")
        _jwt_token = raw[7:] if raw.startswith("Bearer ") or raw.startswith("bearer ") else raw

        jwt_block = JWTTokenBlocklist(jwt_token=_jwt_token, created_at=datetime.now(timezone.utc))
        jwt_block.save()

        current_user.set_jwt_auth_active(False)
        current_user.save()

        return {"success": True}, 200
