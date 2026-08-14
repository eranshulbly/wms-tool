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
from api.shared import media
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
        """Email is the only credential, on this app and the web one alike.

        The installed order app still posts the identifier under the key `username`, and
        there is no way to change that without shipping a new build — so both keys are
        accepted, but the lookup is on EMAIL either way. A person's name is not a login:
        typing it here fails exactly as any other wrong value would.
        """
        body = request.get_json(silent=True) or {}
        email = (body.get('email') or body.get('username') or '').strip()
        password = body.get('password') or ''
        if not email or not password:
            return {"detail": "email and password are required"}, 422

        rows = mysql_manager.execute_query(
            "SELECT id, name AS username, password, status FROM users WHERE email = %s", (email,)
        )
        if not rows or not check_password_hash(rows[0]['password'], password):
            return {"detail": "Invalid email or password"}, 401

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
        cols = ("company_id, name, order_capture_mode, analytics_mode, "
                "catalog_label_mode")
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
            # 'targets'  -> Busy-feed sales measured against dealer targets
            # 'invoices' -> a month total summed from uploaded invoices, no targets
            "analytics_mode": r['analytics_mode'],
            # 'code_first' -> order picker leads with the part number
            # 'name_first' -> it leads with the product name instead
            "catalog_label_mode": r['catalog_label_mode'],
        } for r in rows or []], 200


@rest_api.route('/api/v1/auth/users')
class V1Users(Resource):
    @v1_require_permission(rbac.P.USER_READ)
    def get(self, current_user):
        """List users, for admin pickers (e.g. the salesperson order filter)."""
        rows = mysql_manager.execute_query(
            """SELECT id AS user_id, name AS username, email, status, role
               FROM users WHERE status = 'active' ORDER BY name"""
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

        if mysql_manager.execute_query("SELECT id FROM users WHERE name = %s", (username,)):
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
            """INSERT INTO users (name, email, password, jwt_auth_active, date_joined, status, role)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (username, email, generate_password_hash(password), False,
             now_local(), 'active', primary_role),
            fetch=False,
        )
        new_user = mysql_manager.execute_query(
            "SELECT id, name AS username, email, status, date_joined FROM users WHERE name = %s", (username,)
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
        # The dealer table is aliased below, so scope the filter to that alias.
        frag, params = company_filter(current_user, column='d.company_id')
        where = "WHERE d.status = 'active'" + (f" AND {frag}" if frag else "")
        # No LIMIT: the app needs every dealer a rep might check into, and a
        # truncated list silently hides dealers (there are already more than the
        # old cap of 100). Active dealers are in the hundreds, not thousands.
        #
        # location_status tells the app whether to offer the "capture location"
        # action: 'stored' (coordinates known), 'pending' (a submission awaits
        # admin approval) or 'missing' (offer capture).
        rows = mysql_manager.execute_query(
            f"""SELECT d.dealer_id, d.dealer_code, d.name, d.email, d.phone, d.town,
                       d.status, d.created_at, d.latitude, d.longitude,
                       EXISTS(SELECT 1 FROM dealer_location_submissions s
                               WHERE s.dealer_id = d.dealer_id
                                 AND s.status = 'pending') AS has_pending
                FROM dealer d {where}
                ORDER BY d.name""",
            tuple(params),
        ) or []

        def _loc_status(r):
            if r['latitude'] is not None and r['longitude'] is not None:
                return 'stored'
            return 'pending' if r['has_pending'] else 'missing'

        return [{
            "dealer_id": r['dealer_id'], "dealer_code": r['dealer_code'], "name": r['name'],
            "email": r['email'], "phone": r['phone'], "town": r['town'],
            "status": r['status'], "created_at": _iso(r['created_at']),
            "latitude": float(r['latitude']) if r['latitude'] is not None else None,
            "longitude": float(r['longitude']) if r['longitude'] is not None else None,
            "location_status": _loc_status(r),
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


@rest_api.route('/api/v1/dealers/<int:dealer_id>/location-photo')
class V1DealerLocationPhoto(Resource):
    """A rep's proof-of-location capture for a dealer with no coordinates yet
    (multipart/form-data: photo, latitude, longitude, [accuracy_m], [note]).

    The photo is evidence for an admin, not the record: on approval the
    coordinates are written to the dealer and the image is deleted. Refused when
    the dealer already has coordinates, or already has a submission waiting —
    otherwise a dealer accumulates duplicates for an admin to sort out.
    """

    @v1_require_permission(rbac.P.DEALER_READ)
    def post(self, current_user, dealer_id):
        frag, cparams = company_filter(current_user, column='company_id')
        rows = mysql_manager.execute_query(
            "SELECT dealer_id, latitude, longitude FROM dealer WHERE dealer_id = %s"
            + (f" AND {frag}" if frag else ""),
            tuple([dealer_id] + list(cparams)))
        if not rows:
            return {"detail": f"dealer {dealer_id} not found"}, 404
        if rows[0]['latitude'] is not None and rows[0]['longitude'] is not None:
            return {"detail": "this dealer already has a stored location"}, 409

        if mysql_manager.execute_query(
                "SELECT submission_id FROM dealer_location_submissions "
                "WHERE dealer_id = %s AND status = 'pending'", (dealer_id,)):
            return {"detail": "a location for this dealer is already awaiting approval"}, 409

        form = request.form
        lat, lng = form.get('latitude'), form.get('longitude')
        if lat is None or lng is None:
            return {"detail": "latitude and longitude are required"}, 422
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return {"detail": "latitude/longitude must be numbers"}, 422
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return {"detail": "latitude/longitude out of range"}, 422
        try:
            accuracy = float(form['accuracy_m']) if form.get('accuracy_m') else None
        except (TypeError, ValueError):
            accuracy = None

        photo = request.files.get('photo')
        if photo is None:
            return {"detail": "a photo of the dealer is required"}, 422
        try:
            path, mime, size = media.save_dealer_location_photo(photo, dealer_id)
        except media.MediaError as e:
            return {"detail": str(e)}, 400

        mysql_manager.execute_query(
            """INSERT INTO dealer_location_submissions
                 (dealer_id, submitted_by, latitude, longitude, accuracy_m,
                  photo_path, mime_type, size_bytes, note, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
            (dealer_id, current_user['user_id'], lat, lng, accuracy,
             path, mime, size, (form.get('note') or '').strip() or None),
            fetch=False)

        return {"status": "pending",
                "detail": "sent for admin approval"}, 201


@rest_api.route('/api/v1/dealers')
class V1CreateDealer(Resource):
    """A rep proposes a NEW dealer from the field (multipart/form-data: name,
    latitude, longitude, [accuracy_m], photo).

    The dealer is created in the dealer table but INACTIVE, owned by the rep, with
    a pending location submission carrying the shopfront photo and GPS fix. An admin
    approving that submission writes the coordinates AND flips the dealer to active
    (see dealer-locations approve). Until then it never shows in the active dealer
    list, so it can't be checked into or ordered against.
    """

    @v1_require_permission(rbac.P.DEALER_READ)
    def post(self, current_user):
        form = request.form
        name = (form.get('name') or '').strip()
        if len(name) < 2:
            return {"detail": "a dealer name is required"}, 422

        lat, lng = form.get('latitude'), form.get('longitude')
        if lat is None or lng is None:
            return {"detail": "latitude and longitude are required"}, 422
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return {"detail": "latitude/longitude must be numbers"}, 422
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return {"detail": "latitude/longitude out of range"}, 422
        try:
            accuracy = float(form['accuracy_m']) if form.get('accuracy_m') else None
        except (TypeError, ValueError):
            accuracy = None

        photo = request.files.get('photo')
        if photo is None:
            return {"detail": "a photo of the dealer is required"}, 422

        # The new dealer joins the rep's own company (so it lands in their book once
        # approved); fall back to the caller's single scoped company.
        crows = mysql_manager.execute_query(
            "SELECT company_id FROM dealer "
            "WHERE sales_executive_id = %s AND company_id IS NOT NULL LIMIT 1",
            (current_user['user_id'],))
        company_id = crows[0]['company_id'] if crows else None
        if company_id is None:
            scoped = company_scope(current_user)
            company_id = scoped[0] if scoped else None
        if company_id is None:
            return {"detail": "no company assigned — ask an admin for access"}, 403

        # Create INACTIVE, owned by the rep; coordinates are written on approval.
        with mysql_manager.get_cursor() as cur:
            cur.execute(
                """INSERT INTO dealer (name, status, sales_executive_id, company_id)
                   VALUES (%s, 'inactive', %s, %s)""",
                (name, current_user['user_id'], company_id))
            dealer_id = cur.lastrowid

        try:
            path, mime, size = media.save_dealer_location_photo(photo, dealer_id)
        except media.MediaError as e:
            # Don't leave an inactive dealer with no evidence behind it.
            mysql_manager.execute_query(
                "DELETE FROM dealer WHERE dealer_id = %s", (dealer_id,), fetch=False)
            return {"detail": str(e)}, 400

        mysql_manager.execute_query(
            """INSERT INTO dealer_location_submissions
                 (dealer_id, submitted_by, latitude, longitude, accuracy_m,
                  photo_path, mime_type, size_bytes, note, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')""",
            (dealer_id, current_user['user_id'], lat, lng, accuracy,
             path, mime, size, 'New dealer — activate on approval'),
            fetch=False)

        return {"status": "pending", "dealer_id": dealer_id,
                "detail": "New dealer sent for admin approval"}, 201
