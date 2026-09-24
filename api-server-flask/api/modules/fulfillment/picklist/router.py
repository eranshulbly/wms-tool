# -*- encoding: utf-8 -*-
"""Pick list routes:
  POST /api/picklists/upload     — import one pick-list PDF
  GET  /api/picklists            — list pick lists, open by default
  POST /api/picklists/download   — rebuild selected pick lists as one PDF
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
})


def _company_scope(current_user, company_id=None):
    """Resolve the caller's tenant scope. A supplied company_id may only narrow it."""
    return resolve_company_scope(current_user, company_id)


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

        warehouse_id = request.args.get('warehouse_id', type=int)
        company_id = request.args.get('company_id', type=int)

        try:
            company_ids = _company_scope(current_user, company_id)
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        try:
            rows = picklist_repo.list_picklists(
                company_ids, warehouse_id=warehouse_id, state=state)
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

        rows = picklist_repo.fetch_for_render(ids, company_ids)
        if not rows:
            return {'success': False,
                    'msg': 'None of the selected pick lists are available to you.'}, 404

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
