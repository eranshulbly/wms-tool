# -*- encoding: utf-8 -*-
"""
Mobile API — user_auth module (/api/v1/auth/*).

Ports wms-v2-backend's auth endpoints onto this backend's users/roles, using the
unified RBAC (see rbac.py) and this backend's JWT secret. Contracts match v2 so
the Android app only changes its base host.

  GET  /api/v1/auth            module status
  POST /api/v1/auth/login      username+password -> access+refresh
  POST /api/v1/auth/refresh    rotate refresh token
  GET  /api/v1/auth/me         current user + effective permissions
  POST /api/v1/auth/users      create user (user:manage)
  GET  /api/v1/auth/dealers    list active dealers (dealer:read)
  POST /api/v1/auth/dealers    create dealer (dealer:manage)
"""

from datetime import datetime

from flask import request
from flask_restx import Resource
from werkzeug.security import check_password_hash, generate_password_hash

from api.extensions import rest_api
from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.shared.timeutil import now_local
from api.shared.auth_v1 import (v1_auth_required, v1_require_permission,
                                company_filter, company_scope)
from api.modules.platform.user_auth import rbac, tokens

logger = get_logger(__name__)


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


@rest_api.route('/api/v1/auth')
class V1AuthStatus(Resource):
    def get(self):
        return {"module": "user_auth", "status": "ok"}, 200


@rest_api.route('/api/v1/auth/login')
class V1Login(Resource):
    def post(self):
        body = request.get_json(silent=True) or {}
        username = (body.get('username') or '').strip()
        password = body.get('password') or ''
        if not username or not password:
            return {"detail": "username and password are required"}, 422

        rows = mysql_manager.execute_query(
            "SELECT id, username, password, status FROM users WHERE username = %s", (username,)
        )
        if not rows or not check_password_hash(rows[0]['password'], password):
            return {"detail": "Invalid username or password"}, 401

        user = rows[0]
        if user['status'] != 'active':
            return {"detail": f"Account is {user['status']}"}, 401

        access, refresh = tokens.issue_tokens(user['id'], request.headers.get('User-Agent'))
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}, 200


@rest_api.route('/api/v1/auth/refresh')
class V1Refresh(Resource):
    def post(self):
        body = request.get_json(silent=True) or {}
        raw = body.get('refresh_token')
        if not raw:
            return {"detail": "refresh_token is required"}, 422
        try:
            access, refresh, _ = tokens.rotate_refresh_token(raw, request.headers.get('User-Agent'))
        except ValueError as e:
            return {"detail": str(e)}, 401
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}, 200


@rest_api.route('/api/v1/auth/me')
class V1Me(Resource):
    @v1_auth_required
    def get(self, current_user):
        return {
            "user_id": current_user['user_id'],
            "username": current_user['username'],
            "permissions": current_user['permissions'],
            "roles": current_user['roles'],
            "warehouse_ids": current_user['warehouse_ids'],
            "has_all_warehouses": current_user['has_all_warehouses'],
            "company_ids": current_user['company_ids'],
            "has_all_companies": current_user['has_all_companies'],
        }, 200


@rest_api.route('/api/v1/companies')
class V1Companies(Resource):
    """The companies the caller may see — the source of truth for company scoping."""

    @v1_auth_required
    def get(self, current_user):
        scoped = current_user['company_ids']
        cols = "company_id, name, order_capture_mode"
        if scoped is None:
            rows = mysql_manager.execute_query(
                f"SELECT {cols} FROM company ORDER BY name"
            )
        elif not scoped:
            rows = []
        else:
            rows = mysql_manager.execute_query(
                f"SELECT {cols} FROM company WHERE company_id IN (%s) ORDER BY name"
                % ','.join(['%s'] * len(scoped)),
                tuple(scoped),
            )
        return [{
            "company_id": r['company_id'],
            "name": r['name'],
            # 'photo'    -> reps capture a picture of the paper order
            # 'itemised' -> reps pick dealer + products in the app
            "order_capture_mode": r['order_capture_mode'],
        } for r in rows or []], 200


@rest_api.route('/api/v1/auth/users')
class V1Users(Resource):
    @v1_require_permission(rbac.P.USER_READ)
    def get(self, current_user):
        """List users, for admin pickers (e.g. the salesperson order filter)."""
        rows = mysql_manager.execute_query(
            """SELECT id AS user_id, username, email, status, role
               FROM users WHERE status = 'active' ORDER BY username"""
        ) or []
        return [{
            "user_id": r['user_id'], "username": r['username'],
            "email": r['email'], "status": r['status'], "role": r['role'],
        } for r in rows], 200

    @v1_require_permission(rbac.P.USER_MANAGE)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        username = (body.get('username') or '').strip()
        email = (body.get('email') or '').strip()
        password = body.get('password') or ''
        if len(username) < 3 or len(username) > 64 or not email or len(password) < 8:
            return {"detail": "username (3-64), email and password (min 8) are required"}, 422

        if mysql_manager.execute_query("SELECT id FROM users WHERE username = %s", (username,)):
            return {"detail": f"username '{username}' already exists"}, 409
        if mysql_manager.execute_query("SELECT id FROM users WHERE email = %s", (email,)):
            return {"detail": f"email '{email}' already exists"}, 409

        role_names = body.get('role_names') or []
        roles = []
        if role_names:
            rows = mysql_manager.execute_query(
                "SELECT role_id, name FROM roles WHERE name IN (%s)" %
                ','.join(['%s'] * len(role_names)), tuple(role_names)
            ) or []
            found = {r['name'] for r in rows}
            missing = sorted(set(role_names) - found)
            if missing:
                return {"detail": f"unknown role(s): {missing}"}, 400
            roles = rows

        # users.role keeps the primary role for the existing web app.
        primary_role = role_names[0] if role_names else 'viewer'
        mysql_manager.execute_query(
            """INSERT INTO users (username, email, password, jwt_auth_active, date_joined, status, role)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (username, email, generate_password_hash(password), False,
             now_local(), 'active', primary_role),
            fetch=False,
        )
        new_user = mysql_manager.execute_query(
            "SELECT id, username, email, status, date_joined FROM users WHERE username = %s", (username,)
        )[0]

        for r in roles:
            mysql_manager.execute_query(
                "INSERT IGNORE INTO user_roles (user_id, role_id, assigned_by) VALUES (%s, %s, %s)",
                (new_user['id'], r['role_id'], current_user['user_id']), fetch=False,
            )
        # Scope grants are (warehouse, company) pairs — company_id is NOT NULL, so a
        # bare warehouse_ids list can't be honoured. Accept explicit pairs, or the
        # warehouse_ids x company_ids cross product as a convenience.
        grants = body.get('grants')
        if grants is None:
            wids = body.get('warehouse_ids') or []
            cids = body.get('company_ids') or []
            if wids and not cids:
                return {"detail": "warehouse_ids requires company_ids, or pass "
                                  "grants: [{warehouse_id, company_id}]"}, 422
            grants = [{'warehouse_id': w, 'company_id': c} for w in wids for c in cids]

        for g in grants:
            mysql_manager.execute_query(
                """INSERT IGNORE INTO user_warehouse_company (user_id, warehouse_id, company_id)
                   VALUES (%s, %s, %s)""",
                (new_user['id'], g.get('warehouse_id'), g.get('company_id')), fetch=False,
            )

        return {
            "user_id": new_user['id'],
            "username": new_user['username'],
            "email": new_user['email'],
            "full_name": body.get('full_name'),
            "status": new_user['status'],
            "roles": rbac.get_user_roles(new_user['id']),
            "created_at": _iso(new_user['date_joined']),
        }, 201


@rest_api.route('/api/v1/auth/dealers')
class V1Dealers(Resource):
    @v1_require_permission(rbac.P.DEALER_READ)
    def get(self, current_user):
        # Dealers belong to a company; one with no company stays hidden until assigned.
        frag, params = company_filter(current_user)
        where = "WHERE status = 'active'" + (f" AND {frag}" if frag else "")
        rows = mysql_manager.execute_query(
            f"""SELECT dealer_id, dealer_code, name, email, phone, town, status, created_at
                FROM dealer {where} ORDER BY name LIMIT 100""",
            tuple(params),
        ) or []
        return [{
            "dealer_id": r['dealer_id'], "dealer_code": r['dealer_code'], "name": r['name'],
            "email": r['email'], "phone": r['phone'], "town": r['town'],
            "status": r['status'], "created_at": _iso(r['created_at']),
        } for r in rows], 200

    @v1_require_permission(rbac.P.DEALER_MANAGE)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        code = (body.get('dealer_code') or '').strip()
        name = (body.get('name') or '').strip()
        if not code or not name:
            return {"detail": "dealer_code and name are required"}, 422

        if mysql_manager.execute_query("SELECT dealer_id FROM dealer WHERE dealer_code = %s", (code,)):
            return {"detail": f"dealer_code '{code}' already exists"}, 409

        # Stamp the owning company, else a scoped user creates dealers they can't see.
        company_id = body.get('company_id')
        scoped = company_scope(current_user)
        if scoped is not None:
            if not scoped:
                return {"detail": "no company assigned — ask an admin for access"}, 403
            if company_id is None:
                if len(scoped) > 1:
                    return {"detail": "company_id is required (you have several)"}, 422
                company_id = scoped[0]
            elif company_id not in scoped:
                return {"detail": f"company {company_id} is not yours"}, 403

        mysql_manager.execute_query(
            """INSERT INTO dealer (dealer_code, name, email, phone, town, address, gstin,
                                   status, company_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)""",
            (code, name, body.get('email'), body.get('phone'), body.get('town'),
             body.get('address'), body.get('gstin'), company_id),
            fetch=False,
        )
        r = mysql_manager.execute_query(
            """SELECT dealer_id, dealer_code, name, email, phone, town, status, created_at
               FROM dealer WHERE dealer_code = %s""", (code,)
        )[0]
        return {
            "dealer_id": r['dealer_id'], "dealer_code": r['dealer_code'], "name": r['name'],
            "email": r['email'], "phone": r['phone'], "town": r['town'],
            "status": r['status'], "created_at": _iso(r['created_at']),
        }, 201
