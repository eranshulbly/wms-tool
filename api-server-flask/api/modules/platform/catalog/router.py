# -*- encoding: utf-8 -*-
"""
Product routes: ProductUpload.
"""

import werkzeug
from flask_restx import Resource, fields, reqparse

from api.extensions import rest_api
from api.core.auth import token_required, active_required, upload_permission_required
from api.models import Company
from api.services import product_service
from api.core.logging import get_logger

logger = get_logger(__name__)

# ── Models ───────────────────────────────────────────────────────────────────

product_upload_parser = reqparse.RequestParser()
product_upload_parser.add_argument('file',
                                   type=werkzeug.datastructures.FileStorage,
                                   location='files',
                                   required=True,
                                   help='Excel/CSV/PDF file with product data')
product_upload_parser.add_argument('company_id',
                                   type=int,
                                   location='form',
                                   required=True,
                                   help='Company ID must be provided')
# The operator's answer to the part-number prompt. Absent on a first attempt, so a file
# without Part # is refused and explained rather than silently given generated codes.
product_upload_parser.add_argument('auto_generate_part_numbers',
                                   type=str,
                                   location='form',
                                   required=False,
                                   help='Set to true to accept auto-generated product numbers')

product_upload_response = rest_api.model('ProductUploadResponse', {
    'success':        fields.Boolean(description='Success status of upload'),
    'msg':            fields.String(description='Message describing the result'),
    'processed_count': fields.Integer(description='Number of product lines processed'),
    'error_count':    fields.Integer(description='Number of rows with errors'),
    'orders_updated': fields.Integer(description='Number of orders whose products were updated'),
    'error_report':   fields.String(description='Base64-encoded Excel error report'),
    'upload_batch_id': fields.String(description='Batch ID for tracking'),
})

# ── Endpoint ─────────────────────────────────────────────────────────────────

@rest_api.route('/api/products/upload')
class ProductUpload(Resource):
    """Upload a product CSV/Excel file to attach product lines to existing orders."""

    @rest_api.expect(product_upload_parser)
    @rest_api.response(200, 'Success', product_upload_response)
    @rest_api.response(400, 'Bad Request', product_upload_response)
    @token_required
    @active_required
    @upload_permission_required('products')
    def post(self, current_user):
        try:
            args = product_upload_parser.parse_args()
            uploaded_file = args['file']
            company_id    = args['company_id']

            company = Company.get_by_id(company_id)
            if not company:
                return {'success': False, 'msg': f'Company with ID {company_id} not found',
                        'processed_count': 0, 'error_count': 0}, 400

            approved = str(args.get('auto_generate_part_numbers') or '').lower() in (
                '1', 'true', 'yes')
            return product_service.process_product_upload(
                uploaded_file, company_id, current_user.id,
                auto_generate_part_numbers=approved)

        except Exception as e:
            return {'success': False, 'msg': f'Error processing upload: {str(e)}',
                    'processed_count': 0, 'error_count': 0}, 400


# ── Product master ───────────────────────────────────────────────────────────
#
# Distinct from /api/products/upload above, which attaches product LINES to existing
# orders. This one loads the catalogue itself: identity and packaging, merge-upserted.

product_master_parser = reqparse.RequestParser()
product_master_parser.add_argument('file', type=werkzeug.datastructures.FileStorage,
                                   location='files', required=True,
                                   help='CSV or Excel product master')
product_master_parser.add_argument('company_id', type=int, location='form',
                                   required=False,
                                   help='Company the catalogue belongs to')


@rest_api.route('/api/admin/catalog/product-master')
class ProductMasterUpload(Resource):
    """Merge-upsert the product catalogue and its packaging ladder."""

    @rest_api.expect(product_master_parser)
    @token_required
    @active_required
    @upload_permission_required('products')
    def post(self, current_user):
        from api.permissions import resolve_company_scope, CompanyAccessDenied
        from api.modules.platform.catalog import master_upload

        args = product_master_parser.parse_args()

        # The company is chosen by the operator and never read from the sheet, so a
        # scoped admin cannot load another tenant's catalogue by posting someone
        # else's id. With nothing selected we fall back to the caller's own scope,
        # but only when that is unambiguous.
        try:
            scope = resolve_company_scope(current_user, args.get('company_id'))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403
        if scope is None:
            return {'success': False, 'msg': 'Select a company for this upload.'}, 422
        if not scope:
            return {'success': False, 'msg': 'You are not assigned to any company.'}, 422
        if len(scope) > 1:
            return {'success': False,
                    'msg': 'Select a company for this upload — you have access to several.'}, 422

        try:
            return master_upload.process(args['file'], scope[0])
        except Exception as e:
            logger.exception("Product master upload failed",
                             extra={'company_id': scope[0]})
            return {'success': False, 'msg': f'Upload failed: {e}'}, 400
