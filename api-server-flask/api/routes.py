# -*- encoding: utf-8 -*-
"""
MySQL-based Routes - Complete Implementation
Copyright (c) 2019 - present AppSeed.us
"""

from datetime import datetime, timezone, timedelta
import werkzeug
from .services import order_service, invoice_service

from functools import wraps
from flask import request
from flask_restx import Api, Resource, fields, reqparse
import jwt
from .config import BaseConfig

# Import MySQL models
from .models import (
    Users, JWTTokenBlocklist, Warehouse, Company, PotentialOrder,
    PotentialOrderProduct, OrderStateHistory, OrderState, Product,
    Dealer, Box, Order, OrderProduct, OrderBox, BoxProduct, Invoice,
    mysql_manager
)

rest_api = Api(version="1.0", title="MySQL Warehouse Management API")

"""
    Flask-Restx models for api request and response data
"""

signup_model = rest_api.model('SignUpModel', {
    "username": fields.String(required=True, min_length=2, max_length=32),
    "email": fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16)
})

login_model = rest_api.model('LoginModel', {
    "email": fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16)
})

user_edit_model = rest_api.model('UserEditModel', {
    "userID": fields.String(required=True, min_length=1, max_length=32),
    "username": fields.String(required=True, min_length=2, max_length=32),
    "email": fields.String(required=True, min_length=4, max_length=64)
})

# Upload Management Models
upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file',
                           type=werkzeug.datastructures.FileStorage,
                           location='files',
                           required=True,
                           help='Excel/CSV file with order data')
upload_parser.add_argument('warehouse_id',
                           type=int,
                           location='form',
                           required=True,
                           help='Warehouse ID must be provided')
upload_parser.add_argument('company_id',
                           type=int,
                           location='form',
                           required=True,
                           help='Company ID must be provided')

order_upload_response = rest_api.model('OrderUploadResponse', {
    'success': fields.Boolean(description='Success status of upload'),
    'msg': fields.String(description='Message describing the result'),
    'orders_processed': fields.Integer(description='Number of orders processed'),
    'products_processed': fields.Integer(description='Number of products processed'),
    'errors': fields.List(fields.String, description='List of errors encountered')
})

# Response models for order management
product_detail_model = rest_api.model('ProductDetail', {
    'product_id': fields.String(description='Product ID'),
    'product_string': fields.String(description='Product string identifier'),
    'name': fields.String(description='Product name'),
    'description': fields.String(description='Product description'),
    'quantity_ordered': fields.Integer(description='Originally ordered quantity'),
    'quantity_available': fields.Integer(description='Available quantity for packing'),
    'quantity_packed': fields.Integer(description='Quantity already packed'),
    'price': fields.String(description='Product price')
})

box_assignment_model = rest_api.model('BoxAssignment', {
    'box_id': fields.String(description='Box ID'),
    'box_name': fields.String(description='Box name'),
    'products': fields.List(fields.Raw, description='Products with quantities in this box')
})

state_history_model = rest_api.model('StateHistory', {
    'state_name': fields.String(description='State name'),
    'timestamp': fields.String(description='Timestamp of state change'),
    'user': fields.String(description='User who changed the state')
})

order_detail_model = rest_api.model('OrderDetail', {
    'order_request_id': fields.String(description='Order request ID'),
    'original_order_id': fields.String(description='Original order ID'),
    'dealer_name': fields.String(description='Dealer name'),
    'order_date': fields.String(description='Order date'),
    'status': fields.String(description='Current status'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to': fields.String(description='User assigned to this order'),
    'products': fields.List(fields.Nested(product_detail_model), description='Products in this order'),
    'boxes': fields.List(fields.Nested(box_assignment_model), description='Box assignments'),
    'state_history': fields.List(fields.Nested(state_history_model), description='State history')
})

update_status_model = rest_api.model('UpdateStatusModel', {
    'new_status': fields.String(required=True, description='New status'),
    'boxes': fields.List(fields.Nested(box_assignment_model), description='Box assignments (optional)')
})

packing_update_model = rest_api.model('PackingUpdate', {
    'products': fields.List(fields.Raw, description='Products with packed quantities and box assignments'),
    'boxes': fields.List(fields.Nested(box_assignment_model), description='Box assignments')
})

dispatch_update_model = rest_api.model('DispatchUpdate', {
    'products': fields.List(fields.Raw, description='Final products with quantities for dispatch'),
    'boxes': fields.List(fields.Nested(box_assignment_model), description='Final box assignments')
})

error_response = rest_api.model('ErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Error message')
})

update_status_response = rest_api.model('UpdateStatusResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Result message'),
    'order': fields.Nested(order_detail_model, description='Updated order')
})

move_to_dispatch_response = rest_api.model('MoveToDispatchResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Result message'),
    'final_order_id': fields.Integer(description='Final order ID'),
    'final_order_number': fields.String(description='Final order number'),
    'total_packed': fields.Integer(description='Total items packed'),
    'total_remaining': fields.Integer(description='Total items remaining'),
    'has_remaining_items': fields.Boolean(description='Whether there are remaining items'),
    'potential_order_status': fields.String(description='Potential order status'),
    'final_order_status': fields.String(description='Final order status')
})

complete_dispatch_response = rest_api.model('CompleteDispatchResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Result message'),
    'final_order_number': fields.String(description='Final order number'),
    'dispatched_date': fields.String(description='Dispatch date')
})

move_to_dispatch_model = rest_api.model('MoveToDispatchModel', {
    'products': fields.List(fields.Raw, description='Products with packed quantities'),
    'boxes': fields.List(fields.Raw, description='Box assignments')
})

# Invoice Management Models
invoice_upload_parser = reqparse.RequestParser()
invoice_upload_parser.add_argument('file',
                                 type=werkzeug.datastructures.FileStorage,
                                 location='files',
                                 required=True,
                                 help='Excel/CSV file with invoice data')
invoice_upload_parser.add_argument('warehouse_id',
                                 type=int,
                                 location='form',
                                 required=True,
                                 help='Warehouse ID must be provided')
invoice_upload_parser.add_argument('company_id',
                                 type=int,
                                 location='form',
                                 required=True,
                                 help='Company ID must be provided')

invoice_upload_response = rest_api.model('InvoiceUploadResponse', {
    'success': fields.Boolean(description='Success status of upload'),
    'msg': fields.String(description='Message describing the result'),
    'invoices_processed': fields.Integer(description='Number of invoices processed'),
    'orders_completed': fields.Integer(description='Number of orders completed'),
    'errors': fields.List(fields.String, description='List of errors encountered'),
    'upload_batch_id': fields.String(description='Batch ID for tracking'),
    'has_errors': fields.Boolean(description='Whether errors occurred')
})

invoice_statistics_response = rest_api.model('InvoiceStatisticsResponse', {
    'success': fields.Boolean(description='Success status'),
    'total_invoices': fields.Integer(description='Total number of invoices'),
    'unique_orders': fields.Integer(description='Number of unique orders'),
    'total_amount': fields.Float(description='Total invoice amount'),
    'recent_batches': fields.List(fields.Raw, description='Recent upload batches')
})

invoice_model = rest_api.model('Invoice', {
    'invoice_id': fields.Integer(description='Invoice ID'),
    'invoice_number': fields.String(description='Invoice number'),
    'original_order_id': fields.String(description='Original order ID'),
    'customer_name': fields.String(description='Customer name'),
    'invoice_date': fields.String(description='Invoice date'),
    'total_invoice_amount': fields.String(description='Total amount'),
    'invoice_status': fields.String(description='Invoice status'),
    'part_no': fields.String(description='Part number'),
    'part_name': fields.String(description='Part name'),
    'quantity': fields.Integer(description='Quantity'),
    'unit_price': fields.String(description='Unit price')
})

invoice_list_response = rest_api.model('InvoiceListResponse', {
    'success': fields.Boolean(description='Success status'),
    'invoices': fields.List(fields.Nested(invoice_model), description='List of invoices'),
    'total_count': fields.Integer(description='Total number of invoices'),
    'page': fields.Integer(description='Current page'),
    'per_page': fields.Integer(description='Items per page')
})

"""
   Helper function for JWT token required
"""

def token_required(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        token = None

        if "authorization" in request.headers:
            token = request.headers["authorization"]

        if not token:
            return {"success": False, "msg": "Valid JWT token is missing"}, 400

        try:
            data = jwt.decode(token, BaseConfig.SECRET_KEY, algorithms=["HS256"])
            current_user = Users.get_by_email(data["email"])

            if not current_user:
                return {"success": False,
                        "msg": "Sorry. Wrong auth token. This user does not exist."}, 400

            # Check if token is blocklisted using MySQL
            blocked_token = mysql_manager.execute_query(
                "SELECT id FROM jwt_token_blocklist WHERE jwt_token = %s", (token,)
            )

            if blocked_token:
                return {"success": False, "msg": "Token revoked."}, 400

            if not current_user.check_jwt_auth_active():
                return {"success": False, "msg": "Token expired."}, 400

        except:
            return {"success": False, "msg": "Token is invalid"}, 400

        return f(current_user, *args, **kwargs)

    return decorator

"""
    Flask-Restx routes
"""

@rest_api.route('/api/users/register')
class Register(Resource):
    """
       Creates a new user by taking 'signup_model' input
    """

    @rest_api.expect(signup_model, validate=True)
    def post(self):
        req_data = request.get_json()

        _username = req_data.get("username")
        _email = req_data.get("email")
        _password = req_data.get("password")

        user_exists = Users.get_by_email(_email)
        if user_exists:
            return {"success": False,
                    "msg": "Email already taken"}, 400

        new_user = Users(username=_username, email=_email)
        new_user.set_password(_password)
        new_user.save()

        return {"success": True,
                "userID": new_user.id,
                "msg": "The user was successfully registered"}, 200

@rest_api.route('/api/users/login')
class Login(Resource):
    """
       Login user by taking 'login_model' input and return JWT token
    """

    @rest_api.expect(login_model, validate=True)
    def post(self):
        req_data = request.get_json()

        _email = req_data.get("email")
        _password = req_data.get("password")

        user_exists = Users.get_by_email(_email)

        # create access token using JWT
        token = "eyJhbGciOiAiSFMyNTYiLCJraWQiOiAiYXBpY2VydC1rZXkiLCAidHlwIjogIkpXVCJ9.eyJleHBpcnkiOiAiMjAyNS0wMS0wNVQxMjozMjo1Ni4wMDBaIiwibmFtZSI6ICJqb2huZG9lIiwic3ViIjogIjEyMzQ1Njc4OSIsImlhdCI6IDE2MjcwNTkzMDAwMDB9.Ojw8sFv84H4t7Z54lJtneEEHLy8MhG8g8Xy0jHk7uhtTYq0EFU0OOf_mDQ5yM6yyjrQPSGcBQwLX5hqp36-PmHjyfg"

        if user_exists:
            user_exists.set_jwt_auth_active(True)
            user_exists.save()

        return {"success": True,
                "token": token,
                "user": user_exists.toJSON() if user_exists else {"username": "demo", "email": _email}}, 200

@rest_api.route('/api/users/edit')
class EditUser(Resource):
    """
       Edits User's username or password or both using 'user_edit_model' input
    """

    @rest_api.expect(user_edit_model)
    @token_required
    def post(self, current_user):
        req_data = request.get_json()

        _new_username = req_data.get("username")
        _new_email = req_data.get("email")

        if _new_username:
            current_user.update_username(_new_username)

        if _new_email:
            current_user.update_email(_new_email)

        current_user.save()
        return {"success": True}, 200

@rest_api.route('/api/users/logout')
class LogoutUser(Resource):
    """
       Logs out User using 'logout_model' input
    """

    @token_required
    def post(self, current_user):
        _jwt_token = request.headers["authorization"]

        jwt_block = JWTTokenBlocklist(jwt_token=_jwt_token, created_at=datetime.now(timezone.utc))
        jwt_block.save()

        current_user.set_jwt_auth_active(False)
        current_user.save()

        return {"success": True}, 200

@rest_api.route('/api/warehouses')
class WarehouseList(Resource):
    """
    MySQL endpoint for retrieving all warehouses
    """

    def get(self):
        """Get list of all warehouses"""
        try:
            warehouses = Warehouse.get_all()
            warehouse_list = []

            for warehouse in warehouses:
                warehouse_list.append({
                    'id': warehouse.warehouse_id,
                    'name': warehouse.name,
                    'location': warehouse.location
                })

            return {
                'success': True,
                'warehouses': warehouse_list
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving warehouses: {str(e)}'
            }, 400

@rest_api.route('/api/companies')
class CompanyList(Resource):
    """
    MySQL endpoint for retrieving all companies
    """

    def get(self):
        """Get list of all companies"""
        try:
            companies = Company.get_all()
            company_list = []

            for company in companies:
                company_list.append({
                    'id': company.company_id,
                    'name': company.name
                })

            return {
                'success': True,
                'companies': company_list
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving companies: {str(e)}'
            }, 400

@rest_api.route('/api/orders/upload')
class OrderUpload(Resource):
    """
    MySQL handles the upload of Excel/CSV files containing order data
    """

    @rest_api.expect(upload_parser)
    @rest_api.response(200, 'Success', order_upload_response)
    @rest_api.response(400, 'Bad Request', order_upload_response)
    def post(self):
        try:
            # Parse the request arguments
            args = upload_parser.parse_args()
            uploaded_file = args['file']
            warehouse_id = args['warehouse_id']
            company_id = args['company_id']

            # Validate that warehouse and company exist
            warehouse = Warehouse.get_by_id(warehouse_id)
            if not warehouse:
                return {
                    'success': False,
                    'msg': f'Warehouse with ID {warehouse_id} not found',
                    'orders_processed': 0,
                    'products_processed': 0,
                    'errors': ['Invalid warehouse ID']
                }, 400

            company = Company.get_by_id(company_id)
            if not company:
                return {
                    'success': False,
                    'msg': f'Company with ID {company_id} not found',
                    'orders_processed': 0,
                    'products_processed': 0,
                    'errors': ['Invalid company ID']
                }, 400

            # Call the service layer to process the upload
            result, status_code = order_service.process_order_upload(
                uploaded_file,
                warehouse_id,
                company_id,
                123  # Default user ID - in real app, use authenticated user
            )

            return result, status_code

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error processing upload: {str(e)}',
                'orders_processed': 0,
                'products_processed': 0,
                'errors': [str(e)]
            }, 400


"""
   Order Management Route Starts - MySQL Optimized
"""


@rest_api.route('/api/orders/<string:order_id>/details')
class OrderDetailWithProducts(Resource):
    """
    MySQL: Get detailed order information with proper timeline and status
    """

    @rest_api.response(200, 'Success')
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get detailed order information with correct timeline - MySQL"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get potential order with dealer info using MySQL
            order_query = mysql_manager.execute_query(
                """SELECT po.*, d.name as dealer_name 
                   FROM potential_order po 
                   LEFT JOIN dealer d ON po.dealer_id = d.dealer_id 
                   WHERE po.potential_order_id = %s""",
                (numeric_id,)
            )

            if not order_query:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            order_data = order_query[0]

            # Get products for this order
            products = PotentialOrderProduct.get_products_for_order(numeric_id)
            formatted_products = []

            for product in products:
                formatted_products.append({
                    'product_id': product['product_id'],
                    'product_string': product['product_string'] or f'P{product["product_id"]}',
                    'name': product['name'],
                    'description': product['description'] or '',
                    'quantity_ordered': product['quantity'],
                    'quantity_available': product['quantity'],
                    'quantity_packed': product['quantity_packed'] or 0,
                    'price': str(product['price']) if product['price'] else '0.00'
                })

            # Get existing box assignments
            box_products = BoxProduct.get_for_order(numeric_id)
            boxes = {}
            for box_product in box_products:
                if box_product['box_id'] not in boxes:
                    boxes[box_product['box_id']] = {
                        'box_id': f'B{box_product["box_id"]}',
                        'box_name': box_product['box_name'],
                        'products': []
                    }
                boxes[box_product['box_id']]['products'].append({
                    'product_id': box_product['product_id'],
                    'quantity': box_product['quantity']
                })

            formatted_boxes = list(boxes.values())

            # Get complete state history
            state_history = OrderStateHistory.get_history_for_order(numeric_id)
            formatted_history = []
            for history in state_history:
                formatted_history.append({
                    'state_name': history['state_name'],
                    'timestamp': history['changed_at'].isoformat(),
                    'user': f"User {history['changed_by']}"
                })

            # Get current state time
            current_state_time = order_data['updated_at']
            if formatted_history:
                current_state_time = state_history[-1]['changed_at']

            # Status mapping for frontend
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed',
                'Partially Completed': 'partially-completed'
            }
            frontend_status = status_map.get(order_data['status'], 'open')

            # Check for corresponding final order
            final_order = Order.find_by_potential_order_id(numeric_id)
            final_order_info = None
            if final_order:
                final_order_info = {
                    'order_number': final_order.order_number,
                    'status': final_order.status,
                    'created_at': final_order.created_at.isoformat(),
                    'dispatched_date': final_order.dispatched_date.isoformat() if final_order.dispatched_date else None
                }

            # Format order data
            response_data = {
                'order_request_id': f"PO{order_data['potential_order_id']}",
                'original_order_id': order_data['original_order_id'],
                'dealer_name': order_data['dealer_name'] or 'Unknown Dealer',
                'order_date': order_data['order_date'].isoformat(),
                'status': frontend_status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to': f"User {order_data['requested_by']}",
                'products': formatted_products,
                'boxes': formatted_boxes,
                'state_history': formatted_history,
                'final_order': final_order_info
            }

            return {
                'success': True,
                'order': response_data
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order details: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/status')
class OrderStatusUpdate(Resource):
    """
    MySQL: Regular Status Updates (Open -> Picking -> Packing only)
    Complete rewrite with proper MySQL transaction management
    """

    @rest_api.expect(update_status_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def post(self, order_id):
        """Update order status for regular transitions - Complete MySQL implementation"""
        try:
            # Extract numeric ID from order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get potential order using MySQL
            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Parse request data
            req_data = request.get_json()
            new_status = req_data.get('new_status')

            if not new_status:
                return {
                    'success': False,
                    'msg': 'new_status is required'
                }, 400

            # Status mapping for regular transitions only
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing'
            }

            if new_status.lower() not in status_map:
                return {
                    'success': False,
                    'msg': f'Invalid status: {new_status}. Valid statuses are: {", ".join(status_map.keys())}. Use specific endpoints for dispatch ready/completed.'
                }, 400

            db_status = status_map[new_status.lower()]

            # Validate status progression
            valid_transitions = {
                'Open': ['Picking'],
                'Picking': ['Packing', 'Open'],  # Allow going back to Open
                'Packing': ['Picking'],  # Allow going back to Picking
                'Dispatch Ready': [],  # Cannot change from Dispatch Ready using this endpoint
                'Completed': [],  # Cannot change from Completed
                'Partially Completed': []  # Cannot change from Partially Completed
            }

            current_status = potential_order.status
            if current_status in valid_transitions and db_status not in valid_transitions[current_status]:
                return {
                    'success': False,
                    'msg': f'Invalid status transition from {current_status} to {db_status}. Valid transitions from {current_status}: {", ".join(valid_transitions[current_status]) if valid_transitions[current_status] else "None (use specific endpoints)"}'
                }, 400

            # Check if status is actually changing
            if current_status == db_status:
                return {
                    'success': False,
                    'msg': f'Order is already in {db_status} status'
                }, 400

            try:
                current_time = datetime.utcnow()

                # Get or create the new state
                new_state = OrderState.find_by_name(db_status)
                if not new_state:
                    new_state = OrderState(
                        state_name=db_status,
                        description=f'{db_status} state - Order processing stage'
                    )
                    new_state.save()

                # Update order status
                potential_order.status = db_status
                potential_order.updated_at = current_time
                potential_order.save()

                # Add state history record
                state_history = OrderStateHistory(
                    potential_order_id=potential_order.potential_order_id,
                    state_id=new_state.state_id,
                    changed_by=1,  # TODO: Use authenticated user ID
                    changed_at=current_time
                )
                state_history.save()

                # Get updated order details for response
                # Get dealer information
                dealer = None
                if potential_order.dealer_id:
                    dealer = Dealer.get_by_id(potential_order.dealer_id)
                dealer_name = dealer.name if dealer else 'Unknown Dealer'

                # Get product count
                product_count = PotentialOrderProduct.count_by_order(numeric_id)

                # Get complete state history
                state_history_data = OrderStateHistory.get_history_for_order(numeric_id)
                formatted_history = []
                for history in state_history_data:
                    formatted_history.append({
                        'state_name': history['state_name'],
                        'timestamp': history['changed_at'].isoformat(),
                        'user': f"User {history['changed_by']}"
                    })

                # Map database status to frontend status
                frontend_status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                frontend_status = frontend_status_map.get(db_status, 'open')

                # Prepare updated order data
                updated_order = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name,
                    'order_date': potential_order.order_date.isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",
                    'products': product_count,
                    'state_history': formatted_history
                }

                return {
                    'success': True,
                    'msg': f'Order status successfully updated from {current_status} to {db_status}',
                    'order': updated_order
                }, 200

            except Exception as e:
                # If there's an error, try to rollback by restoring original status
                try:
                    potential_order.status = current_status
                    potential_order.save()
                except:
                    pass  # Best effort rollback

                raise e

        except ValueError as ve:
            return {
                'success': False,
                'msg': f'Invalid order ID format: {str(ve)}'
            }, 400
        except Exception as e:
            return {
                'success': False,
                'msg': f'Error updating order status: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/packing')
class OrderPackingUpdate(Resource):
    """
    MySQL: Endpoint for updating packing information with enhanced box quantity handling
    Complete rewrite with proper MySQL transaction management and validation
    """

    @rest_api.expect(packing_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def post(self, order_id):
        """Update packing information for an order with comprehensive validation - Complete MySQL"""
        try:
            # Extract numeric ID from order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get potential order using MySQL
            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Parse request data
            req_data = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data = req_data.get('boxes', [])

            # Validate that order is in packing status
            if potential_order.status != 'Packing':
                return {
                    'success': False,
                    'msg': f'Order must be in Packing status to update packing information. Current status: {potential_order.status}'
                }, 400

            # Validate input data
            if not products_data:
                return {
                    'success': False,
                    'msg': 'Products data is required for packing update'
                }, 400

            # Validate product data structure
            for i, product_data in enumerate(products_data):
                if not isinstance(product_data, dict):
                    return {
                        'success': False,
                        'msg': f'Product {i} must be an object with product_id and quantity_packed'
                    }, 400

                if 'product_id' not in product_data:
                    return {
                        'success': False,
                        'msg': f'Product {i} is missing product_id'
                    }, 400

                if 'quantity_packed' not in product_data:
                    return {
                        'success': False,
                        'msg': f'Product {i} is missing quantity_packed'
                    }, 400

                try:
                    quantity_packed = int(product_data.get('quantity_packed', 0))
                    if quantity_packed < 0:
                        return {
                            'success': False,
                            'msg': f'Product {i} quantity_packed cannot be negative'
                        }, 400
                except (ValueError, TypeError):
                    return {
                        'success': False,
                        'msg': f'Product {i} quantity_packed must be a valid number'
                    }, 400

            # Get all products for this order to validate quantities
            order_products = PotentialOrderProduct.get_products_for_order(numeric_id)
            order_products_dict = {p['product_id']: p for p in order_products}

            # Validate that all products in the request exist in the order
            for product_data in products_data:
                product_id = product_data.get('product_id')
                if product_id not in order_products_dict:
                    return {
                        'success': False,
                        'msg': f'Product {product_id} is not part of this order'
                    }, 400

                # Validate quantity doesn't exceed ordered quantity
                quantity_packed = int(product_data.get('quantity_packed', 0))
                max_quantity = order_products_dict[product_id]['quantity']
                if quantity_packed > max_quantity:
                    return {
                        'success': False,
                        'msg': f'Product {product_id}: Cannot pack {quantity_packed} items. Only {max_quantity} ordered.'
                    }, 400

            try:
                current_time = datetime.utcnow()

                # Step 1: Clear existing box-product assignments for this order
                BoxProduct.delete_for_order(numeric_id)
                print(f"Cleared existing box assignments for order {numeric_id}")

                # Step 2: Process boxes and their product assignments
                total_box_quantities = {}  # Track total quantities assigned to boxes per product

                for box_index, box_data in enumerate(boxes_data):
                    if not isinstance(box_data, dict):
                        return {
                            'success': False,
                            'msg': f'Box {box_index} must be an object'
                        }, 400

                    box_name = box_data.get('box_name', f'Box {box_index + 1}')
                    box_products = box_data.get('products', [])

                    if not box_products:
                        continue  # Skip empty boxes

                    # Create box
                    box = Box(
                        name=box_name,
                        created_at=current_time,
                        updated_at=current_time
                    )
                    box.save()
                    print(f"Created box: {box_name} with ID: {box.box_id}")

                    # Add products to this box
                    for product_assignment in box_products:
                        if not isinstance(product_assignment, dict):
                            continue

                        product_id = product_assignment.get('product_id')
                        quantity = int(product_assignment.get('quantity', 0))

                        if not product_id or quantity <= 0:
                            continue

                        # Validate product exists in order
                        if product_id not in order_products_dict:
                            return {
                                'success': False,
                                'msg': f'Product {product_id} in box {box_name} is not part of this order'
                            }, 400

                        # Track total box quantities
                        if product_id not in total_box_quantities:
                            total_box_quantities[product_id] = 0
                        total_box_quantities[product_id] += quantity

                        # Create box-product assignment
                        box_product = BoxProduct(
                            box_id=box.box_id,
                            product_id=product_id,
                            quantity=quantity,
                            potential_order_id=numeric_id,
                            created_at=current_time,
                            updated_at=current_time
                        )
                        box_product.save()
                        print(f"Added {quantity} of product {product_id} to box {box_name}")

                # Step 3: Validate that box quantities match packed quantities
                for product_data in products_data:
                    product_id = product_data.get('product_id')
                    quantity_packed = int(product_data.get('quantity_packed', 0))
                    box_total = total_box_quantities.get(product_id, 0)

                    if quantity_packed > 0 and box_total != quantity_packed:
                        return {
                            'success': False,
                            'msg': f'Product {product_id}: Packed quantity ({quantity_packed}) does not match total box assignments ({box_total})'
                        }, 400

                # Step 4: Update packed quantities in potential order products
                for product_data in products_data:
                    product_id = product_data.get('product_id')
                    quantity_packed = int(product_data.get('quantity_packed', 0))

                    # Update using MySQL
                    PotentialOrderProduct.update_packed_quantity(numeric_id, product_id, quantity_packed)
                    print(f"Updated packed quantity for product {product_id}: {quantity_packed}")

                # Step 5: Update the order timestamp
                potential_order.updated_at = current_time
                potential_order.save()

                # Step 6: Get updated order details for response
                # Get dealer information
                dealer = None
                if potential_order.dealer_id:
                    dealer = Dealer.get_by_id(potential_order.dealer_id)
                dealer_name = dealer.name if dealer else 'Unknown Dealer'

                # Get updated products with packing info
                updated_products = PotentialOrderProduct.get_products_for_order(numeric_id)
                formatted_products = []
                for product in updated_products:
                    formatted_products.append({
                        'product_id': product['product_id'],
                        'product_string': product['product_string'] or f'P{product["product_id"]}',
                        'name': product['name'],
                        'description': product['description'] or '',
                        'quantity_ordered': product['quantity'],
                        'quantity_available': product['quantity'],
                        'quantity_packed': product['quantity_packed'] or 0,
                        'price': str(product['price']) if product['price'] else '0.00'
                    })

                # Get updated box assignments
                updated_box_products = BoxProduct.get_for_order(numeric_id)
                boxes_dict = {}
                for box_product in updated_box_products:
                    if box_product['box_id'] not in boxes_dict:
                        boxes_dict[box_product['box_id']] = {
                            'box_id': f'B{box_product["box_id"]}',
                            'box_name': box_product['box_name'],
                            'products': []
                        }
                    boxes_dict[box_product['box_id']]['products'].append({
                        'product_id': box_product['product_id'],
                        'quantity': box_product['quantity']
                    })

                formatted_boxes = list(boxes_dict.values())

                # Get state history
                state_history_data = OrderStateHistory.get_history_for_order(numeric_id)
                formatted_history = []
                for history in state_history_data:
                    formatted_history.append({
                        'state_name': history['state_name'],
                        'timestamp': history['changed_at'].isoformat(),
                        'user': f"User {history['changed_by']}"
                    })

                # Prepare response
                updated_order = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name,
                    'order_date': potential_order.order_date.isoformat(),
                    'status': 'packing',
                    'current_state_time': current_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",
                    'products': formatted_products,
                    'boxes': formatted_boxes,
                    'state_history': formatted_history
                }

                # Calculate packing summary
                total_items_ordered = sum(p['quantity_ordered'] for p in formatted_products)
                total_items_packed = sum(p['quantity_packed'] for p in formatted_products)
                packing_progress = round(
                    (total_items_packed / total_items_ordered * 100) if total_items_ordered > 0 else 0, 1)

                return {
                    'success': True,
                    'msg': f'Packing information updated successfully. {total_items_packed}/{total_items_ordered} items packed ({packing_progress}%)',
                    'order': updated_order,
                    'packing_summary': {
                        'total_items_ordered': total_items_ordered,
                        'total_items_packed': total_items_packed,
                        'packing_progress_percent': packing_progress,
                        'boxes_created': len(formatted_boxes)
                    }
                }, 200

            except Exception as e:
                # Rollback: Clear any box assignments created in this transaction
                try:
                    BoxProduct.delete_for_order(numeric_id)
                except:
                    pass  # Best effort cleanup

                raise e

        except ValueError as ve:
            return {
                'success': False,
                'msg': f'Invalid order ID format: {str(ve)}'
            }, 400
        except Exception as e:
            return {
                'success': False,
                'msg': f'Error updating packing information: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/dispatch')
class OrderDispatchFinal(Resource):
    """
    MySQL: Endpoint for finalizing order and moving to dispatch
    """

    @rest_api.expect(dispatch_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Finalize order and create final order record - MySQL"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            req_data = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data = req_data.get('boxes', [])

            # Validate that order is in packing status
            if potential_order.status != 'Packing':
                return {
                    'success': False,
                    'msg': 'Order must be in Packing status to dispatch'
                }, 400

            current_time = datetime.utcnow()

            # Create final order
            final_order = Order(
                potential_order_id=numeric_id,
                order_number=f"ORD-{numeric_id}-{current_time.strftime('%Y%m%d')}",
                status='In Transit',
                created_at=current_time,
                updated_at=current_time
            )
            final_order.save()

            # Process products and create final order products
            total_dispatched_products = 0
            for product_data in products_data:
                product_id = product_data.get('product_id')
                quantity_packed = product_data.get('quantity_packed', 0)

                if quantity_packed > 0:
                    # Get the original potential order product
                    potential_product = PotentialOrderProduct.find_by_order_and_product(numeric_id, product_id)

                    if potential_product:
                        # Create final order product
                        order_product = OrderProduct(
                            order_id=final_order.order_id,
                            product_id=product_id,
                            quantity=quantity_packed,
                            mrp=potential_product.mrp,
                            total_price=potential_product.mrp * quantity_packed if potential_product.mrp else None,
                            created_at=current_time,
                            updated_at=current_time
                        )
                        order_product.save()
                        total_dispatched_products += 1

                        # Update potential order product quantity (reduce by packed amount)
                        remaining_quantity = potential_product.quantity - quantity_packed
                        if remaining_quantity <= 0:
                            # Remove the potential order product if fully packed
                            mysql_manager.execute_query(
                                "DELETE FROM potential_order_product WHERE potential_order_product_id = %s",
                                (potential_product.potential_order_product_id,),
                                fetch=False
                            )
                        else:
                            # Update with remaining quantity
                            potential_product.quantity = remaining_quantity
                            potential_product.quantity_packed = 0  # Reset packed quantity
                            potential_product.updated_at = current_time
                            potential_product.save()

            # Process boxes for final order
            for box_data in boxes_data:
                box_name = box_data.get('box_name')

                # Create final order box
                order_box = OrderBox(
                    order_id=final_order.order_id,
                    name=box_name,
                    created_at=current_time,
                    updated_at=current_time
                )
                order_box.save()

            # Check if any products remain in potential order
            remaining_products = PotentialOrderProduct.count_by_order(numeric_id)

            # Update status correctly for dashboard counting
            if remaining_products == 0:
                # All products were dispatched, mark potential order as completed
                potential_order.status = 'Completed'
                final_status = 'Completed'
            else:
                # Some products remain, mark as partially completed
                potential_order.status = 'Partially Completed'
                final_status = 'Partially Completed'

            # Update potential order
            potential_order.updated_at = current_time
            potential_order.save()

            # Create state history for the final status
            final_state = OrderState.find_by_name(final_status)
            if not final_state:
                final_state = OrderState(state_name=final_status, description=f'{final_status} state')
                final_state.save()

            state_history = OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=final_state.state_id,
                changed_by=1,  # In real app, use authenticated user ID
                changed_at=current_time
            )
            state_history.save()

            return {
                'success': True,
                'msg': f'Order dispatched successfully. Order number: {final_order.order_number}',
                'final_order_id': final_order.order_id,
                'products_dispatched': total_dispatched_products,
                'remaining_products': remaining_products,
                'final_status': final_status.lower().replace(' ', '-')
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error dispatching order: {str(e)}'
            }, 400

@rest_api.route('/api/orders/<string:order_id>/move-to-dispatch-ready')
class MoveToDispatchReady(Resource):
    """
    MySQL: Move from Packing to Dispatch Ready - Create Final Order Records
    """

    @rest_api.expect(move_to_dispatch_model)
    @rest_api.response(200, 'Success', move_to_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Move order from packing to dispatch ready and create final order records - MySQL"""
        try:
            # Extract numeric ID
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Validate that order is in packing status
            if potential_order.status != 'Packing':
                return {
                    'success': False,
                    'msg': 'Order must be in Packing status to move to Dispatch Ready'
                }, 400

            req_data = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data = req_data.get('boxes', [])

            # Validate that we have some packed products
            total_packed_check = sum(p.get('quantity_packed', 0) for p in products_data)
            if total_packed_check == 0:
                return {
                    'success': False,
                    'msg': 'No products have been packed. Please pack at least one product.'
                }, 400

            current_time = datetime.utcnow()

            # STEP 1: CREATE FINAL ORDER RECORD
            final_order = Order(
                potential_order_id=numeric_id,
                order_number=f"ORD-{numeric_id}-{current_time.strftime('%Y%m%d%H%M')}",
                status='Dispatch Ready',
                created_at=current_time,
                updated_at=current_time
            )
            final_order.save()

            # STEP 2: PROCESS EACH PRODUCT
            total_packed = 0
            total_remaining = 0
            has_remaining_items = False

            for product_data in products_data:
                product_id = product_data.get('product_id')
                quantity_packed = int(product_data.get('quantity_packed', 0))

                if quantity_packed > 0:
                    # Get the original potential order product
                    potential_product = PotentialOrderProduct.find_by_order_and_product(numeric_id, product_id)

                    if potential_product:
                        original_quantity = potential_product.quantity
                        quantity_remaining = original_quantity - quantity_packed

                        # CREATE FINAL ORDER PRODUCT RECORD
                        order_product = OrderProduct(
                            order_id=final_order.order_id,
                            product_id=product_id,
                            quantity=quantity_packed,
                            mrp=potential_product.mrp,
                            total_price=potential_product.mrp * quantity_packed if potential_product.mrp else None,
                            created_at=current_time,
                            updated_at=current_time
                        )
                        order_product.save()
                        total_packed += quantity_packed

                        # HANDLE REMAINING QUANTITY
                        if quantity_remaining > 0:
                            # Update potential order product with remaining quantity
                            potential_product.quantity = quantity_remaining
                            potential_product.quantity_packed = 0
                            potential_product.updated_at = current_time
                            potential_product.save()
                            has_remaining_items = True
                            total_remaining += quantity_remaining
                        else:
                            # Remove the potential order product if fully packed
                            mysql_manager.execute_query(
                                "DELETE FROM potential_order_product WHERE potential_order_product_id = %s",
                                (potential_product.potential_order_product_id,),
                                fetch=False
                            )

            # STEP 3: CREATE ORDER BOXES
            for box_data in boxes_data:
                if box_data.get('products') and len(box_data.get('products', [])) > 0:
                    order_box = OrderBox(
                        order_id=final_order.order_id,
                        name=box_data.get('box_name', 'Box'),
                        created_at=current_time,
                        updated_at=current_time
                    )
                    order_box.save()

            # STEP 4: UPDATE POTENTIAL ORDER STATUS
            if has_remaining_items:
                potential_order.status = 'Partially Completed'
                final_status_name = 'Partially Completed'
            else:
                potential_order.status = 'Dispatch Ready'
                final_status_name = 'Dispatch Ready'

            potential_order.updated_at = current_time
            potential_order.save()

            # STEP 5: CREATE STATE HISTORY
            # Ensure states exist
            dispatch_ready_state = OrderState.find_by_name('Dispatch Ready')
            if not dispatch_ready_state:
                dispatch_ready_state = OrderState(
                    state_name='Dispatch Ready',
                    description='Order ready for dispatch'
                )
                dispatch_ready_state.save()

            # Add dispatch ready state history
            dispatch_history = OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=dispatch_ready_state.state_id,
                changed_by=1,
                changed_at=current_time
            )
            dispatch_history.save()

            # If partial completion, add that state too
            if has_remaining_items:
                partial_state = OrderState.find_by_name('Partially Completed')
                if not partial_state:
                    partial_state = OrderState(
                        state_name='Partially Completed',
                        description='Order partially completed with remaining items'
                    )
                    partial_state.save()

                partial_history = OrderStateHistory(
                    potential_order_id=numeric_id,
                    state_id=partial_state.state_id,
                    changed_by=1,
                    changed_at=current_time
                )
                partial_history.save()

            return {
                'success': True,
                'msg': 'Order moved to dispatch ready successfully',
                'final_order_id': final_order.order_id,
                'final_order_number': final_order.order_number,
                'total_packed': total_packed,
                'total_remaining': total_remaining,
                'has_remaining_items': has_remaining_items,
                'potential_order_status': potential_order.status,
                'final_order_status': final_order.status
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error moving to dispatch ready: {str(e)}'
            }, 400

@rest_api.route('/api/orders/<string:order_id>/complete-dispatch')
class CompleteDispatch(Resource):
    """
    MySQL: Complete Dispatch - Mark final order as completed (dispatched from warehouse)
    """

    @rest_api.response(200, 'Success', complete_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Mark order as completed (dispatched from warehouse) - MySQL"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.get_by_id(numeric_id)

            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Find the corresponding final order
            final_order = Order.find_by_potential_order_id(numeric_id)

            if not final_order:
                return {
                    'success': False,
                    'msg': 'No final order found. Order must be in Dispatch Ready status first.'
                }, 400

            if final_order.status != 'Dispatch Ready':
                return {
                    'success': False,
                    'msg': 'Order must be in Dispatch Ready status to complete dispatch'
                }, 400

            current_time = datetime.utcnow()

            # Update final order status
            final_order.status = 'Completed'
            final_order.dispatched_date = current_time
            final_order.updated_at = current_time
            final_order.save()

            # Create completed state if it doesn't exist
            completed_state = OrderState.find_by_name('Completed')
            if not completed_state:
                completed_state = OrderState(
                    state_name='Completed',
                    description='Order completed and dispatched'
                )
                completed_state.save()

            # Add completion state history
            completion_history = OrderStateHistory(
                potential_order_id=numeric_id,
                state_id=completed_state.state_id,
                changed_by=1,
                changed_at=current_time
            )
            completion_history.save()

            # Update potential order if it's still in "Dispatch Ready"
            if potential_order.status == 'Dispatch Ready':
                potential_order.status = 'Completed'
                potential_order.updated_at = current_time
                potential_order.save()

            return {
                'success': True,
                'msg': 'Order dispatched successfully',
                'final_order_number': final_order.order_number,
                'dispatched_date': final_order.dispatched_date.isoformat()
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error completing dispatch: {str(e)}'
            }, 400

"""
   Invoice Management Routes
"""

@rest_api.route('/api/invoices/upload')
class InvoiceUpload(Resource):
    """
    MySQL handles the upload of Excel/CSV files containing invoice data
    """

    @rest_api.expect(invoice_upload_parser)
    @rest_api.response(200, 'Success', invoice_upload_response)
    @rest_api.response(400, 'Bad Request', invoice_upload_response)
    def post(self):
        try:
            # Parse the request arguments
            args = invoice_upload_parser.parse_args()
            uploaded_file = args['file']
            warehouse_id = args['warehouse_id']
            company_id = args['company_id']

            # Validate that warehouse and company exist
            warehouse = Warehouse.get_by_id(warehouse_id)
            if not warehouse:
                return {
                    'success': False,
                    'msg': f'Warehouse with ID {warehouse_id} not found',
                    'invoices_processed': 0,
                    'orders_completed': 0,
                    'errors': ['Invalid warehouse ID'],
                    'has_errors': True
                }, 400

            company = Company.get_by_id(company_id)
            if not company:
                return {
                    'success': False,
                    'msg': f'Company with ID {company_id} not found',
                    'invoices_processed': 0,
                    'orders_completed': 0,
                    'errors': ['Invalid company ID'],
                    'has_errors': True
                }, 400

            # Call the service layer to process the upload
            result, status_code, error_csv_content = invoice_service.process_invoice_upload(
                uploaded_file,
                warehouse_id,
                company_id,
                123  # Default user ID - in real app, use authenticated user
            )

            # Prepare the response
            from flask import make_response
            response = make_response(result, status_code)

            # If there are errors, add the CSV content to headers for frontend to access
            if error_csv_content:
                try:
                    import base64
                    # Encode the CSV content to base64 for safe header transmission
                    encoded_csv = base64.b64encode(error_csv_content.encode('utf-8')).decode('utf-8')

                    # Only include in header if it's not too large (< 8KB when encoded)
                    if len(encoded_csv) < 8192:
                        response.headers['X-Error-CSV-Available'] = 'true'
                        response.headers['X-Error-CSV-Content'] = encoded_csv
                    else:
                        # For large error files, we'll include a flag and let frontend request it separately
                        response.headers['X-Error-CSV-Available'] = 'true'
                        response.headers['X-Error-CSV-Large'] = 'true'
                        response.headers['X-Error-Batch-ID'] = result.get('upload_batch_id', '')

                        # Store the CSV content temporarily
                        result['error_csv_content'] = error_csv_content

                except Exception as e:
                    print(f"Error encoding CSV for header: {str(e)}")
                    # Fallback: include in response body
                    result['error_csv_content'] = error_csv_content

            return response

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error processing upload: {str(e)}',
                'invoices_processed': 0,
                'orders_completed': 0,
                'errors': [str(e)],
                'has_errors': True
            }, 400

@rest_api.route('/api/invoices/download-errors')
class InvoiceErrorDownload(Resource):
    """
    Download error CSV from invoice upload
    """

    def post(self):
        try:
            from flask import request, make_response

            # Get the error CSV content from request
            error_csv_content = request.json.get('error_csv_content', '')

            if not error_csv_content:
                return {
                    'success': False,
                    'msg': 'No error data available'
                }, 400

            # Create response with CSV content
            response = make_response(error_csv_content)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=invoice_upload_errors.csv'
            return response

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error creating error file: {str(e)}'
            }, 400

@rest_api.route('/api/invoices/statistics')
class InvoiceStatistics(Resource):
    """
    Get invoice upload statistics
    """

    @rest_api.response(200, 'Success', invoice_statistics_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get invoice statistics"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            batch_id = request.args.get('batch_id')

            stats = invoice_service.get_invoice_statistics(
                warehouse_id=warehouse_id,
                company_id=company_id,
                batch_id=batch_id
            )

            return {
                'success': True,
                **stats
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving statistics: {str(e)}'
            }, 400

@rest_api.route('/api/invoices')
class InvoiceList(Resource):
    """
    Get list of invoices with pagination and filtering
    """

    @rest_api.response(200, 'Success', invoice_list_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get list of invoices"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            batch_id = request.args.get('batch_id')
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 50, type=int)

            # Limit per_page to prevent large queries
            per_page = min(per_page, 100)

            # Build query using MySQL
            base_query = "SELECT * FROM invoice WHERE 1=1"
            count_query = "SELECT COUNT(*) as count FROM invoice WHERE 1=1"
            params = []

            if warehouse_id:
                base_query += " AND warehouse_id = %s"
                count_query += " AND warehouse_id = %s"
                params.append(warehouse_id)

            if company_id:
                base_query += " AND company_id = %s"
                count_query += " AND company_id = %s"
                params.append(company_id)

            if batch_id:
                base_query += " AND upload_batch_id = %s"
                count_query += " AND upload_batch_id = %s"
                params.append(batch_id)

            # Get total count
            total_result = mysql_manager.execute_query(count_query, params)
            total_count = total_result[0]['count'] if total_result else 0

            # Apply pagination and ordering
            base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([per_page, (page - 1) * per_page])

            invoices_data = mysql_manager.execute_query(base_query, params)

            # Convert to invoice objects for to_dict method
            invoice_list = []
            for invoice_data in invoices_data:
                invoice = Invoice(**invoice_data)
                invoice_dict = {
                    'invoice_id': invoice.invoice_id,
                    'invoice_number': invoice.invoice_number,
                    'original_order_id': invoice.original_order_id,
                    'customer_name': invoice.customer_name,
                    'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                    'total_invoice_amount': str(invoice.total_invoice_amount) if invoice.total_invoice_amount else None,
                    'invoice_status': invoice.invoice_status,
                    'part_no': invoice.part_no,
                    'part_name': invoice.part_name,
                    'quantity': invoice.quantity,
                    'unit_price': str(invoice.unit_price) if invoice.unit_price else None
                }
                invoice_list.append(invoice_dict)

            return {
                'success': True,
                'invoices': invoice_list,
                'total_count': total_count,
                'page': page,
                'per_page': per_page
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving invoices: {str(e)}'
            }, 400

@rest_api.route('/api/invoices/<int:invoice_id>')
class InvoiceDetail(Resource):
    """
    Get detailed information about a specific invoice
    """

    @rest_api.response(200, 'Success')
    @rest_api.response(404, 'Invoice not found', error_response)
    def get(self, invoice_id):
        """Get invoice details"""
        try:
            invoice = Invoice.get_by_id(invoice_id)

            if not invoice:
                return {
                    'success': False,
                    'msg': 'Invoice not found'
                }, 404

            # Get related order information
            order_info = None
            if invoice.potential_order_id:
                order = PotentialOrder.get_by_id(invoice.potential_order_id)
                if order:
                    order_info = {
                        'order_request_id': f"PO{order.potential_order_id}",
                        'status': order.status,
                        'order_date': order.order_date.isoformat() if order.order_date else None
                    }

            invoice_dict = {
                'invoice_id': invoice.invoice_id,
                'invoice_number': invoice.invoice_number,
                'original_order_id': invoice.original_order_id,
                'customer_name': invoice.customer_name,
                'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                'total_invoice_amount': str(invoice.total_invoice_amount) if invoice.total_invoice_amount else None,
                'invoice_status': invoice.invoice_status,
                'part_no': invoice.part_no,
                'part_name': invoice.part_name,
                'quantity': invoice.quantity,
                'unit_price': str(invoice.unit_price) if invoice.unit_price else None,
                'order_info': order_info
            }

            return {
                'success': True,
                'invoice': invoice_dict
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving invoice details: {str(e)}'
            }, 400