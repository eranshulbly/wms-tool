# -*- encoding: utf-8 -*-
"""Pick list routes:
  POST /api/picklists/upload     — import one pick-list PDF
  GET  /api/picklists            — list pick lists, open by default
  POST /api/picklists/download   — rebuild selected pick lists as one PDF
  POST /api/picklists/printed    — set or clear the printed mark by hand
  POST /api/picklists/scan       — move an order from a scanned QR payload
"""

from io import BytesIO

import werkzeug
from flask import request, send_file
from flask_restx import Resource, fields, reqparse

from api.core.auth import token_required, active_required, upload_permission_required
from api.core.logging import get_logger
from api.extensions import rest_api
from api.models import Company, Warehouse
from api.modules.fulfillment.picklist import pdf as picklist_pdf
from api.modules.fulfillment.picklist import repository as picklist_repo
from api.modules.fulfillment.picklist import service as picklist_service
from api.permissions import (
    CompanyAccessDenied, has_all_warehouse_access, resolve_company_scope,
)

logger = get_logger(__name__)

# A batch download is capped because gunicorn runs a single process here: ReportLab
# draws a page in tens of milliseconds, so a hundred is a second or two, but an
# uncapped selection would hold the only worker for as long as it took.
MAX_DOWNLOAD = 100

upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file',
                           type=werkzeug.datastructures.FileStorage,
                           location='files', required=True,
                           help='Pick-list PDF')
upload_parser.add_argument('warehouse_id', type=int, location='form', required=True)
upload_parser.add_argument('company_id', type=int, location='form', required=True)

scan_model = rest_api.model('PicklistScan', {
    'payload': fields.String(required=True, description='Raw scanned QR string'),
    'target_status': fields.String(description='Station target, e.g. "packed". '
                                               'Omit to advance to the next state.'),
    'box_count': fields.Integer(description='Number of boxes, when moving to Packed'),
    'device_id': fields.String(description='Scanner identifier, for the audit trail'),
})

download_model = rest_api.model('PicklistDownload', {
    'picklist_ids': fields.List(fields.Integer, required=True),
    'mark_printed': fields.Boolean(
        description='True when the caller is printing these, not just saving a copy'),
})

printed_model = rest_api.model('PicklistPrinted', {
    'picklist_ids': fields.List(fields.Integer, required=True),
    'printed': fields.Boolean(required=True, description='True to mark, false to clear'),
})


def _company_scope(current_user, company_id=None):
    """Resolve the caller's tenant scope. A supplied company_id may only narrow it."""
    return resolve_company_scope(current_user, company_id)


def _owner_scope(current_user, want_all=False):
    """Whose pick lists this caller may see. None means everyone's.

    Pick lists are the one thing here that is per-user: each person works the
    pile they uploaded, so two office staff importing for the same warehouse do
    not print each other's sheets. Orders, invoices and everything else stay
    shared — a warehouse has one order book.

    Admins are exempt, and that is not a courtesy. Without it, the sheets of
    whoever is off sick become invisible to everybody, and a pile of unprinted
    pick lists sits in the system with no one able to reach it. `want_all` lets
    an admin ask for the whole set explicitly.

    The scope comes from the TOKEN, never from a request parameter — a caller
    cannot widen it by asking.
    """
    if getattr(current_user, 'role', None) == 'admin':
        return None if want_all else current_user.id
    return current_user.id


@rest_api.route('/api/picklists/upload')
class PicklistUpload(Resource):
    """Import one pick-list PDF and attach it to the order it names."""

    @rest_api.expect(upload_parser)
    @token_required
    @active_required
    @upload_permission_required('picklists')
    def post(self, current_user):
        try:
            args = upload_parser.parse_args()
            warehouse_id = args['warehouse_id']
            company_id = args['company_id']

            if not has_all_warehouse_access(current_user.role):
                from api.models import UserWarehouseCompany
                if not UserWarehouseCompany.user_can_access(
                        current_user.id, warehouse_id, company_id):
                    return {'success': False,
                            'msg': 'You do not have access to this warehouse/company '
                                   'combination.'}, 403

            if not Warehouse.get_by_id(warehouse_id):
                return {'success': False,
                        'msg': 'Warehouse with ID %s not found' % warehouse_id}, 400
            if not Company.get_by_id(company_id):
                return {'success': False,
                        'msg': 'Company with ID %s not found' % company_id}, 400

            return picklist_service.upload_one(
                args['file'], warehouse_id, company_id, current_user.id)

        except Exception as e:
            logger.exception("Pick-list upload endpoint error")
            return {'success': False, 'msg': 'Error processing upload: %s' % e}, 400


@rest_api.route('/api/picklists')
class PicklistList(Resource):
    """Pick lists with their order's live status. `state` defaults to open."""

    @token_required
    @active_required
    def get(self, current_user):
        state = (request.args.get('state') or 'open').lower()
        if state not in ('open', 'closed', 'all'):
            return {'success': False,
                    'msg': "state must be one of: open, closed, all"}, 400

        # Tri-state: printed / unprinted / (absent) everything.
        printed_arg = (request.args.get('printed') or 'all').lower()
        if printed_arg not in ('printed', 'unprinted', 'all'):
            return {'success': False,
                    'msg': "printed must be one of: printed, unprinted, all"}, 400
        printed = {'printed': True, 'unprinted': False, 'all': None}[printed_arg]

        # Admins may ask for everyone's; for anyone else this is ignored and the
        # scope stays their own.
        want_all = (request.args.get('owner') or 'mine').lower() == 'all'
        owner_id = _owner_scope(current_user, want_all)

        warehouse_id = request.args.get('warehouse_id', type=int)
        company_id = request.args.get('company_id', type=int)

        try:
            company_ids = _company_scope(current_user, company_id)
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        try:
            rows = picklist_repo.list_picklists(
                company_ids, warehouse_id=warehouse_id, state=state,
                printed=printed, owner_id=owner_id)
        except Exception as e:
            logger.exception("Pick-list listing failed")
            return {'success': False, 'msg': 'Could not load pick lists: %s' % e}, 400

        return {
            'success': True,
            'state': state,
            'picklists': [
                {
                    'picklist_id': r['picklist_id'],
                    'original_order_id': r['original_order_id'],
                    'picklist_code': r['picklist_code'],
                    'picklist_date': r['picklist_date'].isoformat()
                                     if r['picklist_date'] else None,
                    'dealer_name': r['dealer_name'] or '',
                    'line_count': r['line_count'],
                    'order_status': r['order_status'],
                    'state': 'open' if r['order_status'] in picklist_repo.OPEN_STATUSES
                             else 'closed',
                    'created_at': r['created_at'].isoformat() if r['created_at'] else None,
                    'printed_at': r['printed_at'].isoformat() if r['printed_at'] else None,
                    'print_count': r['print_count'] or 0,
                    'printed_by_name': r['printed_by_name'] or '',
                    'uploaded_by_name': r['uploaded_by_name'] or '',
                    'created_by': r['created_by'],
                }
                for r in rows
            ],
        }, 200


@rest_api.route('/api/picklists/download')
class PicklistDownload(Resource):
    """Rebuild the selected pick lists into one PDF, each with its QR code.

    One document rather than a zip of many: the point of selecting a batch is to
    send it to the printer once and hand the stack to pickers.
    """

    @rest_api.expect(download_model)
    @token_required
    @active_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        ids = body.get('picklist_ids') or []

        if not isinstance(ids, list) or not ids:
            return {'success': False, 'msg': 'Select at least one pick list.'}, 400
        if len(ids) > MAX_DOWNLOAD:
            return {'success': False,
                    'msg': 'Select at most %d pick lists per download.' % MAX_DOWNLOAD}, 400

        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return {'success': False, 'msg': 'picklist_ids must be integers.'}, 400

        try:
            company_ids = _company_scope(current_user, body.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        # want_all here, unlike the listing: an admin's DEFAULT VIEW is their own
        # pile for tidiness, but their AUTHORITY is full. Passing the narrow scope
        # would let an admin see every sheet and then fail to print any of them.
        rows = picklist_repo.fetch_for_render(
            ids, company_ids, owner_id=_owner_scope(current_user, want_all=True))
        if not rows:
            return {'success': False,
                    'msg': 'None of the selected pick lists are available to you.'}, 404

        # A sheet whose order has left Open is finished as paper: a picker is
        # already walking the aisles with the copy that was issued, and a second
        # copy printed behind them is two people picking one order.
        #
        # Enforced here, not only by greying out the buttons: the front end
        # can be bypassed by posting the ids directly, and this is the rule that
        # keeps duplicate paper off the floor.
        #
        # The whole batch is refused rather than the closed sheets quietly
        # dropped. A stack that came back one sheet short, with nothing said,
        # is how an order goes unpicked.
        closed = [r for r in rows
                  if r['order_status'] not in picklist_repo.OPEN_STATUSES]
        if closed:
            listed = ', '.join('%s (%s)' % (r['original_order_id'], r['order_status'])
                               for r in closed[:5])
            more = '' if len(closed) <= 5 else ' and %d more' % (len(closed) - 5)
            return {'success': False,
                    'msg': 'These pick lists are closed and cannot be printed or '
                           'downloaded again: %s%s. A sheet closes once its order '
                           'moves past Open.' % (listed, more)}, 409

        # Preserve the caller's selection order; fetch_for_render orders by creation.
        by_id = {r['picklist_id']: r for r in rows}
        ordered = [by_id[i] for i in ids if i in by_id]

        try:
            pdf_bytes = picklist_pdf.build_pdf(ordered)
        except picklist_pdf.PicklistRenderError as e:
            return {'success': False, 'msg': str(e)}, 400
        except Exception as e:
            logger.exception("Pick-list PDF render failed", extra={'count': len(ordered)})
            return {'success': False, 'msg': 'Could not build the PDF: %s' % e}, 400

        # Stamped only when the caller pressed PRINT, not when they saved a copy.
        #
        # The decision is made here rather than reported back by the browser after
        # window.print(): a print dialog can be cancelled, a tab closed or a
        # network dropped, and none of that returns. What the server can honestly
        # record is that the sheet was issued for printing — "Mark as not printed"
        # covers the rest. Marked only after the PDF actually rendered, so a
        # failed render never marks anything.
        if body.get('mark_printed'):
            try:
                picklist_repo.mark_printed([r['picklist_id'] for r in ordered],
                                           current_user.id)
            except Exception:
                # The paper matters more than the bookkeeping: never fail a print
                # because the flag could not be written.
                logger.exception("Could not mark pick lists printed",
                                 extra={'count': len(ordered)})

        if len(ordered) == 1:
            filename = 'picklist_%s.pdf' % (ordered[0]['original_order_id'] or 'order')
        else:
            filename = 'picklists_%d.pdf' % len(ordered)

        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,        # inline, so the browser can preview and print
            download_name=filename,
        )


@rest_api.route('/api/picklists/printed')
class PicklistPrinted(Resource):
    """Set or clear the printed mark by hand.

    The escape hatch for the one thing the server cannot see: a Print that opened
    the dialog and was cancelled, a paper jam, a printer that was offline. Without
    it an operator is stuck looking at sheets the system insists came out.
    """

    @rest_api.expect(printed_model)
    @token_required
    @active_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        ids = body.get('picklist_ids') or []
        printed = bool(body.get('printed'))

        if not isinstance(ids, list) or not ids:
            return {'success': False, 'msg': 'Select at least one pick list.'}, 400
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return {'success': False, 'msg': 'picklist_ids must be integers.'}, 400

        try:
            company_ids = _company_scope(current_user, body.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        # Scoped through the same query the download uses, so a caller cannot
        # flip a mark on another tenant's pick list by guessing an id.
        allowed = [r['picklist_id'] for r in picklist_repo.fetch_for_render(
            ids, company_ids, owner_id=_owner_scope(current_user, want_all=True))]
        if not allowed:
            return {'success': False,
                    'msg': 'None of the selected pick lists are available to you.'}, 404

        if printed:
            n = picklist_repo.mark_printed(allowed, current_user.id)
        else:
            n = picklist_repo.unmark_printed(allowed)

        return {'success': True, 'updated': n, 'printed': printed}, 200


@rest_api.route('/api/picklists/scan')
class PicklistScan(Resource):
    """Move an order from a scanned pick-list QR code."""

    @rest_api.expect(scan_model)
    @token_required
    @active_required
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        payload = (body.get('payload') or '').strip()

        if not payload:
            return {'success': False, 'result': 'bad_payload',
                    'msg': 'No QR payload was sent.'}, 400

        return picklist_service.apply_scan(
            payload,
            current_user,
            target_status=body.get('target_status'),
            box_count=body.get('box_count'),
            device_id=body.get('device_id'),
        )
