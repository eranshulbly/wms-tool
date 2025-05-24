# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from datetime import datetime, timezone, timedelta

import werkzeug
from .services import order_service

from functools import wraps

from flask import request
from flask_restx import Api, Resource, fields,reqparse
import jwt
from .config import BaseConfig
import requests
from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer, Box, Order, OrderProduct, OrderBox, BoxProduct,Users, JWTTokenBlocklist

rest_api = Api(version="1.0", title="Users API")


"""
    Flask-Restx models for api request and response data
"""

signup_model = rest_api.model('SignUpModel', {"username": fields.String(required=True, min_length=2, max_length=32),
                                              "email": fields.String(required=True, min_length=4, max_length=64),
                                              "password": fields.String(required=True, min_length=4, max_length=16)
                                              })

login_model = rest_api.model('LoginModel', {"email": fields.String(required=True, min_length=4, max_length=64),
                                            "password": fields.String(required=True, min_length=4, max_length=16)
                                            })

user_edit_model = rest_api.model('UserEditModel', {"userID": fields.String(required=True, min_length=1, max_length=32),
                                                   "username": fields.String(required=True, min_length=2, max_length=32),
                                                   "email": fields.String(required=True, min_length=4, max_length=64)
                                                   })
"""
   Upload Management Routes
"""
# Define the request parser for file upload
upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file',
                           type=werkzeug.datastructures.FileStorage,
                           location='files',
                           required=True,
                           help='Excel/CSV file with order data')
upload_parser.add_argument('warehouse_id',
                           type=int,
                           location='form',  # Add this line
                           required=True,
                           help='Warehouse ID must be provided')
upload_parser.add_argument('company_id',
                           type=int,
                           location='form',  # Add this line
                           required=True,
                           help='Company ID must be provided')

# Response model for order upload
order_upload_response = rest_api.model('OrderUploadResponse', {
    'success': fields.Boolean(description='Success status of upload'),
    'msg': fields.String(description='Message describing the result'),
    'orders_processed': fields.Integer(description='Number of orders processed'),
    'products_processed': fields.Integer(description='Number of products processed'),
    'errors': fields.List(fields.String, description='List of errors encountered')
})

"""
   Order Management Routes
"""

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

order_detail_response = rest_api.model('OrderDetailResponse', {
    'success': fields.Boolean(description='Success status'),
    'order': fields.Nested(order_detail_model, description='Order details')
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

# Response models
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

            token_expired = db.session.query(JWTTokenBlocklist.id).filter_by(jwt_token=token).scalar()

            if token_expired is not None:
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

        # if not user_exists:
        #     return {"success": False,
        #             "msg": "This email does not exist."}, 400

        # if not user_exists.check_password(_password):
        #     return {"success": False,
        #             "msg": "Wrong credentials."}, 400

        # create access token uwing JWT
        # token = jwt.encode({'email': _email, 'exp': datetime.utcnow() + timedelta(minutes=30)}, BaseConfig.SECRET_KEY)
        token = "eyJhbGciOiAiSFMyNTYiLCJraWQiOiAiYXBpY2VydC1rZXkiLCAidHlwIjogIkpXVCJ9.eyJleHBpcnkiOiAiMjAyNS0wMS0wNVQxMjozMjo1Ni4wMDBaIiwibmFtZSI6ICJqb2huZG9lIiwic3ViIjogIjEyMzQ1Njc4OSIsImlhdCI6IDE2MjcwNTkzMDAwMDB9.Ojw8sFv84H4t7Z54lJtneEEHLy8MhG8g8Xy0jHk7uhtTYq0EFU0OOf_mDQ5yM6yyjrQPSGcBQwLX5hqp36-PmHjyfg"

        user_exists.set_jwt_auth_active(True)
        user_exists.save()

        return {"success": True,
                "token": token,
                "user": user_exists.toJSON()}, 200


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
            self.update_username(_new_username)

        if _new_email:
            self.update_email(_new_email)

        self.save()

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

        self.set_jwt_auth_active(False)
        self.save()

        return {"success": True}, 200


@rest_api.route('/api/warehouses')
class WarehouseList(Resource):
    """
    Endpoint for retrieving all warehouses
    """

    def get(self):
        """
        Get list of all warehouses
        """
        try:
            warehouses = Warehouse.query.all()
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
    Endpoint for retrieving all companies
    """

    def get(self):
        """
        Get list of all companies
        """
        try:
            companies = Company.query.all()
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
    Handles the upload of Excel/CSV files containing order data
    """

    @rest_api.expect(upload_parser)
    @rest_api.response(200, 'Success', order_upload_response)
    @rest_api.response(400, 'Bad Request', order_upload_response)
    def post(self):
        # Parse the request arguments
        args = upload_parser.parse_args()
        uploaded_file = args['file']
        warehouse_id = args['warehouse_id']
        company_id = args['company_id']

        # Call the service layer to process the upload
        result, status_code = order_service.process_order_upload(
            uploaded_file,
            warehouse_id,
            company_id,
            123
        )

        return result, status_code


"""
   Order Management Route Starts
"""

@rest_api.route('/api/orders/<string:order_id>/details')
class OrderDetailWithProducts(Resource):
    """
    Get detailed order information with proper timeline and status
    """

    @rest_api.response(200, 'Success')
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get detailed order information with correct timeline"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get dealer name
            dealer = Dealer.query.get(potential_order.dealer_id)
            dealer_name = dealer.name if dealer else 'Unknown Dealer'

            # Get products for this order
            products = []
            order_products = db.session.query(PotentialOrderProduct, Product).join(
                Product, PotentialOrderProduct.product_id == Product.product_id
            ).filter(
                PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
            ).all()

            for order_product, product in order_products:
                products.append({
                    'product_id': product.product_id,
                    'product_string': product.product_string or f'P{product.product_id}',
                    'name': product.name,
                    'description': product.description or '',
                    'quantity_ordered': order_product.quantity,
                    'quantity_available': order_product.quantity,
                    'quantity_packed': order_product.quantity_packed or 0,
                    'price': str(product.price) if product.price else '0.00'
                })

            # Get existing box assignments
            boxes = []
            box_products = db.session.query(BoxProduct, Box).join(
                Box, BoxProduct.box_id == Box.box_id
            ).filter(
                BoxProduct.potential_order_id == potential_order.potential_order_id
            ).all()

            # Group products by box
            box_dict = {}
            for box_product, box in box_products:
                if box.box_id not in box_dict:
                    box_dict[box.box_id] = {
                        'box_id': f'B{box.box_id}',
                        'box_name': box.name,
                        'products': []
                    }

                product = Product.query.get(box_product.product_id)
                if product:
                    box_dict[box.box_id]['products'].append({
                        'product_id': product.product_id,
                        'quantity': box_product.quantity
                    })

            boxes = list(box_dict.values())

            # Get complete state history
            state_history = db.session.query(
                OrderStateHistory, OrderState
            ).join(
                OrderState, OrderStateHistory.state_id == OrderState.state_id
            ).filter(
                OrderStateHistory.potential_order_id == potential_order.potential_order_id
            ).order_by(
                OrderStateHistory.changed_at
            ).all()

            formatted_history = []
            for history, state in state_history:
                username = f"User {history.changed_by}"
                formatted_history.append({
                    'state_name': state.state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': username
                })

            # Get current state time
            current_state_time = potential_order.updated_at
            if formatted_history:
                current_state_time = formatted_history[-1]['timestamp']

            # Status mapping for frontend
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed',
                'Partially Completed': 'partially-completed'
            }
            frontend_status = status_map.get(potential_order.status, 'open')

            # Check for corresponding final order
            final_order = Order.query.filter_by(potential_order_id=potential_order.potential_order_id).first()
            final_order_info = None
            if final_order:
                final_order_info = {
                    'order_number': final_order.order_number,
                    'status': final_order.status,
                    'created_at': final_order.created_at.isoformat(),
                    'dispatched_date': final_order.dispatched_date.isoformat() if final_order.dispatched_date else None
                }

            # Format order data
            order_data = {
                'order_request_id': f"PO{potential_order.potential_order_id}",
                'original_order_id': potential_order.original_order_id,
                'dealer_name': dealer_name,
                'order_date': potential_order.order_date.isoformat(),
                'status': frontend_status,
                'current_state_time': current_state_time,
                'assigned_to': f"User {potential_order.requested_by}",
                'products': products,
                'boxes': boxes,
                'state_history': formatted_history,
                'final_order': final_order_info
            }

            return {
                'success': True,
                'order': order_data
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order details: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/status')
class OrderStatusUpdate(Resource):
    """
    Regular Status Updates (Open -> Picking -> Packing only)
    """

    @rest_api.expect(fields.Raw)
    @rest_api.response(200, 'Success')
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Update order status for regular transitions"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            req_data = request.get_json()
            new_status = req_data.get('new_status')

            # Status mapping for regular transitions only
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing'
            }

            if new_status not in status_map:
                return {
                    'success': False,
                    'msg': f'Invalid status: {new_status}. Use specific endpoints for dispatch ready/completed.'
                }, 400

            db_status = status_map[new_status]

            # Validate status progression
            valid_transitions = {
                'Open': ['Picking'],
                'Picking': ['Packing'],
                'Packing': []  # Packing should use dispatch-ready endpoint
            }

            current_status = potential_order.status
            if current_status in valid_transitions and db_status not in valid_transitions[current_status]:
                return {
                    'success': False,
                    'msg': f'Invalid status transition from {current_status} to {db_status}'
                }, 400

            # Get or create the state
            new_state = OrderState.query.filter_by(state_name=db_status).first()
            if not new_state:
                new_state = OrderState(state_name=db_status, description=f'{db_status} state')
                db.session.add(new_state)
                db.session.flush()

            # Update order status
            current_time = datetime.utcnow()
            potential_order.status = db_status
            potential_order.updated_at = current_time

            # Add state history
            state_history = OrderStateHistory(
                potential_order_id=potential_order.potential_order_id,
                state_id=new_state.state_id,
                changed_by=1,
                changed_at=current_time
            )
            db.session.add(state_history)

            db.session.commit()

            return {
                'success': True,
                'msg': f'Order status updated to {new_status}'
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'success': False,
                'msg': f'Error updating order status: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/packing')
class OrderPackingUpdate(Resource):
    """
    Endpoint for updating packing information with improved box quantity handling
    """

    @rest_api.expect(packing_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Update packing information for an order with partial quantities"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            req_data = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data = req_data.get('boxes', [])

            # Validate that order is in packing status
            if potential_order.status != 'Packing':
                return {
                    'success': False,
                    'msg': 'Order must be in Packing status to update packing information'
                }, 400

            # Clear existing box-product assignments for this order
            BoxProduct.query.filter_by(potential_order_id=potential_order.potential_order_id).delete()

            # Process boxes and their product assignments
            for box_data in boxes_data:
                box_name = box_data.get('box_name')
                box_products = box_data.get('products', [])

                # Create or get box
                box = Box(
                    name=box_name,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(box)
                db.session.flush()

                # Add products to this box with quantities
                for product_assignment in box_products:
                    product_id = product_assignment.get('product_id')
                    quantity = product_assignment.get('quantity', 0)

                    if quantity > 0:
                        box_product = BoxProduct(
                            box_id=box.box_id,
                            product_id=product_id,
                            quantity=quantity,
                            potential_order_id=potential_order.potential_order_id,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.session.add(box_product)

            # Update packed quantities in potential order products
            for product_data in products_data:
                product_id = product_data.get('product_id')
                quantity_packed = product_data.get('quantity_packed', 0)

                potential_product = PotentialOrderProduct.query.filter(
                    PotentialOrderProduct.potential_order_id == potential_order.potential_order_id,
                    PotentialOrderProduct.product_id == product_id
                ).first()

                if potential_product:
                    potential_product.quantity_packed = quantity_packed
                    potential_product.updated_at = datetime.utcnow()

            # Update the order timestamp
            potential_order.updated_at = datetime.utcnow()
            db.session.commit()

            return {
                'success': True,
                'msg': 'Packing information updated successfully'
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'success': False,
                'msg': f'Error updating packing information: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/dispatch')
class OrderDispatchFinal(Resource):
    """
    FIXED: Endpoint for finalizing order and moving to dispatch - fixed status counting
    """

    @rest_api.expect(dispatch_update_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Finalize order and create final order record"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            req_data = request.get_json()
            products_data = req_data.get('products', [])
            boxes_data = req_data.get('boxes', [])

            # Validate that order is in packing status
            if potential_order.status != 'Packing':
                return {
                    'success': False,
                    'msg': 'Order must be in Packing status to dispatch'
                }, 400

            # Start transaction
            try:
                # Create final order
                final_order = Order(
                    potential_order_id=potential_order.potential_order_id,
                    order_number=f"ORD-{potential_order.potential_order_id}-{datetime.now().strftime('%Y%m%d')}",
                    status='In Transit',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(final_order)
                db.session.flush()

                # Process products and create final order products
                total_dispatched_products = 0
                for product_data in products_data:
                    product_id = product_data.get('product_id')
                    quantity_packed = product_data.get('quantity_packed', 0)

                    if quantity_packed > 0:
                        # Get the original potential order product
                        potential_product = PotentialOrderProduct.query.filter(
                            PotentialOrderProduct.potential_order_id == potential_order.potential_order_id,
                            PotentialOrderProduct.product_id == product_id
                        ).first()

                        if potential_product:
                            # Create final order product
                            order_product = OrderProduct(
                                order_id=final_order.order_id,
                                product_id=product_id,
                                quantity=quantity_packed,
                                mrp=potential_product.mrp,
                                total_price=potential_product.mrp * quantity_packed if potential_product.mrp else None,
                                created_at=datetime.utcnow(),
                                updated_at=datetime.utcnow()
                            )
                            db.session.add(order_product)
                            total_dispatched_products += 1

                            # Update potential order product quantity (reduce by packed amount)
                            remaining_quantity = potential_product.quantity - quantity_packed
                            if remaining_quantity <= 0:
                                # Remove the potential order product if fully packed
                                db.session.delete(potential_product)
                            else:
                                # Update with remaining quantity
                                potential_product.quantity = remaining_quantity
                                potential_product.quantity_packed = 0  # Reset packed quantity
                                potential_product.updated_at = datetime.utcnow()

                # Process boxes for final order
                for box_data in boxes_data:
                    box_name = box_data.get('box_name')

                    # Create final order box
                    order_box = OrderBox(
                        order_id=final_order.order_id,
                        name=box_name,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.session.add(order_box)

                # Check if any products remain in potential order
                remaining_products = PotentialOrderProduct.query.filter(
                    PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
                ).count()

                # FIXED: Update status correctly for dashboard counting
                if remaining_products == 0:
                    # All products were dispatched, mark potential order as completed
                    potential_order.status = 'Completed'
                    final_status = 'Completed'
                else:
                    # Some products remain, mark as partially completed
                    potential_order.status = 'Partially Completed'
                    final_status = 'Partially Completed'

                # Update potential order
                potential_order.updated_at = datetime.utcnow()

                # Create state history for the final status (not dispatch ready)
                final_state = OrderState.query.filter_by(state_name=final_status).first()
                if not final_state:
                    final_state = OrderState(state_name=final_status, description=f'{final_status} state')
                    db.session.add(final_state)
                    db.session.flush()

                state_history = OrderStateHistory(
                    potential_order_id=potential_order.potential_order_id,
                    state_id=final_state.state_id,
                    changed_by=1,  # In real app, use authenticated user ID
                    changed_at=datetime.utcnow()
                )
                db.session.add(state_history)

                db.session.commit()

                return {
                    'success': True,
                    'msg': f'Order dispatched successfully. Order number: {final_order.order_number}',
                    'final_order_id': final_order.order_id,
                    'products_dispatched': total_dispatched_products,
                    'remaining_products': remaining_products,
                    'final_status': final_status.lower().replace(' ', '-')
                }, 200

            except Exception as e:
                db.session.rollback()
                raise e

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error dispatching order: {str(e)}'
            }, 400

@rest_api.route('/api/orders/<string:order_id>/move-to-dispatch-ready')
class MoveToDispatchReady(Resource):
    """
    Move from Packing to Dispatch Ready - Create Final Order Records
    """

    @rest_api.expect(move_to_dispatch_model)
    @rest_api.response(200, 'Success', move_to_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Move order from packing to dispatch ready and create final order records"""
        try:
            # Extract numeric ID
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

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

            # Start transaction
            try:
                current_time = datetime.utcnow()

                # STEP 1: CREATE FINAL ORDER RECORD
                final_order = Order(
                    potential_order_id=potential_order.potential_order_id,
                    order_number=f"ORD-{potential_order.potential_order_id}-{current_time.strftime('%Y%m%d%H%M')}",
                    status='Dispatch Ready',
                    created_at=current_time,
                    updated_at=current_time
                )
                db.session.add(final_order)
                db.session.flush()

                # STEP 2: PROCESS EACH PRODUCT
                total_packed = 0
                total_remaining = 0
                has_remaining_items = False

                for product_data in products_data:
                    product_id = product_data.get('product_id')
                    quantity_packed = int(product_data.get('quantity_packed', 0))

                    if quantity_packed > 0:
                        # Get the original potential order product
                        potential_product = PotentialOrderProduct.query.filter(
                            PotentialOrderProduct.potential_order_id == potential_order.potential_order_id,
                            PotentialOrderProduct.product_id == product_id
                        ).first()

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
                            db.session.add(order_product)
                            total_packed += quantity_packed

                            # HANDLE REMAINING QUANTITY
                            if quantity_remaining > 0:
                                # Update potential order product with remaining quantity
                                potential_product.quantity = quantity_remaining
                                potential_product.quantity_packed = 0
                                potential_product.updated_at = current_time
                                has_remaining_items = True
                                total_remaining += quantity_remaining
                            else:
                                # Remove the potential order product if fully packed
                                db.session.delete(potential_product)

                # STEP 3: CREATE ORDER BOXES
                for box_data in boxes_data:
                    if box_data.get('products') and len(box_data.get('products', [])) > 0:
                        order_box = OrderBox(
                            order_id=final_order.order_id,
                            name=box_data.get('box_name', 'Box'),
                            created_at=current_time,
                            updated_at=current_time
                        )
                        db.session.add(order_box)

                # STEP 4: UPDATE POTENTIAL ORDER STATUS
                if has_remaining_items:
                    potential_order.status = 'Partially Completed'
                    final_status_name = 'Partially Completed'
                else:
                    potential_order.status = 'Dispatch Ready'
                    final_status_name = 'Dispatch Ready'

                potential_order.updated_at = current_time

                # STEP 5: CREATE STATE HISTORY
                # Ensure states exist
                dispatch_ready_state = OrderState.query.filter_by(state_name='Dispatch Ready').first()
                if not dispatch_ready_state:
                    dispatch_ready_state = OrderState(
                        state_name='Dispatch Ready',
                        description='Order ready for dispatch'
                    )
                    db.session.add(dispatch_ready_state)
                    db.session.flush()

                # Add dispatch ready state history
                dispatch_history = OrderStateHistory(
                    potential_order_id=potential_order.potential_order_id,
                    state_id=dispatch_ready_state.state_id,
                    changed_by=1,
                    changed_at=current_time
                )
                db.session.add(dispatch_history)

                # If partial completion, add that state too
                if has_remaining_items:
                    partial_state = OrderState.query.filter_by(state_name='Partially Completed').first()
                    if not partial_state:
                        partial_state = OrderState(
                            state_name='Partially Completed',
                            description='Order partially completed with remaining items'
                        )
                        db.session.add(partial_state)
                        db.session.flush()

                    partial_history = OrderStateHistory(
                        potential_order_id=potential_order.potential_order_id,
                        state_id=partial_state.state_id,
                        changed_by=1,
                        changed_at=current_time
                    )
                    db.session.add(partial_history)

                # Commit all changes
                db.session.commit()

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
                db.session.rollback()
                raise e

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error moving to dispatch ready: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>/complete-dispatch')
class CompleteDispatch(Resource):
    """
    Complete Dispatch - Mark final order as completed (dispatched from warehouse)
    """

    @rest_api.response(200, 'Success', complete_dispatch_response)
    @rest_api.response(400, 'Error', error_response)
    def post(self, order_id):
        """Mark order as completed (dispatched from warehouse)"""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Find the corresponding final order
            final_order = Order.query.filter_by(potential_order_id=potential_order.potential_order_id).first()

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

            # Create completed state if it doesn't exist
            completed_state = OrderState.query.filter_by(state_name='Completed').first()
            if not completed_state:
                completed_state = OrderState(
                    state_name='Completed',
                    description='Order completed and dispatched'
                )
                db.session.add(completed_state)
                db.session.flush()

            # Add completion state history
            completion_history = OrderStateHistory(
                potential_order_id=potential_order.potential_order_id,
                state_id=completed_state.state_id,
                changed_by=1,
                changed_at=current_time
            )
            db.session.add(completion_history)

            # Update potential order if it's still in "Dispatch Ready"
            if potential_order.status == 'Dispatch Ready':
                potential_order.status = 'Completed'
                potential_order.updated_at = current_time

            db.session.commit()

            return {
                'success': True,
                'msg': 'Order dispatched successfully',
                'final_order_number': final_order.order_number,
                'dispatched_date': final_order.dispatched_date.isoformat()
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'success': False,
                'msg': f'Error completing dispatch: {str(e)}'
            }, 400