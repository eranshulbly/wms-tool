# -*- encoding: utf-8 -*-
"""
Order management routes:
  POST /api/orders/upload
  POST /api/orders/bulk-status-update
  GET  /api/orders/<order_id>/details
  POST /api/orders/<order_id>/status
  POST /api/orders/<order_id>/packed
  POST /api/orders/<order_id>/dispatch
  POST /api/orders/<order_id>/move-to-invoiced
  POST /api/orders/<order_id>/complete-dispatch
"""

from datetime import datetime

import werkzeug
from flask import request
from flask_restx import Resource, fields, reqparse

from ..extensions import rest_api
from ..core.auth import token_required, active_required, upload_permission_required
from ..models import (
    PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState,
    Dealer, Box, Order, BoxProduct, Warehouse, Company,
    mysql_manager
)
from ..db_manager import partition_filter
from ..services import order_service
from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Models ───────────────────────────────────────────────────────────────────

upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file',
                           type=werkzeug.datastructures.FileStorage,
                           location='files',
                           required=True,
                           help='Excel/CSV file with order data')
upload_parser.add_argument('warehouse_id',
                           type=int, location='form', required=True,
                           help='Warehouse ID must be provided')
upload_parser.add_argument('company_id',
                           type=int, location='form', required=True,
                           help='Company ID must be provided')

order_upload_response = rest_api.model('OrderUploadResponse', {
    'success':            fields.Boolean(description='Success status of upload'),
    'msg':                fields.String(description='Message describing the result'),
    'orders_processed':   fields.Integer(description='Number of orders processed'),
    'products_processed': fields.Integer(description='Number of products processed'),
    'errors':             fields.List(fields.String, description='List of errors encountered'),
})

product_detail_model = rest_api.model('ProductDetail', {
    'product_id':         fields.String(description='Product ID'),
    'product_string':     fields.String(description='Product string identifier'),
    'name':               fields.String(description='Product name'),
    'description':        fields.String(description='Product description'),
    'quantity_ordered':   fields.Integer(description='Originally ordered quantity'),
    'quantity_available': fields.Integer(description='Available quantity for packed'),
    'quantity_packed':    fields.Integer(description='Quantity already packed'),
    'price':              fields.String(description='Product price'),
})

box_assignment_model = rest_api.model('BoxAssignment', {
    'box_id':    fields.String(description='Box ID'),
    'box_name':  fields.String(description='Box name'),
    'products':  fields.List(fields.Raw, description='Products with quantities in this box'),
})

state_history_model = rest_api.model('StateHistory', {
    'state_name': fields.String(description='State name'),
    'timestamp':  fields.String(description='Timestamp of state change'),
    'user':       fields.String(description='User who changed the state'),
})

order_detail_model = rest_api.model('OrderDetail', {
    'order_request_id':  fields.String(description='Order request ID'),
    'original_order_id': fields.String(description='Original order ID'),
    'dealer_name':       fields.String(description='Dealer name'),
    'order_date':        fields.String(description='Order date'),
    'status':            fields.String(description='Current status'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to':       fields.String(description='User assigned to this order'),
    'products':          fields.List(fields.Nested(product_detail_model), description='Products in this order'),
    'boxes':             fields.List(fields.Nested(box_assignment_model), description='Box assignments'),
    'state_history':     fields.List(fields.Nested(state_history_model), description='State history'),
})

update_status_model = rest_api.model('UpdateStatusModel', {
    'new_status': fields.String(required=True, description='New status'),
    'boxes':      fields.List(fields.Nested(box_assignment_model), description='Box assignments (optional)'),
})

packed_update_model = rest_api.model('PackedUpdate', {
    'products': fields.List(fields.Raw, description='Products with packed quantities and box assignments'),
    'boxes':    fields.List(fields.Nested(box_assignment_model), description='Box assignments'),
})

dispatch_update_model = rest_api.model('DispatchUpdate', {
    'products': fields.List(fields.Raw, description='Final products with quantities for dispatch'),
    'boxes':    fields.List(fields.Nested(box_assignment_model), description='Final box assignments'),
})

error_response = rest_api.model('ErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg':     fields.String(description='Error message'),
})

update_status_response = rest_api.model('UpdateStatusResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg':     fields.String(description='Result message'),
    'order':   fields.Nested(order_detail_model, description='Updated order'),
})

move_to_dispatch_response = rest_api.model('MoveToDispatchResponse', {
    'success':                 fields.Boolean(description='Success status'),
    'msg':                     fields.String(description='Result message'),
    'final_order_id':          fields.Integer(description='Final order ID'),
    'final_order_number':      fields.String(description='Final order number'),
    'total_packed':            fields.Integer(description='Total items packed'),
    'total_remaining':         fields.Integer(description='Total items remaining'),
    'has_remaining_items':     fields.Boolean(description='Whether there are remaining items'),
    'potential_order_status':  fields.String(description='Potential order status'),
    'final_order_status':      fields.String(description='Final order status'),
})

complete_dispatch_response = rest_api.model('CompleteDispatchResponse', {
    'success':             fields.Boolean(description='Success status'),
    'msg':                 fields.String(description='Result message'),
    'final_order_number':  fields.String(description='Final order number'),
    'dispatched_date':     fields.String(description='Dispatch date'),
})

move_to_dispatch_model = rest_api.model('MoveToDispatchModel', {
    'products': fields.List(fields.Raw, description='Products with packed quantities'),
    'boxes':    fields.List(fields.Raw, description='Box assignments'),
})

bulk_status_update_parser = reqparse.RequestParser()
bulk_status_update_parser.add_argument('file',
                                       type=werkzeug.datastructures.FileStorage,
                                       location='files',
                                       required=True,
                                       help='Excel file with Order ID (and Number of Boxes for Packed target)')
bulk_status_update_parser.add_argument('target_status',
                                       type=str, location='form', required=True,
                                       help='Target status to move orders to')
bulk_status_update_parser.add_argument('warehouse_id',
                                       type=int, location='form', required=True)
bulk_status_update_parser.add_argument('company_id',
                                       type=int, location='form', required=True)

# ── Endpoints ────────────────────────────────────────────────────────────────

@rest_api.route('/api/orders/upload')
class OrderUpload(Resource):
    """MySQL handles the upload of Excel/CSV files containing order data."""

    @rest_api.expect(upload_parser)
    @rest_api.response(200, 'Success', order_upload_response)
    @rest_api.response(400, 'Bad Request', order_upload_response)
    @token_required
    @active_required
    @upload_permission_required('orders')
    def post(self, current_user):
        try:
            args = upload_parser.parse_args()
            uploaded_file = args['file']
            warehouse_id  = args['warehouse_id']
            company_id    = args['company_id']

            # Check warehouse+company access for non-admin users
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

            return order_service.process_order_upload(uploaded_file, warehouse_id, company_id, current_user.id)

        except Exception as e:
            return {'success': False, 'msg': f'Error processing upload: {str(e)}',
                    'processed_count': 0, 'error_count': 0}, 400


@rest_api.route('/api/orders/bulk-status-update')
class BulkStatusUpdate(Resource):
    """Bulk-transition orders from an uploaded Excel file."""

    @rest_api.expect(bulk_status_update_parser)
    @token_required
    @active_required
    def post(self, current_user):
        try:
            import os
            from ..utils.upload_utils import (
                save_temp_file, read_upload_file, cleanup_temp_file,
                make_upload_response
            )
            from ..business.order_business import process_bulk_status_update

            args = bulk_status_update_parser.parse_args()
            uploaded_file = args['file']
            target_status = args['target_status'].strip()
            warehouse_id  = args['warehouse_id']
            company_id    = args['company_id']

            if target_status.lower() in ('invoiced', 'invoice'):
                return {
                    'success': False,
                    'msg': 'Cannot bulk-move orders to Invoiced. Use invoice file upload instead.',
                    'processed_count': 0, 'error_count': 0
                }, 400

            # Check warehouse+company access
            from ..permissions import has_all_warehouse_access
            if not has_all_warehouse_access(current_user.role):
                from ..models import UserWarehouseCompany
                if not UserWarehouseCompany.user_can_access(current_user.id, warehouse_id, company_id):
                    return {
                        'success': False, 'msg': 'No access to this warehouse/company.',
                        'processed_count': 0, 'error_count': 0
                    }, 403

            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            temp_path, file_extension = save_temp_file(uploaded_file, BASE_DIR)

            try:
                df = read_upload_file(temp_path, file_extension)
            except Exception as e:
                cleanup_temp_file(temp_path)
                return {'success': False, 'msg': str(e), 'processed_count': 0, 'error_count': 0}, 400
            finally:
                cleanup_temp_file(temp_path)

            # Clean up DataFrame: drop blank rows and normalise column names
            df = df.dropna(how='all')
            df.columns = df.columns.str.replace('\n', ' ').str.replace('\r', ' ').str.strip()

            from ..utils.upload_utils import resolve_required_columns
            required_cols = ['Order ID']
            if target_status.lower() == 'packed':
                required_cols.append('Number of Boxes')
            df, col_error = resolve_required_columns(df, required_cols)
            if col_error:
                return {'success': False, 'msg': col_error, 'processed_count': 0, 'error_count': 0}, 400

            result = process_bulk_status_update(df, target_status, warehouse_id, company_id, current_user.id)
            return make_upload_response(result['orders_processed'], result['error_rows'])

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error processing bulk update: {str(e)}',
                'processed_count': 0, 'error_count': 0
            }, 400


@rest_api.route('/api/orders/<string:order_id>/details')
class OrderDetailWithProducts(Resource):
    """MySQL: Get detailed order information with proper timeline and status."""

    @rest_api.response(200, 'Success')
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    @token_required
    @active_required
    def get(self, _current_user, order_id):
        """Get detailed order information with correct timeline - MySQL."""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            pf_sql, pf_params = partition_filter('potential_order', alias='po')
            order_query = mysql_manager.execute_query(
                f"""SELECT po.*, d.name as dealer_name
                   FROM potential_order po
                   LEFT JOIN dealer d ON po.dealer_id = d.dealer_id
                   WHERE po.potential_order_id = %s AND {pf_sql}""",
                (numeric_id, *pf_params)
            )

            if not order_query:
                return {'success': False, 'msg': 'Order not found'}, 404

            order_data = order_query[0]

            # Get products for this order
            products = PotentialOrderProduct.get_products_for_order(numeric_id)
            formatted_products = []
            for product in products:
                formatted_products.append({
                    'product_id':        product['product_id'],
                    'product_string':    product['product_string'] or f'P{product["product_id"]}',
                    'name':              product['name'],
                    'description':       product['description'] or '',
                    'quantity_ordered':  product['quantity'],
                    'quantity_available': product['quantity'],
                    'quantity_packed':   product['quantity_packed'] or 0,
                    'price':             str(product['price']) if product['price'] else '0.00'
                })

            # Get existing box assignments
            box_products = BoxProduct.get_for_order(numeric_id)
            boxes = {}
            for box_product in box_products:
                if box_product['box_id'] not in boxes:
                    boxes[box_product['box_id']] = {
                        'box_id':   f'B{box_product["box_id"]}',
                        'box_name': box_product['box_name'],
                        'products': []
                    }
                boxes[box_product['box_id']]['products'].append({
                    'product_id': box_product['product_id'],
                    'quantity':   box_product['quantity']
                })
            formatted_boxes = list(boxes.values())

            # Get complete state history
            state_history = OrderStateHistory.get_history_for_order(numeric_id)
            formatted_history = []
            for history in state_history:
                formatted_history.append({
                    'state_name': history['state_name'],
                    'timestamp':  history['changed_at'].isoformat(),
                    'user':       f"User {history['changed_by']}"
                })

            current_state_time = order_data['updated_at']
            if formatted_history:
                current_state_time = state_history[-1]['changed_at']

            status_map = {
                'Open': 'open', 'Picking': 'picking', 'Packed': 'packed',
                'Invoiced': 'invoiced', 'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed', 'Partially Completed': 'partially-completed'
            }
            frontend_status = status_map.get(order_data['status'], 'open')

            final_order = Order.find_by_potential_order_id(numeric_id)
            final_order_info = None
            if final_order:
                final_order_info = {
                    'order_number':    final_order.order_number,
                    'status':          final_order.status,
                    'created_at':      final_order.created_at.isoformat(),
                    'dispatched_date': final_order.dispatched_date.isoformat() if final_order.dispatched_date else None
                }

            response_data = {
                'order_request_id':  f"PO{order_data['potential_order_id']}",
                'original_order_id': order_data['original_order_id'],
                'dealer_name':       order_data['dealer_name'] or 'Unknown Dealer',
                'order_date':        order_data['order_date'].isoformat() if order_data['order_date'] else None,
                'status':            frontend_status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to':       f"User {order_data['requested_by']}",
                'products':          formatted_products,
                'boxes':             formatted_boxes,
                'state_history':     formatted_history,
                'final_order':       final_order_info,
            }

            return {'success': True, 'order': response_data}, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving order details: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>/status')
class OrderStatusUpdate(Resource):
    """MySQL: Regular Status Updates (Open -> Picking -> Packed only)."""

    @rest_api.expect(update_status_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        """Update order status for regular transitions - Complete MySQL implementation."""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            from ..permissions import can_see_order_state
            if not can_see_order_state(current_user.role, potential_order.status):
                return {
                    'success': False,
                    'msg': f'You do not have permission to manage orders in {potential_order.status} status.'
                }, 403

            req_data = request.get_json()
            new_status = req_data.get('new_status')

            if not new_status:
                return {'success': False, 'msg': 'new_status is required'}, 400

            from ..business.order_state_machine import OrderStateMachine
            from ..constants.order_states import OrderStatus

            try:
                db_status = OrderStatus.from_frontend_slug(new_status.lower())
            except ValueError:
                return {
                    'success': False,
                    'msg': f'Invalid status: {new_status}. Use specific endpoints for invoice/dispatch/completed transitions.'
                }, 400

            current_status = potential_order.status
            if not OrderStateMachine.can_single_transition(current_status, db_status):
                allowed = [s.value for s in OrderStateMachine.SINGLE_ORDER_TRANSITIONS.get(current_status, [])]
                return {
                    'success': False,
                    'msg': f'Invalid status transition from {current_status} to {db_status}. '
                           f'Allowed from {current_status}: {", ".join(allowed) if allowed else "None (use specific endpoints)"}'
                }, 400

            if current_status == db_status:
                return {'success': False, 'msg': f'Order is already in {db_status} status'}, 400

            try:
                current_time = datetime.utcnow()

                new_state = OrderState.find_by_name(db_status)
                if not new_state:
                    new_state = OrderState(state_name=db_status,
                                           description=f'{db_status} state - Order processing stage')
                    new_state.save()

                potential_order.status = db_status
                potential_order.updated_at = current_time
                potential_order.save()

                final_order = None

                # When moving to Packed: save box_count on PotentialOrder only.
                if db_status == 'Packed':
                    number_of_boxes = req_data.get('number_of_boxes', 1)
                    try:
                        number_of_boxes = max(1, int(number_of_boxes))
                    except (ValueError, TypeError):
                        number_of_boxes = 1

                    potential_order.box_count = number_of_boxes
                    potential_order.updated_at = current_time
                    potential_order.save()

                    # Auto-transition: if invoice was already submitted while Open/Picking,
                    # go straight to Invoiced now that it's been packed.
                    if potential_order.invoice_submitted:
                        # Record Packed state in history (audit trail)
                        OrderStateHistory(
                            potential_order_id=potential_order.potential_order_id,
                            state_id=new_state.state_id,
                            changed_by=current_user.id,
                            changed_at=current_time
                        ).save()

                        invoiced_state = OrderState.find_by_name('Invoiced')
                        if not invoiced_state:
                            invoiced_state = OrderState(state_name='Invoiced',
                                                        description='Invoice uploaded for order')
                            invoiced_state.save()

                        final_order = Order(
                            potential_order_id=numeric_id,
                            order_number=f"ORD-{numeric_id}-{current_time.strftime('%Y%m%d%H%M')}",
                            status='Invoiced',
                            box_count=potential_order.box_count,
                            created_at=current_time,
                            updated_at=current_time
                        )
                        final_order.save()

                        potential_order.status = 'Invoiced'
                        potential_order.invoice_submitted = False
                        potential_order.updated_at = current_time
                        potential_order.save()

                        db_status = 'Invoiced'
                        new_state = invoiced_state

                # Add state history record
                OrderStateHistory(
                    potential_order_id=potential_order.potential_order_id,
                    state_id=new_state.state_id,
                    changed_by=current_user.id,
                    changed_at=current_time
                ).save()

                dealer = None
                if potential_order.dealer_id:
                    dealer = Dealer.get_by_id(potential_order.dealer_id)
                dealer_name = dealer.name if dealer else 'Unknown Dealer'

                product_count = PotentialOrderProduct.count_by_order(numeric_id)

                state_history_data = OrderStateHistory.get_history_for_order(numeric_id)
                formatted_history = []
                for history in state_history_data:
                    formatted_history.append({
                        'state_name': history['state_name'],
                        'timestamp':  history['changed_at'].isoformat(),
                        'user':       f"User {history['changed_by']}"
                    })

                frontend_status_map = {
                    'Open': 'open', 'Picking': 'picking', 'Packed': 'packed',
                    'Invoiced': 'invoiced', 'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed', 'Partially Completed': 'partially-completed'
                }
                frontend_status = frontend_status_map.get(db_status, 'open')

                updated_order = {
                    'order_request_id':  f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name':       dealer_name,
                    'order_date':        potential_order.order_date.isoformat(),
                    'status':            frontend_status,
                    'current_state_time': current_time.isoformat(),
                    'assigned_to':       f"User {potential_order.requested_by}",
                    'products':          product_count,
                    'box_count':         final_order.box_count if final_order else None,
                    'state_history':     formatted_history,
                }

                return {
                    'success': True,
                    'msg': f'Order status successfully updated from {current_status} to {db_status}',
                    'order': updated_order
                }, 200

            except Exception as e:
                try:
                    potential_order.status = current_status
                    potential_order.save()
                except Exception:
                    pass
                raise e

        except ValueError as ve:
            return {'success': False, 'msg': f'Invalid order ID format: {str(ve)}'}, 400
        except Exception as e:
            return {'success': False, 'msg': f'Error updating order status: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>/packed')
class OrderPackedUpdate(Resource):
    """MySQL: Endpoint for updating packed information with enhanced box quantity handling."""

    @rest_api.expect(packed_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        """Update packed information for an order with comprehensive validation - Complete MySQL."""
        try:
            from ..permissions import can_see_order_state
            if not can_see_order_state(current_user.role, 'Packed'):
                return {'success': False, 'msg': 'You do not have permission to manage Packed orders.'}, 403

            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            req_data   = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data    = req_data.get('boxes', [])

            if potential_order.status != 'Packed':
                return {
                    'success': False,
                    'msg': f'Order must be in Packed status to update packed information. Current status: {potential_order.status}'
                }, 400

            if not products_data:
                return {'success': False, 'msg': 'Products data is required for packed update'}, 400

            # Validate product data structure
            for i, product_data in enumerate(products_data):
                if not isinstance(product_data, dict):
                    return {'success': False, 'msg': f'Product {i} must be an object with product_id and quantity_packed'}, 400
                if 'product_id' not in product_data:
                    return {'success': False, 'msg': f'Product {i} is missing product_id'}, 400
                if 'quantity_packed' not in product_data:
                    return {'success': False, 'msg': f'Product {i} is missing quantity_packed'}, 400
                try:
                    quantity_packed = int(product_data.get('quantity_packed', 0))
                    if quantity_packed < 0:
                        return {'success': False, 'msg': f'Product {i} quantity_packed cannot be negative'}, 400
                except (ValueError, TypeError):
                    return {'success': False, 'msg': f'Product {i} quantity_packed must be a valid number'}, 400

            order_products = PotentialOrderProduct.get_products_for_order(numeric_id)
            order_products_dict = {p['product_id']: p for p in order_products}

            for product_data in products_data:
                product_id = product_data.get('product_id')
                if product_id not in order_products_dict:
                    return {'success': False, 'msg': f'Product {product_id} is not part of this order'}, 400

                quantity_packed = int(product_data.get('quantity_packed', 0))
                max_quantity    = order_products_dict[product_id]['quantity']
                if quantity_packed > max_quantity:
                    return {
                        'success': False,
                        'msg': f'Product {product_id}: Cannot pack {quantity_packed} items. Only {max_quantity} ordered.'
                    }, 400

            try:
                current_time = datetime.utcnow()

                # Step 1: Clear existing box-product assignments for this order
                BoxProduct.delete_for_order(numeric_id)
                logger.debug("Cleared existing box assignments", extra={'order_id': numeric_id})

                # Step 2: Process boxes and their product assignments
                total_box_quantities = {}

                for box_index, box_data in enumerate(boxes_data):
                    if not isinstance(box_data, dict):
                        return {'success': False, 'msg': f'Box {box_index} must be an object'}, 400

                    box_name     = box_data.get('box_name', f'Box {box_index + 1}')
                    box_products = box_data.get('products', [])

                    if not box_products:
                        continue

                    box = Box(name=box_name, created_at=current_time, updated_at=current_time)
                    box.save()
                    logger.debug("Box created", extra={'box_name': box_name, 'box_id': box.box_id})

                    for product_assignment in box_products:
                        if not isinstance(product_assignment, dict):
                            continue

                        product_id = product_assignment.get('product_id')
                        quantity   = int(product_assignment.get('quantity', 0))

                        if not product_id or quantity <= 0:
                            continue

                        if product_id not in order_products_dict:
                            return {
                                'success': False,
                                'msg': f'Product {product_id} in box {box_name} is not part of this order'
                            }, 400

                        if product_id not in total_box_quantities:
                            total_box_quantities[product_id] = 0
                        total_box_quantities[product_id] += quantity

                        BoxProduct(
                            box_id=box.box_id,
                            product_id=product_id,
                            quantity=quantity,
                            potential_order_id=numeric_id,
                            created_at=current_time,
                            updated_at=current_time
                        ).save()
                        logger.debug("Added product to box",
                                     extra={'product_id': product_id, 'box_name': box_name, 'quantity': quantity})

                # Step 3: Validate box quantities match packed quantities
                for product_data in products_data:
                    product_id      = product_data.get('product_id')
                    quantity_packed = int(product_data.get('quantity_packed', 0))
                    box_total       = total_box_quantities.get(product_id, 0)

                    if quantity_packed > 0 and box_total != quantity_packed:
                        return {
                            'success': False,
                            'msg': f'Product {product_id}: Packed quantity ({quantity_packed}) does not match total box assignments ({box_total})'
                        }, 400

                # Step 4: Update packed quantities in potential order products
                for product_data in products_data:
                    product_id      = product_data.get('product_id')
                    quantity_packed = int(product_data.get('quantity_packed', 0))
                    PotentialOrderProduct.update_packed_quantity(numeric_id, product_id, quantity_packed)
                    logger.debug("Updated packed quantity",
                                 extra={'product_id': product_id, 'quantity_packed': quantity_packed})

                # Step 5: Update the order timestamp
                potential_order.updated_at = current_time
                potential_order.save()

                # Step 6: Get updated order details for response
                dealer = None
                if potential_order.dealer_id:
                    dealer = Dealer.get_by_id(potential_order.dealer_id)
                dealer_name = dealer.name if dealer else 'Unknown Dealer'

                updated_products = PotentialOrderProduct.get_products_for_order(numeric_id)
                formatted_products = []
                for product in updated_products:
                    formatted_products.append({
                        'product_id':        product['product_id'],
                        'product_string':    product['product_string'] or f'P{product["product_id"]}',
                        'name':              product['name'],
                        'description':       product['description'] or '',
                        'quantity_ordered':  product['quantity'],
                        'quantity_available': product['quantity'],
                        'quantity_packed':   product['quantity_packed'] or 0,
                        'price':             str(product['price']) if product['price'] else '0.00'
                    })

                updated_box_products = BoxProduct.get_for_order(numeric_id)
                boxes_dict = {}
                for box_product in updated_box_products:
                    if box_product['box_id'] not in boxes_dict:
                        boxes_dict[box_product['box_id']] = {
                            'box_id':   f'B{box_product["box_id"]}',
                            'box_name': box_product['box_name'],
                            'products': []
                        }
                    boxes_dict[box_product['box_id']]['products'].append({
                        'product_id': box_product['product_id'],
                        'quantity':   box_product['quantity']
                    })
                formatted_boxes = list(boxes_dict.values())

                state_history_data = OrderStateHistory.get_history_for_order(numeric_id)
                formatted_history = []
                for history in state_history_data:
                    formatted_history.append({
                        'state_name': history['state_name'],
                        'timestamp':  history['changed_at'].isoformat(),
                        'user':       f"User {history['changed_by']}"
                    })

                updated_order = {
                    'order_request_id':  f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name':       dealer_name,
                    'order_date':        potential_order.order_date.isoformat(),
                    'status':            'packed',
                    'current_state_time': current_time.isoformat(),
                    'assigned_to':       f"User {potential_order.requested_by}",
                    'products':          formatted_products,
                    'boxes':             formatted_boxes,
                    'state_history':     formatted_history,
                }

                total_items_ordered = sum(p['quantity_ordered'] for p in formatted_products)
                total_items_packed  = sum(p['quantity_packed'] for p in formatted_products)
                packed_progress = round(
                    (total_items_packed / total_items_ordered * 100) if total_items_ordered > 0 else 0, 1)

                return {
                    'success': True,
                    'msg': f'Packed information updated successfully. {total_items_packed}/{total_items_ordered} items packed ({packed_progress}%)',
                    'order': updated_order,
                    'packed_summary': {
                        'total_items_ordered': total_items_ordered,
                        'total_items_packed':  total_items_packed,
                        'packed_progress_percent': packed_progress,
                        'boxes_created':       len(formatted_boxes),
                    }
                }, 200

            except Exception as e:
                try:
                    BoxProduct.delete_for_order(numeric_id)
                except Exception:
                    pass
                raise e

        except ValueError as ve:
            return {'success': False, 'msg': f'Invalid order ID format: {str(ve)}'}, 400
        except Exception as e:
            return {'success': False, 'msg': f'Error updating packed information: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>/dispatch')
class OrderDispatchFinal(Resource):
    """MySQL: Endpoint for finalizing order and moving to dispatch."""

    @rest_api.expect(dispatch_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        """Finalize order and create final order record - MySQL."""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            req_data      = request.get_json()
            products_data = req_data.get('products', [])

            if potential_order.status != 'Packed':
                return {'success': False, 'msg': 'Order must be in Packed status to dispatch'}, 400

            current_time = datetime.utcnow()

            total_dispatched_products = 0
            for product_data in products_data:
                product_id      = product_data.get('product_id')
                quantity_packed = product_data.get('quantity_packed', 0)

                if quantity_packed > 0:
                    potential_product = PotentialOrderProduct.find_by_order_and_product(numeric_id, product_id)

                    if potential_product:
                        total_dispatched_products += 1

                        remaining_quantity = potential_product.quantity - quantity_packed
                        if remaining_quantity <= 0:
                            pf_sql, pf_params = partition_filter('potential_order_product')
                            mysql_manager.execute_query(
                                f"DELETE FROM potential_order_product WHERE potential_order_product_id = %s AND {pf_sql}",
                                (potential_product.potential_order_product_id, *pf_params),
                                fetch=False
                            )
                        else:
                            potential_product.quantity        = remaining_quantity
                            potential_product.quantity_packed = 0
                            potential_product.updated_at      = current_time
                            potential_product.save()

            remaining_products = PotentialOrderProduct.count_by_order(numeric_id)

            if remaining_products == 0:
                potential_order.status = 'Completed'
                final_status = 'Completed'
            else:
                potential_order.status = 'Partially Completed'
                final_status = 'Partially Completed'

            potential_order.updated_at = current_time
            potential_order.save()

            final_state = OrderState.find_by_name(final_status)
            if not final_state:
                final_state = OrderState(state_name=final_status, description=f'{final_status} state')
                final_state.save()

            OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=final_state.state_id,
                changed_by=current_user.id,
                changed_at=current_time
            ).save()

            return {
                'success': True,
                'msg': 'Packed quantities updated successfully.',
                'products_dispatched': total_dispatched_products,
                'remaining_products':  remaining_products,
                'final_status':        final_status.lower().replace(' ', '-')
            }, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error dispatching order: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>/move-to-invoiced')
class MoveToInvoiced(Resource):
    """MySQL: Move from Packed to Invoiced - Create Final Order Records."""

    @rest_api.expect(move_to_dispatch_model)
    @rest_api.response(200, 'Success', move_to_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        """Move order from packed to invoice ready and create final order records - MySQL."""
        try:
            from ..permissions import can_see_order_state
            if not can_see_order_state(current_user.role, 'Packed'):
                return {
                    'success': False,
                    'msg': 'You do not have permission to manage orders in Packed status.'
                }, 403

            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            if potential_order.status != 'Packed':
                return {'success': False, 'msg': 'Order must be in Packed status to move to Invoiced'}, 400

            current_time = datetime.utcnow()

            # STEP 1: CREATE FINAL ORDER RECORD
            final_order = Order(
                potential_order_id=numeric_id,
                order_number=f"ORD-{numeric_id}-{current_time.strftime('%Y%m%d%H%M')}",
                status='Dispatch Ready',
                box_count=potential_order.box_count,
                created_at=current_time,
                updated_at=current_time
            )
            final_order.save()

            # STEP 2: UPDATE POTENTIAL ORDER STATUS
            # Bug 19 fix: set PotentialOrder to 'Dispatch Ready' to match the Order record.
            potential_order.status = 'Dispatch Ready'
            potential_order.updated_at = current_time
            potential_order.save()

            # STEP 3: CREATE STATE HISTORY
            dispatch_ready_state = OrderState.find_by_name('Dispatch Ready')
            if not dispatch_ready_state:
                dispatch_ready_state = OrderState(
                    state_name='Dispatch Ready',
                    description='Order invoiced and ready for dispatch'
                )
                dispatch_ready_state.save()

            OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=dispatch_ready_state.state_id,
                changed_by=current_user.id,
                changed_at=current_time
            ).save()

            return {
                'success': True,
                'msg': 'Order moved to invoiced successfully',
                'final_order_id':       final_order.order_id,
                'final_order_number':   final_order.order_number,
                'number_of_boxes':      final_order.box_count,
                'potential_order_status': potential_order.status,
                'final_order_status':   final_order.status,
            }, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error moving to invoiced: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>/complete-dispatch')
class CompleteDispatch(Resource):
    """MySQL: Complete Dispatch - Mark final order as completed (dispatched from warehouse)."""

    @rest_api.response(200, 'Success', complete_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        """Mark order as completed (dispatched from warehouse) - MySQL."""
        try:
            from ..permissions import can_see_order_state
            if not can_see_order_state(current_user.role, 'Dispatch Ready'):
                return {
                    'success': False,
                    'msg': 'You do not have permission to manage orders in Dispatch Ready status.'
                }, 403

            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            final_order = Order.find_by_potential_order_id(numeric_id)

            if not final_order:
                return {
                    'success': False,
                    'msg': 'No final order found. Order must be in Dispatch Ready status first.'
                }, 400

            if final_order.status != 'Dispatch Ready':
                return {'success': False, 'msg': 'Order must be in Dispatch Ready status to complete dispatch'}, 400

            current_time = datetime.utcnow()

            final_order.status         = 'Completed'
            final_order.dispatched_date = current_time
            final_order.updated_at      = current_time
            final_order.save()

            completed_state = OrderState.find_by_name('Completed')
            if not completed_state:
                completed_state = OrderState(state_name='Completed', description='Order completed and dispatched')
                completed_state.save()

            # Bug 14 fix: use current_user.id not hardcoded 1
            OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=completed_state.state_id,
                changed_by=current_user.id,
                changed_at=current_time
            ).save()

            # Bug 16 fix: PotentialOrder may be in 'Dispatch Ready' or 'Invoiced'
            if potential_order.status in ('Dispatch Ready', 'Invoiced'):
                potential_order.status     = 'Completed'
                potential_order.updated_at = current_time
                potential_order.save()

            return {
                'success': True,
                'msg':                 'Order dispatched successfully',
                'final_order_number':  final_order.order_number,
                'dispatched_date':     final_order.dispatched_date.isoformat(),
            }, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error completing dispatch: {str(e)}'}, 400
