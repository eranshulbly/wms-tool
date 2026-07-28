# -*- encoding: utf-8 -*-
"""
Mobile API — dealer visits (/api/v1/visits/*).

A salesperson checks in when they reach a dealer and checks out when they leave;
time and location are captured at both ends. One visit stays `active` until
checked out, and a rep may only have one active visit at a time.
"""

from datetime import datetime, date

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.shared.db_manager import mysql_manager
from api.shared.auth_v1 import v1_auth_required, company_scope
from api.shared.timeutil import now_local


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _f(v):
    return float(v) if v is not None else None


def _visit_out(v):
    if v is None:
        return None
    return {
        "visit_id": v['visit_id'],
        "dealer_id": v['dealer_id'],
        "dealer_name": v.get('dealer_name'),
        "company_id": v.get('company_id'),
        "status": v['status'],
        "check_in_at": _iso(v['check_in_at']),
        "check_in_latitude": _f(v.get('check_in_latitude')),
        "check_in_longitude": _f(v.get('check_in_longitude')),
        "check_in_accuracy_m": v.get('check_in_accuracy_m'),
        "check_out_at": _iso(v.get('check_out_at')),
        "check_out_latitude": _f(v.get('check_out_latitude')),
        "check_out_longitude": _f(v.get('check_out_longitude')),
        "check_out_accuracy_m": v.get('check_out_accuracy_m'),
    }


_VISIT_COLS = """v.visit_id, v.user_id, v.dealer_id, v.company_id, v.status,
                 v.check_in_at, v.check_in_latitude, v.check_in_longitude, v.check_in_accuracy_m,
                 v.check_out_at, v.check_out_latitude, v.check_out_longitude, v.check_out_accuracy_m,
                 d.name AS dealer_name"""


def _active_visit(user_id):
    rows = mysql_manager.execute_query(
        f"""SELECT {_VISIT_COLS} FROM dealer_visits v
            LEFT JOIN dealer d ON d.dealer_id = v.dealer_id
            WHERE v.user_id = %s AND v.status = 'active'
            ORDER BY v.visit_id DESC LIMIT 1""",
        (user_id,),
    )
    return rows[0] if rows else None


def _visit_by_id(visit_id):
    rows = mysql_manager.execute_query(
        f"""SELECT {_VISIT_COLS} FROM dealer_visits v
            LEFT JOIN dealer d ON d.dealer_id = v.dealer_id
            WHERE v.visit_id = %s""",
        (visit_id,),
    )
    return rows[0] if rows else None


def _coords(body):
    """Validate and return (lat, lng, accuracy) or raise ValueError with a message."""
    lat, lng = body.get('latitude'), body.get('longitude')
    if lat is None or lng is None:
        raise ValueError("latitude and longitude are required")
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError("latitude/longitude must be numbers")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise ValueError("latitude/longitude out of range")
    try:
        acc = float(body['location_accuracy_m']) if body.get('location_accuracy_m') is not None else None
    except (TypeError, ValueError):
        acc = None
    return lat, lng, acc


@rest_api.route('/api/v1/visits/active')
class V1ActiveVisit(Resource):
    @v1_auth_required
    def get(self, current_user):
        """The caller's current active visit, or {"active": null} if none."""
        return {"active": _visit_out(_active_visit(current_user['user_id']))}, 200


@rest_api.route('/api/v1/visits/check-in')
class V1CheckIn(Resource):
    @v1_auth_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        dealer_id = body.get('dealer_id')
        if not dealer_id:
            return {"detail": "dealer_id is required"}, 422
        try:
            lat, lng, acc = _coords(body)
        except ValueError as e:
            return {"detail": str(e)}, 422

        # One active visit at a time — must check out before checking in elsewhere.
        existing = _active_visit(current_user['user_id'])
        if existing:
            return {"detail": "already checked in — check out first",
                    "active": _visit_out(existing)}, 409

        # Dealer must exist, be active, and be in the caller's company scope.
        dealer = mysql_manager.execute_query(
            "SELECT dealer_id, status, company_id FROM dealer WHERE dealer_id = %s", (dealer_id,)
        )
        if not dealer or (dealer[0].get('status') or 'active') != 'active':
            return {"detail": f"dealer {dealer_id} not found or inactive"}, 404
        scoped = company_scope(current_user)
        if scoped is not None and dealer[0].get('company_id') not in scoped:
            return {"detail": "dealer is not in your company"}, 403

        now = now_local()
        mysql_manager.execute_query(
            """INSERT INTO dealer_visits
                 (user_id, dealer_id, company_id, check_in_at,
                  check_in_latitude, check_in_longitude, check_in_accuracy_m, status,
                  created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)""",
            (current_user['user_id'], dealer_id, dealer[0].get('company_id'), now, lat, lng, acc,
             now, now),
            fetch=False,
        )
        return _visit_out(_active_visit(current_user['user_id'])), 201


@rest_api.route('/api/v1/visits/check-out')
class V1CheckOut(Resource):
    @v1_auth_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        try:
            lat, lng, acc = _coords(body)
        except ValueError as e:
            return {"detail": str(e)}, 422

        visit = _active_visit(current_user['user_id'])
        if not visit:
            return {"detail": "no active visit to check out of"}, 409

        now = now_local()
        mysql_manager.execute_query(
            """UPDATE dealer_visits
               SET check_out_at = %s, check_out_latitude = %s, check_out_longitude = %s,
                   check_out_accuracy_m = %s, status = 'checked_out', updated_at = %s
               WHERE visit_id = %s""",
            (now, lat, lng, acc, now, visit['visit_id']),
            fetch=False,
        )
        return _visit_out(_visit_by_id(visit['visit_id'])), 200
