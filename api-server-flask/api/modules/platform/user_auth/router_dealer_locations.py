# -*- encoding: utf-8 -*-
"""
Dealer location approvals — admin only.

A sales rep standing at a dealer's shop photographs it; the device's GPS fix
travels with the photo (see POST /api/v1/dealers/<id>/location-photo). An admin
checks the photo looks like the right shop and approves, which writes the
coordinates onto the dealer.

The photo is evidence, not the record. Once a submission is decided — approved
or rejected — the image is deleted and only the coordinates and the audit row
survive, so proof photos don't pile up on disk.

Routes:
  GET  /api/admin/dealer-locations                 list submissions (default pending)
  GET  /api/admin/dealer-locations/<id>/photo      the proof photo (while pending)
  POST /api/admin/dealer-locations/<id>/approve    write coords to dealer, drop photo
  POST /api/admin/dealer-locations/<id>/reject     mark rejected, drop photo
"""

from datetime import datetime
from functools import wraps

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.db_manager import mysql_manager
from api.core.logging import get_logger
from api.shared import media

logger = get_logger(__name__)


def _admin_required(f):
    """Ensure the current user carries the 'admin' role."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        return f(*args, **kwargs)

    return wrapper


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


def _row_out(r):
    return {
        'submission_id': r['submission_id'],
        'dealer_id': r['dealer_id'],
        'dealer': r['dealer_name'],
        'dealer_code': r['dealer_code'],
        'town': r['town'],
        'submitted_by': r['submitted_by'],
        'submitted_by_name': r['username'],
        'latitude': float(r['latitude']),
        'longitude': float(r['longitude']),
        'accuracy_m': float(r['accuracy_m']) if r['accuracy_m'] is not None else None,
        'note': r['note'],
        'status': r['status'],
        # Absent once decided — the file is deleted at that point.
        'has_photo': bool(r['photo_path']),
        'created_at': _iso(r['created_at']),
        'reviewed_at': _iso(r['reviewed_at']),
    }


@rest_api.route('/api/admin/dealer-locations')
class DealerLocationList(Resource):

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        """List location submissions. `status` query param, default 'pending';
        pass 'all' to see decided ones too."""
        status = (request.args.get('status') or 'pending').strip()
        conds, params = [], []
        if status and status != 'all':
            conds.append("s.status = %s")
            params.append(status)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = mysql_manager.execute_query(
            f"""SELECT s.*, d.name AS dealer_name, d.dealer_code, d.town, u.username
                FROM dealer_location_submissions s
                JOIN dealer d ON d.dealer_id = s.dealer_id
                LEFT JOIN users u ON u.id = s.submitted_by
                {where}
                ORDER BY s.created_at DESC""",
            tuple(params)) or []
        return {'success': True, 'submissions': [_row_out(r) for r in rows]}, 200


@rest_api.route('/api/admin/dealer-locations/<int:submission_id>/photo')
class DealerLocationPhoto(Resource):

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user, submission_id):
        rows = mysql_manager.execute_query(
            "SELECT photo_path, mime_type FROM dealer_location_submissions "
            "WHERE submission_id = %s", (submission_id,))
        if not rows:
            return {'success': False, 'msg': 'submission not found'}, 404
        if not rows[0]['photo_path']:
            return {'success': False, 'msg': 'photo was removed after review'}, 410
        try:
            path = media.absolute_path(rows[0]['photo_path'])
        except media.MediaError:
            return {'success': False, 'msg': 'photo unavailable'}, 404
        return send_file(path, mimetype=rows[0]['mime_type'] or 'image/jpeg')


def _decide(submission_id, current_user, approve, note=None):
    """Shared approve/reject: guard the state machine, apply, then drop the photo."""
    rows = mysql_manager.execute_query(
        "SELECT * FROM dealer_location_submissions WHERE submission_id = %s",
        (submission_id,))
    if not rows:
        return {'success': False, 'msg': 'submission not found'}, 404
    sub = rows[0]
    if sub['status'] != 'pending':
        # Already decided — don't silently overwrite an earlier admin's call.
        return {'success': False, 'msg': f"already {sub['status']}"}, 409

    if approve:
        # Write the confirmed coordinates and ACTIVATE the dealer. A dealer proposed
        # from the field starts inactive and only goes live here; for a dealer that
        # was already active (a plain location capture) status = 'active' is a no-op.
        mysql_manager.execute_query(
            "UPDATE dealer SET latitude = %s, longitude = %s, status = 'active' "
            "WHERE dealer_id = %s",
            (sub['latitude'], sub['longitude'], sub['dealer_id']), fetch=False)

    mysql_manager.execute_query(
        """UPDATE dealer_location_submissions
              SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                  note = COALESCE(%s, note), photo_path = NULL
            WHERE submission_id = %s""",
        ('approved' if approve else 'rejected', current_user.id, note, submission_id),
        fetch=False)

    # Only after the row is updated: if this fails the photo is orphaned on disk,
    # which is harmless, whereas deleting first could lose evidence on a failure.
    media.delete_media(sub['photo_path'])

    logger.info("dealer %s location %s by user %s",
                sub['dealer_id'], 'approved' if approve else 'rejected', current_user.id)
    return {'success': True, 'status': 'approved' if approve else 'rejected',
            'dealer_id': sub['dealer_id']}, 200


@rest_api.route('/api/admin/dealer-locations/<int:submission_id>/approve')
class DealerLocationApprove(Resource):

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, submission_id):
        """Approve: the dealer gets these coordinates and the photo is deleted."""
        return _decide(submission_id, current_user, approve=True)


@rest_api.route('/api/admin/dealer-locations/<int:submission_id>/reject')
class DealerLocationReject(Resource):

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, submission_id):
        """Reject: the dealer keeps no coordinates, the photo is deleted, and the
        rep can capture a fresh one (the pending-duplicate guard is released)."""
        body = request.get_json(silent=True) or {}
        note = (body.get('note') or '').strip() or None
        return _decide(submission_id, current_user, approve=False, note=note)
