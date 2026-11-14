# -*- encoding: utf-8 -*-
"""Beat Outstanding API. Ebco only: every call acts on the Ebco company, which the server
works out itself (there is no company parameter). Admin only — it is dealers' dues.

  GET  /api/beat-outstanding/status                    when each file was last uploaded
The Tally outstanding report is never stored: it is sent, as form field `outstanding`,
with every call that shows or downloads amounts, and read for that call only.

  GET  /api/beat-outstanding/report                    executives on today's beat plan,
                                                       without amounts
  POST /api/beat-outstanding/report                    the same, with the outstanding of the
                                                       report sent
  POST /api/beat-outstanding/export                    one executive's (.xlsx); form fields
                                                       user_id, se_name, outstanding
  POST /api/beat-outstanding/export-all                every executive's, one .xlsx each, and
                                                       the Other row's (.zip)
  POST /api/beat-outstanding/export-unassigned         the Other row's: dealers no executive
                                                       covers (.xlsx)
  POST /api/beat-outstanding/upload                    form fields feed, file (Outlet Master,
                                                       Beat Plan)
  GET  /api/beat-outstanding/exec-beats                the executive → beats table
  POST /api/beat-outstanding/exec-beats/parse          form field file (User, Beat columns)
                                                       -> its rows, NOT saved: the page
                                                       shows them in the table to save
  PUT  /api/beat-outstanding/day-beats                 {se_name, beats: [beat name]} — that
                                                       executive's beats for today, by hand
  PUT  /api/beat-outstanding/exec-beats                {rows: [{se_name, beat_name}]} —
                                                       replaces the executive → beats table
"""

import io
from datetime import datetime
from functools import wraps

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.sales.beat_outstanding import service as svc
from api.modules.sales.beat_outstanding.parser import ParseError, PARSERS, parse_exec_beats

logger = get_logger(__name__)

BASE = '/api/beat-outstanding'

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _guard(f):
    """Admin only; maps the module's errors to JSON responses."""
    @wraps(f)
    def wrapper(self, current_user, *args, **kwargs):
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        try:
            return f(self, current_user, *args, **kwargs)
        except (svc.BeatOutstandingError, ParseError) as e:
            return {'success': False, 'msg': str(e)}, 400
        except Exception:
            logger.exception('beat-outstanding %s %s failed', request.method, request.path)
            return {'success': False, 'msg': 'Something went wrong — nothing was changed. See logs.'}, 500
    return token_required(active_required(wrapper))


def _date_arg():
    s = (request.args.get('date') or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        raise svc.BeatOutstandingError('date must be YYYY-MM-DD.')


def _outstanding():
    """The Tally report sent with this request, parsed — or None. Never stored."""
    f = request.files.get('outstanding')
    return svc.read_outstanding(f.stream, f.filename) if f else None


def _file(filename, data, mimetype):
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True,
                     download_name=filename)


@rest_api.route(f'{BASE}/status')
class BeatOutstandingStatus(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'feeds': svc.feed_status(svc.ebco_company_id())}, 200


@rest_api.route(f'{BASE}/report')
class BeatOutstandingReport(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, **svc.report(svc.ebco_company_id(), _date_arg())}, 200

    @_guard
    def post(self, current_user):
        return {'success': True, **svc.report(svc.ebco_company_id(), _date_arg(),
                                              outstanding=_outstanding())}, 200


@rest_api.route(f'{BASE}/export')
class BeatOutstandingExport(Resource):
    @_guard
    def post(self, current_user):
        name, data = svc.export_one(svc.ebco_company_id(), _date_arg(),
                                    request.form.get('user_id', ''), request.form.get('se_name', ''),
                                    _outstanding())
        return _file(name, data, XLSX)


@rest_api.route(f'{BASE}/export-all')
class BeatOutstandingExportAll(Resource):
    @_guard
    def post(self, current_user):
        name, data = svc.export_all(svc.ebco_company_id(), _date_arg(), _outstanding())
        return _file(name, data, 'application/zip')


@rest_api.route(f'{BASE}/export-unassigned')
class BeatOutstandingExportUnassigned(Resource):
    @_guard
    def post(self, current_user):
        name, data = svc.export_unassigned(svc.ebco_company_id(), _outstanding())
        return _file(name, data, XLSX)


@rest_api.route(f'{BASE}/upload')
class BeatOutstandingUpload(Resource):
    @_guard
    def post(self, current_user):
        feed = request.form.get('feed')
        if feed not in PARSERS:
            return {'success': False, 'msg': 'Choose which file this is.'}, 400
        f = request.files.get('file')
        if not f:
            return {'success': False, 'msg': 'No file uploaded'}, 400
        out = svc.ingest(feed, f.stream, f.filename, svc.ebco_company_id(), current_user.username)
        return {'success': True, 'result': out}, 200


@rest_api.route(f'{BASE}/exec-beats')
class BeatOutstandingExecBeats(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, **svc.exec_beats_page(svc.ebco_company_id())}, 200

    @_guard
    def put(self, current_user):
        rows = (request.get_json(silent=True) or {}).get('rows')
        if not isinstance(rows, list):
            return {'success': False, 'msg': 'Send rows: [{se_name, beat_name}].'}, 400
        out = svc.save_exec_beats(svc.ebco_company_id(), rows, current_user.username)
        return {'success': True, **out}, 200


@rest_api.route(f'{BASE}/exec-beats/parse')
class BeatOutstandingExecBeatsParse(Resource):
    @_guard
    def post(self, current_user):
        f = request.files.get('file')
        if not f:
            return {'success': False, 'msg': 'No file uploaded'}, 400
        rows, warnings = parse_exec_beats(f.stream.read(), f.filename)
        return {'success': True, 'rows': rows, 'warnings': warnings[:50],
                'warning_count': len(warnings)}, 200


@rest_api.route(f'{BASE}/day-beats')
class BeatOutstandingDayBeats(Resource):
    @_guard
    def put(self, current_user):
        body = request.get_json(silent=True) or {}
        if not body.get('se_name') or not isinstance(body.get('beats'), list):
            return {'success': False, 'msg': 'Send se_name and beats: [beat name].'}, 400
        out = svc.set_day_beats(svc.ebco_company_id(), body['se_name'], body['beats'])
        return {'success': True, **out}, 200
