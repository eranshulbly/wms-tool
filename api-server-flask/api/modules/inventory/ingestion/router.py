# -*- encoding: utf-8 -*-
"""Admin API — Cadila inventory ingestion (/api/admin/inventory/ingestion/*).

  POST /upload                     upload one or more supplier PDFs
  GET  /received                   inbound lines with product, batch and price
  GET  /report                     batch costing: cost, MRP and margin per SKU + batch

Upload carries a document all the way through: products are created when the catalogue
does not have them, the batch is reused or created, and stock and price details are
written in the same transaction. There is no separate posting step because there is no
step that waits on a human.
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.inventory.ingestion import service as svc
from api.modules.inventory.ingestion.parser import ParseError

logger = get_logger(__name__)

BASE = '/api/admin/inventory/ingestion'


def _company(current_user, requested=None):
    """The tenant these documents belong to — chosen by the operator, never read from
    the file. Mirrors the monthly-upload rule: a scoped admin cannot post another
    tenant's data by sending someone else's id."""
    from api.permissions import resolve_company_scope
    scope = resolve_company_scope(current_user, requested)
    if scope is None:
        return None, 'Select a company for this upload.'
    if not scope:
        return None, 'You are not assigned to any company.'
    if len(scope) > 1:
        return None, 'Select a company for this upload — you have access to several.'
    return scope[0], None


def _scope(current_user):
    from api.permissions import resolve_company_scope
    return resolve_company_scope(current_user)


@rest_api.route(f'{BASE}/upload')
class IngestionUpload(Resource):
    @token_required
    @active_required
    def post(self, current_user):
        files = request.files.getlist('files') or (
            [request.files['file']] if 'file' in request.files else [])
        if not files:
            return {'success': False, 'msg': 'No file uploaded'}, 400

        company_id, err = _company(current_user, request.form.get('company_id'))
        if err:
            return {'success': False, 'msg': err}, 400
        warehouse_id = request.form.get('warehouse_id')
        if not warehouse_id:
            return {'success': False, 'msg': 'Select a warehouse'}, 400

        # An explicit override exists because a note that DOES return goods looks
        # identical on paper to one that only adjusts price. The operator states it; the
        # parser never guesses it from the quantity.
        effect = request.form.get('movement_effect') or None

        results, failed = [], []
        for f in files:
            try:
                out = svc.ingest_pdf(f.stream, f.filename, company_id, int(warehouse_id),
                                     user=current_user.username, movement_effect=effect)
                results.append({
                    'filename': f.filename,
                    'doc_type': out['parsed']['doc_type'],
                    'doc_number': out['doc_number'],
                    'lines': len(out['parsed']['lines']),
                    'duplicate': out['duplicate'],
                    'total_variance': out['parsed']['total_variance'],
                    'warnings': out['parsed']['warnings'],
                    'created_products': out['created_products'],
                    'received': out['received'],
                    'adjusted': out['adjusted'],
                    'moved_stock': out.get('moved_stock', False),
                })
            except (ParseError, svc.IngestionError) as e:
                failed.append({'filename': f.filename, 'error': str(e)})
            except Exception:
                logger.exception('ingestion failed for %s', f.filename)
                failed.append({'filename': f.filename, 'error': 'Unexpected error — see logs'})

        return {'success': True, 'ingested': results, 'failed': failed}, 200


@rest_api.route(f'{BASE}/received')
class IngestionReceived(Resource):
    """What has been taken in — transferin_info rows with product, batch and price."""

    @token_required
    @active_required
    def get(self, current_user):
        # ?company_id= may only NARROW the caller's scope, never widen it — asking for a
        # company outside it raises rather than silently returning someone else's stock.
        # Without it an unrestricted admin has scope None, which means "every company",
        # so the screen must send the selected one or it shows all tenants at once.
        from api.permissions import resolve_company_scope, CompanyAccessDenied
        try:
            scope = resolve_company_scope(current_user, request.args.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        rows = svc.list_received(
            company_ids=scope,
            warehouse_id=request.args.get('warehouse_id'),
            limit=int(request.args.get('limit', 200)),
            offset=int(request.args.get('offset', 0)))
        return {'success': True, 'received': rows}, 200


@rest_api.route(f'{BASE}/report')
class IngestionReport(Resource):
    """Batch costing report — one row per SKU and batch, for any company in scope."""

    @token_required
    @active_required
    def get(self, current_user):
        from api.permissions import resolve_company_scope, CompanyAccessDenied
        try:
            scope = resolve_company_scope(current_user, request.args.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        rows = svc.batch_costing_report(
            company_ids=scope,
            search=request.args.get('search'),
            limit=int(request.args.get('limit', 2000)),
            offset=int(request.args.get('offset', 0)))
        return {'success': True, 'rows': rows}, 200
