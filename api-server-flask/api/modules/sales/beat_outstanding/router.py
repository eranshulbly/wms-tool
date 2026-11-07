# -*- encoding: utf-8 -*-
"""Beat Outstanding API. Ebco only: every call acts on the Ebco company, which the server
works out itself (there is no company parameter). Admin only — it is dealers' dues.

  GET  /api/beat-outstanding/status                    when each file was last uploaded
  GET  /api/beat-outstanding/report?date=              executives on that day's beat plan,
                                                       their dealers' outstanding, and the
                                                       parties not placed on any beat
  GET  /api/beat-outstanding/export?date=&user_id=&se_name=
                                                       one executive's outstanding (.xlsx)
  GET  /api/beat-outstanding/export-all?date=          every executive's, one .xlsx each (.zip)
  POST /api/beat-outstanding/upload                    form fields feed, file
  GET  /api/beat-outstanding/exec-beats                the executive → beats table
  POST /api/beat-outstanding/exec-beats/parse          form field file (User, Beat columns)
                                                       -> its rows, NOT saved: the page
                                                       shows them in the table to save
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


@rest_api.route(f'{BASE}/export')
class BeatOutstandingExport(Resource):
    @_guard
    def get(self, current_user):
        name, data = svc.export_one(svc.ebco_company_id(), _date_arg(),
                                    request.args.get('user_id', ''), request.args.get('se_name', ''))
        return _file(name, data, XLSX)


@rest_api.route(f'{BASE}/export-all')
class BeatOutstandingExportAll(Resource):
    @_guard
    def get(self, current_user):
        name, data = svc.export_all(svc.ebco_company_id(), _date_arg())
        return _file(name, data, 'application/zip')


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
