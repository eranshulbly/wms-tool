# -*- encoding: utf-8 -*-
"""
Invoice management routes:
  POST /api/invoices/upload
  POST /api/invoices/download-errors
  GET  /api/invoices/statistics
  GET  /api/invoices
  GET  /api/invoices/<invoice_id>

Supply sheet generation has moved to supply_sheet_routes.py
  POST /api/supply-sheet/generate
"""

import werkzeug
from flask import request, make_response, send_file
from flask_restx import Resource, fields, reqparse

from ..extensions import rest_api
from ..core.auth import token_required, active_required, upload_permission_required
from ..models import Invoice, PotentialOrder, Warehouse, Company, mysql_manager
from ..db_manager import partition_filter
from ..services import invoice_service
from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Models ───────────────────────────────────────────────────────────────────

invoice_upload_parser = reqparse.RequestParser()
invoice_upload_parser.add_argument('file',
                                   type=werkzeug.datastructures.FileStorage,
                                   location='files',
                                   required=True,
                                   help='Excel/CSV file with invoice data')
invoice_upload_parser.add_argument('warehouse_id',
                                   type=int, location='form', required=True,
                                   help='Warehouse ID must be provided')
invoice_upload_parser.add_argument('company_id',
                                   type=int, location='form', required=True,
                                   help='Company ID must be provided')

invoice_upload_response = rest_api.model('InvoiceUploadResponse', {
    'success':            fields.Boolean(description='Success status of upload'),
    'msg':                fields.String(description='Message describing the result'),
    'invoices_processed': fields.Integer(description='Number of invoices processed'),
    'orders_completed':   fields.Integer(description='Number of orders completed'),
    'errors':             fields.List(fields.String, description='List of errors encountered'),
    'upload_batch_id':    fields.String(description='Batch ID for tracking'),
    'has_errors':         fields.Boolean(description='Whether errors occurred'),
})

invoice_statistics_response = rest_api.model('InvoiceStatisticsResponse', {
    'success':        fields.Boolean(description='Success status'),
    'total_invoices': fields.Integer(description='Total number of invoices'),
    'unique_orders':  fields.Integer(description='Number of unique orders'),
    'total_amount':   fields.Float(description='Total invoice amount'),
    'recent_batches': fields.List(fields.Raw, description='Recent upload batches'),
})

invoice_model = rest_api.model('Invoice', {
    'invoice_id':            fields.Integer(description='Invoice ID'),
    'invoice_number':        fields.String(description='Invoice number'),
    'original_order_id':     fields.String(description='Original order ID'),
    'customer_name':         fields.String(description='Customer name'),
    'invoice_date':          fields.String(description='Invoice date'),
    'total_invoice_amount':  fields.String(description='Total amount'),
    'invoice_status':        fields.String(description='Invoice status'),
    'part_no':               fields.String(description='Part number'),
    'part_name':             fields.String(description='Part name'),
    'quantity':              fields.Integer(description='Quantity'),
    'unit_price':            fields.String(description='Unit price'),
})

invoice_list_response = rest_api.model('InvoiceListResponse', {
    'success':     fields.Boolean(description='Success status'),
    'invoices':    fields.List(fields.Nested(invoice_model), description='List of invoices'),
    'total_count': fields.Integer(description='Total number of invoices'),
    'page':        fields.Integer(description='Current page'),
    'per_page':    fields.Integer(description='Items per page'),
})

invoice_error_response = rest_api.model('InvoiceErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg':     fields.String(description='Error message'),
})

# ── Endpoints ────────────────────────────────────────────────────────────────

@rest_api.route('/api/invoices/upload')
class InvoiceUpload(Resource):
    """MySQL handles the upload of Excel/CSV files containing invoice data."""

    @rest_api.expect(invoice_upload_parser)
    @rest_api.response(200, 'Success', invoice_upload_response)
    @rest_api.response(400, 'Bad Request', invoice_upload_response)
    @token_required
    @active_required
    @upload_permission_required('invoices')
    def post(self, current_user):
        try:
            args = invoice_upload_parser.parse_args()
            uploaded_file = args['file']
            warehouse_id  = args['warehouse_id']
            company_id    = args['company_id']

            from ..permissions import has_all_warehouse_access
            if not has_all_warehouse_access(current_user.role):
                from ..models import UserWarehouseCompany
                if not UserWarehouseCompany.user_can_access(current_user.id, warehouse_id, company_id):
                    return {'success': False, 'msg': 'You do not have access to this warehouse/company combination.',
                            'processed_count': 0, 'error_count': 0}, 403

            warehouse = Warehouse.get_by_id(warehouse_id)
            if not warehouse:
                return {'success': False, 'msg': f'Warehouse with ID {warehouse_id} not found',
                        'processed_count': 0, 'error_count': 0}, 400

            company = Company.get_by_id(company_id)
            if not company:
                return {'success': False, 'msg': f'Company with ID {company_id} not found',
                        'processed_count': 0, 'error_count': 0}, 400

            return invoice_service.process_invoice_upload(uploaded_file, warehouse_id, company_id, current_user.id)

        except Exception as e:
            return {'success': False, 'msg': f'Error processing upload: {str(e)}',
                    'processed_count': 0, 'error_count': 0}, 400


@rest_api.route('/api/invoices/download-errors')
class InvoiceErrorDownload(Resource):
    """Download error CSV from invoice upload."""

    @token_required
    @active_required
    def post(self, _current_user):
        try:
            error_csv_content = request.json.get('error_csv_content', '')

            if not error_csv_content:
                return {'success': False, 'msg': 'No error data available'}, 400

            response = make_response(error_csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=invoice_upload_errors.csv'
            return response

        except Exception as e:
            return {'success': False, 'msg': f'Error creating error file: {str(e)}'}, 400


@rest_api.route('/api/invoices/statistics')
class InvoiceStatistics(Resource):
    """Get invoice upload statistics."""

    @rest_api.response(200, 'Success', invoice_statistics_response)
    @rest_api.response(400, 'Error', invoice_error_response)
    @token_required
    @active_required
    def get(self, _current_user):
        """Get invoice statistics."""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id   = request.args.get('company_id',   type=int)
            batch_id     = request.args.get('batch_id')

            stats = invoice_service.get_invoice_statistics(
                warehouse_id=warehouse_id,
                company_id=company_id,
                batch_id=batch_id
            )

            return {'success': True, **stats}, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving statistics: {str(e)}'}, 400


@rest_api.route('/api/invoices')
class InvoiceList(Resource):
    """Get list of invoices with pagination and filtering."""

    @rest_api.response(200, 'Success', invoice_list_response)
    @rest_api.response(400, 'Error', invoice_error_response)
    @token_required
    @active_required
    def get(self, _current_user):
        """Get list of invoices."""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id   = request.args.get('company_id',   type=int)
            batch_id     = request.args.get('batch_id')
            page         = request.args.get('page',     1,  type=int)
            per_page     = request.args.get('per_page', 50, type=int)

            per_page = min(per_page, 100)

            pf_sql, pf_params = partition_filter('invoice')
            base_query  = f"SELECT * FROM invoice WHERE {pf_sql}"
            count_query = f"SELECT COUNT(*) as count FROM invoice WHERE {pf_sql}"
            params = list(pf_params)

            if warehouse_id:
                base_query  += " AND warehouse_id = %s"
                count_query += " AND warehouse_id = %s"
                params.append(warehouse_id)
            if company_id:
                base_query  += " AND company_id = %s"
                count_query += " AND company_id = %s"
                params.append(company_id)
            if batch_id:
                base_query  += " AND upload_batch_id = %s"
                count_query += " AND upload_batch_id = %s"
                params.append(batch_id)

            total_result = mysql_manager.execute_query(count_query, params)
            total_count  = total_result[0]['count'] if total_result else 0

            base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([per_page, (page - 1) * per_page])

            invoices_data = mysql_manager.execute_query(base_query, params)

            invoice_list = []
            for invoice_data in invoices_data:
                invoice = Invoice(**invoice_data)
                invoice_dict = {
                    'invoice_id':           invoice.invoice_id,
                    'invoice_number':       invoice.invoice_number,
                    'original_order_id':    invoice.original_order_id,
                    'customer_name':        invoice.customer_name,
                    'invoice_date':         invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                    'total_invoice_amount': str(invoice.total_invoice_amount) if invoice.total_invoice_amount else None,
                    'invoice_status':       invoice.invoice_status,
                    'part_no':              invoice.part_no,
                    'part_name':            invoice.part_name,
                    'quantity':             invoice.quantity,
                    'unit_price':           str(invoice.unit_price) if invoice.unit_price else None,
                }
                invoice_list.append(invoice_dict)

            return {
                'success':     True,
                'invoices':    invoice_list,
                'total_count': total_count,
                'page':        page,
                'per_page':    per_page,
            }, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving invoices: {str(e)}'}, 400


@rest_api.route('/api/invoices/<int:invoice_id>')
class InvoiceDetail(Resource):
    """Get detailed information about a specific invoice."""

    @rest_api.response(200, 'Success')
    @rest_api.response(404, 'Invoice not found', invoice_error_response)
    def get(self, invoice_id):
        """Get invoice details."""
        try:
            invoice = Invoice.get_by_id(invoice_id)

            if not invoice:
                return {'success': False, 'msg': 'Invoice not found'}, 404

            order_info = None
            if invoice.potential_order_id:
                order = PotentialOrder.get_by_id(invoice.potential_order_id)
                if order:
                    order_info = {
                        'order_request_id': f"PO{order.potential_order_id}",
                        'status':           order.status,
                        'order_date':       order.order_date.isoformat() if order.order_date else None,
                    }

            invoice_dict = {
                'invoice_id':           invoice.invoice_id,
                'invoice_number':       invoice.invoice_number,
                'original_order_id':    invoice.original_order_id,
                'customer_name':        invoice.customer_name,
                'invoice_date':         invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                'total_invoice_amount': str(invoice.total_invoice_amount) if invoice.total_invoice_amount else None,
                'invoice_status':       invoice.invoice_status,
                'part_no':              invoice.part_no,
                'part_name':            invoice.part_name,
                'quantity':             invoice.quantity,
                'unit_price':           str(invoice.unit_price) if invoice.unit_price else None,
                'order_info':           order_info,
            }

            return {'success': True, 'invoice': invoice_dict}, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving invoice details: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# OLD /api/invoices/supply-sheet/download has been removed.
# Use POST /api/supply-sheet/generate (supply_sheet_routes.py) instead.
# ---------------------------------------------------------------------------
