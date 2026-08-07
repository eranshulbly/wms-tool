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

from flask import request
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
        'submitted_by_name': r['submitted_by_name'],
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
            f"""SELECT s.*, d.name AS dealer_name, d.dealer_code, d.town,
                       u.name AS submitted_by_name
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
            resp = media.send_media(rows[0]['photo_path'], rows[0]['mime_type'])
        except media.MediaError:
            return {'success': False, 'msg': 'photo unavailable'}, 404
        if resp is None:
            return {'success': False, 'msg': 'photo unavailable'}, 404
        return resp


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


# ---------------------------------------------------------------------------
# Dealer records themselves — creation and approval
#
# Two ways a dealer comes into being, both landing on this screen:
#   * a rep proposes one from the field (POST /api/v1/dealers) — created INACTIVE with
#     a pending location submission carrying the shopfront photo;
#   * an admin adds one here — created ACTIVE, because the person who would approve it
#     is the one entering it.
#
# Approving the location submission already activates a rep-proposed dealer. The
# endpoints below cover what that flow cannot: a dealer whose submission was rejected,
# or one created before location capture existed, still has to be decided on its own.
# ---------------------------------------------------------------------------

_DEALER_FIELDS = ('dealer_code', 'town', 'email', 'phone', 'address', 'gstin')


def _dealer_out(r):
    return {
        'dealer_id': r['dealer_id'],
        'name': r['name'],
        'dealer_code': r['dealer_code'] or '',
        'town': r['town'] or '',
        'phone': r['phone'] or '',
        'email': r['email'] or '',
        'status': r['status'],
        'company_id': r['company_id'],
        'company': r.get('company_name'),
        'sales_executive_id': r['sales_executive_id'],
        'sales_executive': r.get('exec_name'),
        'latitude': float(r['latitude']) if r['latitude'] is not None else None,
        'longitude': float(r['longitude']) if r['longitude'] is not None else None,
        'created_at': _iso(r['created_at']),
        # Whether a location submission is still waiting on this dealer. The two queues
        # overlap for a rep-proposed dealer, and an admin needs to see that rather than
        # approve the dealer and leave its photo sitting in the other list.
        'pending_location': bool(r.get('pending_location')),
    }


@rest_api.route('/api/admin/dealers/pending')
class AdminPendingDealers(Resource):
    """Dealers awaiting a decision — everything not yet active."""

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        status = (request.args.get('status') or 'inactive').strip()
        conds, params = [], []
        if status != 'all':
            conds.append("d.status = %s")
            params.append(status)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = mysql_manager.execute_query(
            f"""SELECT d.*, co.name AS company_name, u.name AS exec_name,
                       (SELECT COUNT(*) FROM dealer_location_submissions s
                         WHERE s.dealer_id = d.dealer_id AND s.status = 'pending')
                         AS pending_location
                FROM dealer d
                LEFT JOIN company co ON co.company_id = d.company_id
                LEFT JOIN users u ON u.id = d.sales_executive_id
                {where}
                ORDER BY d.created_at DESC""",
            tuple(params)) or []
        return {'success': True, 'dealers': [_dealer_out(r) for r in rows]}, 200


@rest_api.route('/api/admin/dealers/create')
class AdminCreateDealer(Resource):
    """Admin-created dealer. Active immediately — an admin entering it IS the approval."""

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        name = (body.get('name') or '').strip()
        if len(name) < 2:
            return {'success': False, 'msg': 'A dealer name is required.'}, 422

        company_id = body.get('company_id')
        if not company_id:
            return {'success': False, 'msg': 'A company is required.'}, 422

        vals = {f: ((body.get(f) or '').strip() or None) for f in _DEALER_FIELDS}

        # dealer_code carries a UNIQUE index — check it here so the admin gets a clear
        # message instead of a raw duplicate-key error.
        if vals['dealer_code']:
            clash = mysql_manager.execute_query(
                "SELECT dealer_id FROM dealer WHERE dealer_code = %s", (vals['dealer_code'],))
            if clash:
                return {'success': False,
                        'msg': f"Dealer code \"{vals['dealer_code']}\" is already in use."}, 409
        # Name is how sales data is attributed (busy_sales_data.particulars = dealer.name),
        # so a duplicate name inside a company would split that dealer's sales in two.
        dupe = mysql_manager.execute_query(
            "SELECT dealer_id FROM dealer WHERE name = %s AND company_id = %s",
            (name, company_id))
        if dupe:
            return {'success': False,
                    'msg': f'A dealer named "{name}" already exists in this company.'}, 409

        exec_id = body.get('sales_executive_id') or None
        try:
            with mysql_manager.get_cursor() as cur:
                cur.execute(
                    """INSERT INTO dealer
                         (name, dealer_code, town, email, phone, address, gstin,
                          company_id, sales_executive_id, status, activated_on)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',NOW())""",
                    (name, vals['dealer_code'], vals['town'], vals['email'], vals['phone'],
                     vals['address'], vals['gstin'], company_id, exec_id))
                dealer_id = cur.lastrowid
        except Exception as e:
            logger.exception('Error creating dealer')
            return {'success': False, 'msg': f'Could not create dealer: {e}'}, 400

        logger.info('dealer %s created by admin %s', dealer_id, current_user.id)
        return {'success': True, 'dealer_id': dealer_id, 'name': name}, 201


def _pending_submission(dealer_id):
    rows = mysql_manager.execute_query(
        "SELECT submission_id, photo_path FROM dealer_location_submissions "
        "WHERE dealer_id = %s AND status = 'pending' ORDER BY created_at DESC",
        (dealer_id,)) or []
    return rows


def _decide_dealer(dealer_id, current_user, approve, note=None):
    """Approve (activate) or reject a proposed dealer.

    A rep-proposed dealer arrives with a pending location submission, and THAT is the
    canonical activation: approving it writes the confirmed coordinates, flips the dealer
    active and deletes the photo. So approving from this queue delegates to _decide()
    whenever a submission is waiting — otherwise the dealer would go live with no
    coordinates and its photo would sit orphaned in the other list.

    Only a dealer with nothing pending (its submission was rejected, or it predates
    location capture) is activated directly here.
    """
    rows = mysql_manager.execute_query(
        "SELECT dealer_id, name, status FROM dealer WHERE dealer_id = %s", (dealer_id,))
    if not rows:
        return {'success': False, 'msg': 'dealer not found'}, 404
    if rows[0]['status'] == 'active':
        return {'success': False, 'msg': 'already active'}, 409

    subs = _pending_submission(dealer_id)

    if approve:
        if subs:
            # One decision, one code path — coordinates, activation and photo cleanup.
            return _decide(subs[0]['submission_id'], current_user, approve=True)
        mysql_manager.execute_query(
            "UPDATE dealer SET status = 'active', activated_on = NOW() WHERE dealer_id = %s",
            (dealer_id,), fetch=False)
        logger.info('dealer %s activated (no location on file) by user %s',
                    dealer_id, current_user.id)
        return {'success': True, 'dealer_id': dealer_id, 'status': 'active',
                'located': False}, 200

    mysql_manager.execute_query(
        "UPDATE dealer SET status = 'rejected' WHERE dealer_id = %s", (dealer_id,),
        fetch=False)
    # A rejected dealer must not leave its photo waiting in the location queue — the two
    # lists would then disagree about whether anything is still to be done.
    for s in subs:
        mysql_manager.execute_query(
            """UPDATE dealer_location_submissions
                  SET status = 'rejected', reviewed_by = %s, reviewed_at = NOW(),
                      note = COALESCE(%s, note), photo_path = NULL
                WHERE submission_id = %s""",
            (current_user.id, note, s['submission_id']), fetch=False)
        media.delete_media(s['photo_path'])

    logger.info('dealer %s rejected by user %s', dealer_id, current_user.id)
    return {'success': True, 'dealer_id': dealer_id, 'status': 'rejected'}, 200


@rest_api.route('/api/admin/dealers/<int:dealer_id>/approve')
class AdminDealerApprove(Resource):

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, dealer_id):
        """Activate a proposed dealer. Its location submission, if any, stays pending —
        the coordinates are a separate decision with its own evidence."""
        return _decide_dealer(dealer_id, current_user, approve=True)


@rest_api.route('/api/admin/dealers/<int:dealer_id>/reject')
class AdminDealerReject(Resource):

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, dealer_id):
        """Reject a proposed dealer, closing any pending location submission with it."""
        body = request.get_json(silent=True) or {}
        note = (body.get('note') or '').strip() or None
        return _decide_dealer(dealer_id, current_user, approve=False, note=note)


# ---------------------------------------------------------------------------
# Dealer book — who owns each dealer and what it is targeted at this month
#
# One screen for the two things an admin changes about a live dealer: which executive
# carries it, and its rupee targets for the month. Both are edited in place; neither
# needs an approval step, because an admin making the change IS the authority.
# ---------------------------------------------------------------------------

def _current_period():
    """First of the current month — the grain every target table is keyed on."""
    today = datetime.utcnow().date()
    return today.replace(day=1)


@rest_api.route('/api/admin/dealers/manage')
class AdminDealerManage(Resource):
    """The dealer book: every dealer, its executive, and its targets for one month.

    Filter options travel with the payload rather than needing their own calls — the
    lists are small and always wanted together, so one round trip beats four.
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        period = (request.args.get('period') or '').strip() or _current_period().isoformat()

        conds, params = [], []
        search = (request.args.get('search') or '').strip()
        if search:
            conds.append("(LOWER(d.name) LIKE %s OR LOWER(COALESCE(d.dealer_code,'')) LIKE %s "
                         "OR LOWER(COALESCE(d.town,'')) LIKE %s)")
            like = f"%{search.lower()}%"
            params += [like, like, like]
        for param, col in (('company_id', 'd.company_id'), ('exec_id', 'd.sales_executive_id')):
            val = request.args.get(param, type=int)
            if val:
                conds.append(f"{col} = %s")
                params.append(val)
        # 'unassigned' is a real thing to look for — it is the dealer nobody is working.
        if (request.args.get('exec') or '') == 'unassigned':
            conds.append("d.sales_executive_id IS NULL")
        status = (request.args.get('status') or '').strip()
        if status and status != 'all':
            conds.append("d.status = %s")
            params.append(status)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        try:
            page = max(1, int(request.args.get('page') or 1))
            page_size = int(request.args.get('page_size') or 25)
        except (TypeError, ValueError):
            return {'success': False, 'msg': 'page and page_size must be numbers'}, 422
        page_size = max(1, min(page_size, 200))

        total = (mysql_manager.execute_query(
            f"SELECT COUNT(*) AS n FROM dealer d {where}", tuple(params))
            or [{'n': 0}])[0]['n']
        # A filter change can leave the caller past the end; clamp rather than return an
        # empty page that looks like "no dealers match".
        pages = max(1, -(-total // page_size))
        page = min(page, pages)
        offset = (page - 1) * page_size

        rows = mysql_manager.execute_query(
            f"""SELECT d.dealer_id, d.name, d.dealer_code, d.town, d.status,
                       d.company_id, co.name AS company_name,
                       d.sales_executive_id, u.name AS exec_name
                FROM dealer d
                LEFT JOIN company co ON co.company_id = d.company_id
                LEFT JOIN users u ON u.id = d.sales_executive_id
                {where}
                ORDER BY d.name
                LIMIT %s OFFSET %s""",
            tuple(params + [page_size, offset])) or []

        # Which categories carry a target anywhere in the FILTERED BOOK, not just on this
        # page. Deriving the columns from the page would make them appear and disappear as
        # the admin pages through, and a target would look lost when it had only moved.
        used_cats = [r['category_id'] for r in (mysql_manager.execute_query(
            f"""SELECT DISTINCT mt.category_id
                FROM dealer d
                JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
                {where + (' AND ' if where else 'WHERE ')} mt.target_period = %s""",
            tuple(params + [period])) or [])]

        # Targets for the whole page in one query, then attached in Python — a per-dealer
        # query here would be one round trip per row.
        ids = [r['dealer_id'] for r in rows]
        targets = {}
        if ids:
            ph = ",".join(["%s"] * len(ids))
            trows = mysql_manager.execute_query(
                f"""SELECT mt.dealer_id, mt.category_id, c.name AS category, mt.value_target
                    FROM dealer_money_target mt
                    JOIN categories c ON c.category_id = mt.category_id
                    WHERE mt.target_period = %s AND mt.dealer_id IN ({ph})""",
                (period, *ids)) or []
            for t in trows:
                targets.setdefault(t['dealer_id'], {})[t['category_id']] = {
                    'category': t['category'], 'value_target': float(t['value_target']),
                }

        cats = mysql_manager.execute_query(
            "SELECT category_id, name FROM categories WHERE is_active = 1 ORDER BY name") or []
        execs = mysql_manager.execute_query(
            "SELECT id, name FROM users WHERE role = 'sales_executive' ORDER BY name") or []
        companies = mysql_manager.execute_query(
            "SELECT company_id, name FROM company ORDER BY name") or []

        out = []
        for r in rows:
            t = targets.get(r['dealer_id'], {})
            out.append({
                'dealer_id': r['dealer_id'],
                'name': r['name'],
                'dealer_code': r['dealer_code'] or '',
                'town': r['town'] or '',
                'status': r['status'],
                'company_id': r['company_id'],
                'company': r['company_name'],
                'sales_executive_id': r['sales_executive_id'],
                'sales_executive': r['exec_name'],
                # Keyed by category id so the editor can address a category that has no
                # row yet without inventing one.
                'targets': {str(cid): v['value_target'] for cid, v in t.items()},
                'target_total': round(sum(v['value_target'] for v in t.values()), 2),
            })

        return {
            'success': True,
            'period': period,
            'dealers': out,
            'page': page,
            'page_size': page_size,
            'pages': pages,
            'total': total,
            'categories': [{'id': c['category_id'], 'name': c['name']} for c in cats],
            # The target columns to render, fixed across every page of this filter.
            'target_categories': [c['category_id'] for c in cats
                                  if c['category_id'] in set(used_cats)],
            'executives': [{'id': u['id'], 'name': u['name']} for u in execs],
            'companies': [{'id': c['company_id'], 'name': c['name']} for c in companies],
        }, 200


@rest_api.route('/api/admin/dealers/<int:dealer_id>/executive')
class AdminDealerExecutive(Resource):
    """Assign or change the executive who carries a dealer."""

    @token_required
    @active_required
    @_admin_required
    def patch(self, current_user, dealer_id):
        body = request.get_json(silent=True) or {}
        exec_id = body.get('sales_executive_id')

        if not mysql_manager.execute_query(
                "SELECT dealer_id FROM dealer WHERE dealer_id = %s", (dealer_id,)):
            return {'success': False, 'msg': 'dealer not found'}, 404

        if exec_id in (None, '', 0):
            exec_id, exec_name = None, None
        else:
            urows = mysql_manager.execute_query(
                "SELECT id, name, role FROM users WHERE id = %s", (int(exec_id),))
            if not urows:
                return {'success': False, 'msg': 'user not found'}, 404
            if urows[0]['role'] != 'sales_executive':
                # A dealer's owner drives every per-executive figure on Target Tracker,
                # so it has to be someone who actually carries a book.
                return {'success': False,
                        'msg': f"{urows[0]['name']} is not a sales executive."}, 422
            exec_id, exec_name = urows[0]['id'], urows[0]['name']

        mysql_manager.execute_query(
            "UPDATE dealer SET sales_executive_id = %s WHERE dealer_id = %s",
            (exec_id, dealer_id), fetch=False)
        logger.info('dealer %s assigned to executive %s by admin %s',
                    dealer_id, exec_id, current_user.id)
        return {'success': True, 'dealer_id': dealer_id,
                'sales_executive_id': exec_id, 'sales_executive': exec_name}, 200


@rest_api.route('/api/admin/dealers/<int:dealer_id>/targets')
class AdminDealerTargets(Resource):
    """Set a dealer's rupee targets for one month, per category.

    A category sent as blank or 0 has its row DELETED rather than stored as zero: the
    analytics read "no target" and "a target of nothing" very differently — the first
    renders as '—', the second as a red 0% the dealer can never escape.
    """

    @token_required
    @active_required
    @_admin_required
    def put(self, current_user, dealer_id):
        body = request.get_json(silent=True) or {}
        period = (body.get('period') or '').strip() or _current_period().isoformat()
        targets = body.get('targets') or {}
        if not isinstance(targets, dict):
            return {'success': False, 'msg': 'targets must be an object keyed by category id'}, 422

        drows = mysql_manager.execute_query(
            "SELECT dealer_id, company_id FROM dealer WHERE dealer_id = %s", (dealer_id,))
        if not drows:
            return {'success': False, 'msg': 'dealer not found'}, 404
        company_id = drows[0]['company_id']

        valid = {c['category_id'] for c in (mysql_manager.execute_query(
            "SELECT category_id FROM categories WHERE is_active = 1") or [])}

        applied, cleared = 0, 0
        for raw_cid, raw_val in targets.items():
            try:
                cid = int(raw_cid)
            except (TypeError, ValueError):
                return {'success': False, 'msg': f'bad category id "{raw_cid}"'}, 422
            if cid not in valid:
                return {'success': False, 'msg': f'unknown category id {cid}'}, 422

            if raw_val in (None, ''):
                amount = 0.0
            else:
                try:
                    amount = float(str(raw_val).replace(',', ''))
                except (TypeError, ValueError):
                    return {'success': False,
                            'msg': f'target for category {cid} must be a number'}, 422
            if amount < 0:
                return {'success': False, 'msg': 'a target cannot be negative'}, 422

            if amount == 0:
                mysql_manager.execute_query(
                    "DELETE FROM dealer_money_target "
                    "WHERE dealer_id = %s AND category_id = %s AND target_period = %s",
                    (dealer_id, cid, period), fetch=False)
                cleared += 1
            else:
                # uq_dmt_grain (dealer_id, category_id, target_period) makes this an upsert.
                mysql_manager.execute_query(
                    """INSERT INTO dealer_money_target
                         (dealer_id, category_id, company_id, target_period, value_target)
                       VALUES (%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE value_target = VALUES(value_target)""",
                    (dealer_id, cid, company_id, period, amount), fetch=False)
                applied += 1

        logger.info('dealer %s targets for %s set by admin %s (%d set, %d cleared)',
                    dealer_id, period, current_user.id, applied, cleared)
        return {'success': True, 'dealer_id': dealer_id, 'period': period,
                'set': applied, 'cleared': cleared}, 200
