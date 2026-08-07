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
from api.shared.auth_v1 import v1_auth_required, company_scope, company_filter
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
        # What the rep wrote about this visit. One note per visit — the app edits
        # it in place rather than appending, so a visit has at most one entry in
        # the dealer's note history.
        "notes": v.get('notes'),
    }


_VISIT_COLS = """v.visit_id, v.user_id, v.dealer_id, v.company_id, v.status,
                 v.check_in_at, v.check_in_latitude, v.check_in_longitude, v.check_in_accuracy_m,
                 v.check_out_at, v.check_out_latitude, v.check_out_longitude, v.check_out_accuracy_m,
                 v.notes, d.name AS dealer_name"""

# Longest note we'll store. The column is TEXT, so this is a sanity bound on
# what a phone keyboard can reasonably produce, not a storage limit.
_NOTES_MAX = 4000


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


@rest_api.route('/api/v1/visits/<int:visit_id>/notes')
class V1VisitNotes(Resource):
    @v1_auth_required
    def put(self, current_user, visit_id):
        """Write the note for one visit, replacing whatever was there.

        A visit carries a single note, so this is an edit rather than an append —
        a rep refining what they wrote five minutes ago must not create a second
        entry in the dealer's history. Only the rep who made the visit may write
        it, and a checked-out visit stays editable so a note can be finished
        after leaving the shop.
        """
        body = request.get_json(silent=True) or {}
        if 'notes' not in body:
            return {"detail": "notes is required"}, 422
        notes = body.get('notes')
        notes = '' if notes is None else str(notes).strip()
        if len(notes) > _NOTES_MAX:
            return {"detail": f"notes must be at most {_NOTES_MAX} characters"}, 422

        visit = _visit_by_id(visit_id)
        if not visit:
            return {"detail": f"visit {visit_id} not found"}, 404
        if visit['user_id'] != current_user['user_id']:
            return {"detail": "you can only write notes on your own visits"}, 403

        mysql_manager.execute_query(
            "UPDATE dealer_visits SET notes = %s, updated_at = %s WHERE visit_id = %s",
            # An emptied note is cleared, not stored as '', so it drops out of the
            # history rather than showing as a blank entry.
            (notes or None, now_local(), visit_id),
            fetch=False,
        )
        return _visit_out(_visit_by_id(visit_id)), 200


@rest_api.route('/api/v1/visits/dealer/<int:dealer_id>/notes')
class V1DealerVisitNotes(Resource):
    @v1_auth_required
    def get(self, current_user, dealer_id):
        """Every note written about this dealer, newest visit first.

        Notes are shared across the team rather than private to their author:
        what a rep learned at a shop is worth having on the next visit whoever
        makes it. Visibility is bounded by the caller's company scope, and the
        author's name rides along so a note can be attributed and questioned.
        """
        try:
            limit = min(int(request.args.get('limit', 50)), 200)
        except ValueError:
            return {"detail": "limit must be an integer"}, 422

        conds = ["v.dealer_id = %s", "v.notes IS NOT NULL", "v.notes <> ''"]
        params = [dealer_id]
        frag, fparams = company_filter(current_user, 'v.company_id')
        if frag:
            conds.append(frag)
            params.extend(fparams)

        rows = mysql_manager.execute_query(
            f"""SELECT v.visit_id, v.user_id, v.dealer_id, v.check_in_at, v.check_out_at,
                       v.status, v.notes, v.updated_at, u.name AS author
                FROM dealer_visits v
                LEFT JOIN users u ON u.id = v.user_id
                WHERE {' AND '.join(conds)}
                ORDER BY v.check_in_at DESC, v.visit_id DESC
                LIMIT %s""",
            tuple(params + [limit]),
        ) or []
        return [{
            "visit_id": r['visit_id'],
            "dealer_id": r['dealer_id'],
            "check_in_at": _iso(r['check_in_at']),
            "check_out_at": _iso(r.get('check_out_at')),
            "status": r['status'],
            "notes": r['notes'],
            "updated_at": _iso(r.get('updated_at')),
            "author": r.get('author'),
            # Lets the app offer "edit" on the rep's own notes and not on others'.
            "is_mine": r['user_id'] == current_user['user_id'],
        } for r in rows], 200


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
