# -*- encoding: utf-8 -*-
"""
Product routes: ProductUpload.
"""

import werkzeug
from flask_restx import Resource, fields, reqparse

from ..extensions import rest_api
from ..core.auth import token_required, active_required, upload_permission_required
from ..models import Company
from ..services import product_service
from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Models ───────────────────────────────────────────────────────────────────

product_upload_parser = reqparse.RequestParser()
product_upload_parser.add_argument('file',
                                   type=werkzeug.datastructures.FileStorage,
                                   location='files',
                                   required=True,
                                   help='Excel/CSV file with product data')
product_upload_parser.add_argument('company_id',
                                   type=int,
                                   location='form',
                                   required=True,
                                   help='Company ID must be provided')

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

            return product_service.process_product_upload(uploaded_file, company_id, current_user.id)

        except Exception as e:
            return {'success': False, 'msg': f'Error processing upload: {str(e)}',
                    'processed_count': 0, 'error_count': 0}, 400
