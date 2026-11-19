# -*- encoding: utf-8 -*-
"""Dealer Payment Tracker API (Cadila/dealer_payment_tracker_spec.md, on the cadila_changes
branch). Every call acts on the tracker's company (service.COMPANY), which the server works
out itself. Admin only on Ebco.

  GET  /api/dealer-payments/screen              the daily dealer screen (4); ?reviewed=1 also
                                                lists reviewed manual-check items; ?cheques=1
                                                reads wareops afresh (only when the tile opens)
  GET  /api/dealer-payments/dealers             the dealers, created from the Tally uploads
                                                (for the payment form)
  POST /api/dealer-payments/upload              form fields feed (outstanding | receipts), file
  GET  /api/dealer-payments/payments            the payment log; ?status=OPEN|POSTED|...
  POST /api/dealer-payments/payments            form fields dealer_id, mode, amount,
                                                payment_date, reference, note; file proof
  POST /api/dealer-payments/payments/<id>/cancel
  GET  /api/dealer-payments/payments/<id>/proof
  PUT  /api/dealer-payments/manual-checks/<id>  {reviewed, note}
  POST /api/dealer-payments/process             re-run processing (Refresh)
  GET  /api/dealer-payments/dealers/<id>        one dealer in detail: bills, payments, cheques
  GET  /api/dealer-payments/export/outstanding  the Tally-style Outstanding workbook (.xlsx)
  GET  /api/dealer-payments/exec-beats          this module's executive -> beats table
  PUT  /api/dealer-payments/exec-beats          {rows: [{se_name, beat_name}]} replaces it
  POST /api/dealer-payments/exec-beats/parse    form field file (User, Beat columns) -> rows,
                                                not stored
  GET  /api/dealer-payments/uploads             the last upload of each Tally file
  GET  /api/dealer-payments/beats               per sales executive (Beat Outstanding's
                                                Executive Beats): dealers and totals
  GET  /api/dealer-payments/export/beats        all executives' files (.zip); ?se=<name> one
                                                executive's (.xlsx), ?se=Unassigned the rest
"""

import io
from datetime import date, datetime
from decimal import Decimal
from functools import wraps

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.sales.dealer_payments import service as svc
from api.modules.sales.dealer_payments.cheques import ChequeAdapterError
from api.modules.sales.dealer_payments.parser import ParseError

logger = get_logger(__name__)

BASE = '/api/dealer-payments'

ALLOWED_ROLES = ('admin',)


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    return v


def _guard(f):
    """Admin and manager-type roles; maps the module's errors to JSON responses."""
    @wraps(f)
    def wrapper(self, current_user, *args, **kwargs):
        if not current_user or current_user.role not in ALLOWED_ROLES:
            return {'success': False, 'msg': 'You do not have access to the Dealer Payment Tracker.'}, 403
        try:
            out = f(self, current_user, *args, **kwargs)
            if isinstance(out, tuple) and isinstance(out[0], dict):
                return _jsonable(out[0]), out[1]
            return out
        except (svc.DealerPaymentsError, ParseError, ChequeAdapterError) as e:
            return {'success': False, 'msg': str(e)}, 400
        except Exception:
            logger.exception('dealer-payments %s %s failed', request.method, request.path)
            return {'success': False, 'msg': 'Something went wrong — nothing was changed. See logs.'}, 500
    return token_required(active_required(wrapper))


def _user(current_user):
    return getattr(current_user, 'username', None) or getattr(current_user, 'email', '') or ''


def _file():
    f = request.files.get('file')
    if not f or not f.filename:
        raise svc.DealerPaymentsError('No file uploaded.')
    return f.filename, f.stream.read()


@rest_api.route(f'{BASE}/screen')
class DptScreen(Resource):
    @_guard
    def get(self, current_user):
        cid = svc.company_id()
        return {'success': True, **svc.screen(cid, include_reviewed=request.args.get('reviewed') == '1',
                                              read_cheques=request.args.get('cheques') == '1')}, 200


@rest_api.route(f'{BASE}/dealers')
class DptDealers(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'dealers': svc.dealers(svc.company_id())}, 200


@rest_api.route(f'{BASE}/upload')
class DptUpload(Resource):
    @_guard
    def post(self, current_user):
        feed = request.form.get('feed')
        if feed not in svc.FEEDS:
            raise svc.DealerPaymentsError('Choose which Tally export this is: Outstanding or Receipt Register.')
        name, data = _file()
        cid = svc.company_id()
        load = svc.load_outstanding if feed == svc.KIND_OUTSTANDING else svc.load_receipts
        return {'success': True, 'result': load(cid, data, name, _user(current_user))}, 200


@rest_api.route(f'{BASE}/payments')
class DptPayments(Resource):
    @_guard
    def get(self, current_user):
        status = (request.args.get('status') or '').upper() or None
        return {'success': True, 'payments': svc.payments(svc.company_id(), status=status,
                                                          limit=request.args.get('limit') or 200)}, 200

    @_guard
    def post(self, current_user):
        p = svc.create_payment(svc.company_id(), request.form, _user(current_user),
                               proof=request.files.get('proof'))
        return {'success': True, 'payment': p}, 200


@rest_api.route(f'{BASE}/payments/<int:payment_id>/cancel')
class DptPaymentCancel(Resource):
    @_guard
    def post(self, current_user, payment_id):
        return {'success': True, 'payment': svc.cancel_payment(svc.company_id(), payment_id,
                                                               _user(current_user))}, 200


@rest_api.route(f'{BASE}/payments/<int:payment_id>/proof')
class DptPaymentProof(Resource):
    @_guard
    def get(self, current_user, payment_id):
        from api.shared import media
        path, mime = svc.proof(svc.company_id(), payment_id)
        return media.send_media(path, mime)


@rest_api.route(f'{BASE}/manual-checks/<int:check_id>')
class DptManualCheck(Resource):
    @_guard
    def put(self, current_user, check_id):
        body = request.get_json(silent=True) or {}
        return {'success': True, **svc.set_review(svc.company_id(), check_id,
                                                  bool(body.get('reviewed')), body.get('note'),
                                                  _user(current_user))}, 200


@rest_api.route(f'{BASE}/process')
class DptProcess(Resource):
    @_guard
    def post(self, current_user):
        return {'success': True, 'result': svc.run_processing(svc.company_id())}, 200


@rest_api.route(f'{BASE}/dealers/<string:dealer_id>')
class DptDealerDetail(Resource):
    @_guard
    def get(self, current_user, dealer_id):
        return {'success': True, **svc.dealer_detail(svc.company_id(), dealer_id)}, 200


@rest_api.route(f'{BASE}/export/outstanding')
class DptExportOutstanding(Resource):
    @_guard
    def get(self, current_user):
        name, data = svc.outstanding_export(svc.company_id())
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@rest_api.route(f'{BASE}/beats')
class DptBeats(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, **svc.beat_summary(svc.company_id())}, 200


@rest_api.route(f'{BASE}/export/beats')
class DptExportBeats(Resource):
    @_guard
    def get(self, current_user):
        se = (request.args.get('se') or '').strip()
        if se:
            name, data = svc.beat_export(svc.company_id(), se)
            mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            name, data = svc.beat_export_all(svc.company_id())
            mime = 'application/zip'
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)


@rest_api.route(f'{BASE}/exec-beats')
class DptExecBeats(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, **svc.exec_beats_page(svc.company_id())}, 200

    @_guard
    def put(self, current_user):
        rows = (request.get_json(silent=True) or {}).get('rows')
        if not isinstance(rows, list):
            raise svc.DealerPaymentsError('Send the rows to save.')
        return {'success': True, **svc.save_exec_beats(svc.company_id(), rows, _user(current_user))}, 200


@rest_api.route(f'{BASE}/exec-beats/parse')
class DptExecBeatsParse(Resource):
    @_guard
    def post(self, current_user):
        filename, data = _file()
        return {'success': True, **svc.parse_exec_beats_file(data, filename)}, 200


@rest_api.route(f'{BASE}/uploads')
class DptUploads(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'uploads': svc.last_uploads(svc.company_id())}, 200
