# -*- encoding: utf-8 -*-
"""
Order Management API routes
"""

from flask import request
from flask_restx import Resource, fields

from datetime import datetime, timedelta

from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer, Box, Order, OrderProduct, OrderBox
from .routes import token_required, rest_api

# Response models for order management
status_count_model = rest_api.model('StatusCount', {
    'count': fields.Integer(description='Number of orders with this status'),
    'label': fields.String(description='Label for the status')
})

status_counts_model = rest_api.model('StatusCounts', {
    'open': fields.Nested(status_count_model),
    'picking': fields.Nested(status_count_model),
    'packing': fields.Nested(status_count_model),
    'dispatch': fields.Nested(status_count_model)
})

status_response = rest_api.model('StatusResponse', {
    'success': fields.Boolean(description='Success status'),
    'status_counts': fields.Nested(status_counts_model, description='Order status counts')
})

error_response = rest_api.model('ErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Error message')
})

state_history_model = rest_api.model('StateHistory', {
    'state_name': fields.String(description='State name'),
    'timestamp': fields.String(description='Timestamp of state change'),
    'user': fields.String(description='User who changed the state')
})

product_model = rest_api.model('Product', {
    'product_id': fields.String(description='Product ID'),
    'name': fields.String(description='Product name'),
    'description': fields.String(description='Product description'),
    'quantity': fields.Integer(description='Quantity'),
    'assigned_to_box': fields.String(description='Box assignment, if any')
})

box_model = rest_api.model('Box', {
    'box_id': fields.String(description='Box ID'),
    'name': fields.String(description='Box name'),
    'products': fields.List(fields.String, description='List of product IDs in this box')
})

order_model = rest_api.model('Order', {
    'order_request_id': fields.String(description='Order request ID'),
    'original_order_id': fields.String(description='Original order ID'),
    'dealer_name': fields.String(description='Dealer name'),
    'order_date': fields.String(description='Order date'),
    'status': fields.String(description='Current status'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to': fields.String(description='User assigned to this order'),
    'products': fields.List(fields.Nested(product_model), description='Products in this order'),
    'boxes': fields.List(fields.Nested(box_model), description='Boxes for this order'),
    'state_history': fields.List(fields.Nested(state_history_model), description='State history')
})

orders_response = rest_api.model('OrdersResponse', {
    'success': fields.Boolean(description='Success status'),
    'orders': fields.List(fields.Nested(order_model), description='List of orders')
})

update_status_model = rest_api.model('UpdateStatusModel', {
    'new_status': fields.String(required=True, description='New status'),
    'boxes': fields.List(fields.Nested(box_model), description='Box assignments (required for packing to dispatch)')
})

update_status_response = rest_api.model('UpdateStatusResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Result message'),
    'order': fields.Nested(order_model, description='Updated order')
})


@rest_api.route('/api/orders/status-counts')
class OrderStatusCount(Resource):
    """
    Endpoint for retrieving order status counts for dashboard
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.response(200, 'Success', status_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get counts of orders by status"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            # Base query for potential orders
            query = PotentialOrder.query

            # Apply filters if provided
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Map frontend status names to database status names
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch': 'Dispatch Ready'
            }

            # Get counts for each status
            open_count = query.filter(PotentialOrder.status == status_map['open']).count()
            picking_count = query.filter(PotentialOrder.status == status_map['picking']).count()
            packing_count = query.filter(PotentialOrder.status == status_map['packing']).count()
            dispatch_count = query.filter(PotentialOrder.status == status_map['dispatch']).count()

            return {
                'success': True,
                'status_counts': {
                    'open': {
                        'count': open_count,
                        'label': 'Open Orders'
                    },
                    'picking': {
                        'count': picking_count,
                        'label': 'Picking'
                    },
                    'packing': {
                        'count': packing_count,
                        'label': 'Packing'
                    },
                    'dispatch': {
                        'count': dispatch_count,
                        'label': 'Dispatch Ready'
                    }
                }
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order status counts: {str(e)}'
            }, 400


@rest_api.route('/api/orders')
class OrdersList(Resource):
    """
    Endpoint for retrieving orders with optional filtering
    """

    @rest_api.doc(params={
        'status': 'Order status (open, picking, packing, dispatch, all)',
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID'
    })
    @rest_api.response(200, 'Success', orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get orders with optional filtering"""
        try:
            status = request.args.get('status', 'all')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            # Map frontend status names to database status names
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch': 'Dispatch Ready'
            }

            # Base query for potential orders
            query = db.session.query(
                PotentialOrder,
                Dealer.name.label('dealer_name')
            ).join(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id, isouter=True
            )

            # Apply filters
            if status != 'all':
                query = query.filter(PotentialOrder.status == status_map.get(status))
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Get results
            results = query.all()

            orders = []
            for potential_order, dealer_name in results:
                # Get products for this order
                products = []
                order_products = PotentialOrderProduct.query.filter(
                    PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
                ).all()

                for order_product in order_products:
                    product = Product.query.get(order_product.product_id)
                    if product:
                        products.append({
                            'product_id': product.product_string or f'P{product.product_id}',
                            'name': product.name,
                            'description': product.description or '',
                            'quantity': order_product.quantity,
                            'assigned_to_box': None  # Will be populated if boxes exist
                        })

                # Get boxes and assignments (if status is packing or dispatch)
                boxes = []
                if potential_order.status in ['Packing', 'Dispatch Ready']:
                    # In a real implementation, you would get boxes from your database
                    # For now, we'll create a default box if none exists
                    box = Box.query.filter_by(name=f'Box-{potential_order.potential_order_id}').first()

                    if not box:
                        box = Box(
                            name=f'Box-{potential_order.potential_order_id}',
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.session.add(box)
                        db.session.commit()

                    boxes.append({
                        'box_id': f'B{box.box_id}',
                        'name': box.name,
                        'products': [p['product_id'] for p in products]  # Assign all products to this box
                    })

                    # Update product assignments
                    for product in products:
                        product['assigned_to_box'] = f'B{box.box_id}'

                # Get state history
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
                    username = f"User {history.changed_by}"  # In a real app, get actual username
                    formatted_history.append({
                        'state_name': state.state_name,
                        'timestamp': history.changed_at.isoformat(),
                        'user': username
                    })

                # Get current state time
                current_state_time = potential_order.updated_at
                if formatted_history:
                    # Use the time of the most recent state change
                    current_state_time = datetime.fromisoformat(
                        formatted_history[-1]['timestamp'].replace('Z', '+00:00'))

                # Map database status to frontend status
                status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch'
                }
                frontend_status = status_map.get(potential_order.status, 'open')

                # Format order data
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name or 'Unknown Dealer',
                    'order_date': potential_order.order_date.isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",  # In a real app, get actual username
                    'products': products,
                    'boxes': boxes,
                    'state_history': formatted_history
                }
                orders.append(order_data)

            return {
                'success': True,
                'orders': orders
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving orders: {str(e)}'
            }, 400


@rest_api.route('/api/orders/<string:order_id>')
class OrderDetail(Resource):
    """
    Endpoint for retrieving details of a specific order and updating its status
    """

    @rest_api.response(200, 'Success', orders_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get detailed information for a specific order"""
        try:
            # Extract the numeric part from the order_id (e.g., "PO123" -> 123)
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get the order
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get dealer name
            dealer = Dealer.query.get(potential_order.dealer_id)
            dealer_name = dealer.name if dealer else 'Unknown Dealer'

            # Get products for this order
            products = []
            order_products = PotentialOrderProduct.query.filter(
                PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
            ).all()

            for order_product in order_products:
                product = Product.query.get(order_product.product_id)
                if product:
                    products.append({
                        'product_id': product.product_string or f'P{product.product_id}',
                        'name': product.name,
                        'description': product.description or '',
                        'quantity': order_product.quantity,
                        'assigned_to_box': None  # Will be populated if boxes exist
                    })

            # Get boxes and assignments (if status is packing or dispatch)
            boxes = []
            if potential_order.status in ['Packing', 'Dispatch Ready']:
                # In a real implementation, you would get boxes from your database
                # For now, we'll create a default box if none exists
                box = Box.query.filter_by(name=f'Box-{potential_order.potential_order_id}').first()

                if not box:
                    box = Box(
                        name=f'Box-{potential_order.potential_order_id}',
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.session.add(box)
                    db.session.commit()

                boxes.append({
                    'box_id': f'B{box.box_id}',
                    'name': box.name,
                    'products': [p['product_id'] for p in products]  # Assign all products to this box
                })

                # Update product assignments
                for product in products:
                    product['assigned_to_box'] = f'B{box.box_id}'

            # Get state history
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
                username = f"User {history.changed_by}"  # In a real app, get actual username
                formatted_history.append({
                    'state_name': state.state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': username
                })

            # Get current state time
            current_state_time = potential_order.updated_at
            if formatted_history:
                # Use the time of the most recent state change
                current_state_time = datetime.fromisoformat(formatted_history[-1]['timestamp'].replace('Z', '+00:00'))

            # Map database status to frontend status
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch'
            }
            frontend_status = status_map.get(potential_order.status, 'open')

            # Format order data
            order_data = {
                'order_request_id': f"PO{potential_order.potential_order_id}",
                'original_order_id': potential_order.original_order_id,
                'dealer_name': dealer_name,
                'order_date': potential_order.order_date.isoformat(),
                'status': frontend_status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to': f"User {potential_order.requested_by}",  # In a real app, get actual username
                'products': products,
                'boxes': boxes,
                'state_history': formatted_history
            }

            return {
                'success': True,
                'orders': [order_data]  # Return as a list for consistency with other endpoints
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order details: {str(e)}'
            }, 400

    @rest_api.expect(update_status_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def post(self, order_id):
        """Update the status of an order"""
        try:
            # Extract the numeric part from the order_id (e.g., "PO123" -> 123)
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get the order
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get request data
            req_data = request.get_json()
            new_status = req_data.get('new_status')
            boxes_data = req_data.get('boxes', [])

            # Map frontend status names to database status names
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch': 'Dispatch Ready'
            }

            # Validate the new status
            if new_status not in status_map:
                return {
                    'success': False,
                    'msg': f'Invalid status: {new_status}'
                }, 400

            # Get the corresponding state
            db_status = status_map[new_status]
            new_state = OrderState.query.filter_by(state_name=db_status).first()

            if not new_state:
                # Create the state if it doesn't exist
                new_state = OrderState(state_name=db_status, description=f'{db_status} state')
                db.session.add(new_state)
                db.session.flush()

            # Special handling for packing to dispatch transition
            if potential_order.status == 'Packing' and db_status == 'Dispatch Ready':
                if not boxes_data:
                    return {
                        'success': False,
                        'msg': 'Box assignments required for transition to Dispatch Ready'
                    }, 400

                # Process the box assignments
                for box_data in boxes_data:
                    box_id = box_data.get('box_id')
                    box_name = box_data.get('name')
                    product_ids = box_data.get('products', [])

                    # Validate that all products are assigned
                    products_in_order = PotentialOrderProduct.query.filter(
                        PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
                    ).all()

                    product_id_strings = []
                    for op in products_in_order:
                        product = Product.query.get(op.product_id)
                        if product:
                            product_id_strings.append(product.product_string or f'P{product.product_id}')

                    # Check if all products are assigned to a box
                    if not all(p_id in product_ids for p_id in product_id_strings):
                        return {
                            'success': False,
                            'msg': 'All products must be assigned to a box'
                        }, 400

                    # Create or update the box
                    numeric_box_id = int(box_id.replace('B', '')) if box_id.startswith('B') else None
                    box = None

                    if numeric_box_id:
                        box = Box.query.get(numeric_box_id)

                    if not box:
                        box = Box(
                            name=box_name,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        db.session.add(box)
                        db.session.flush()

            # Update the order status
            potential_order.status = db_status
            potential_order.updated_at = datetime.utcnow()

            # Create a state history entry
            state_history = OrderStateHistory(
                potential_order_id=potential_order.potential_order_id,
                state_id=new_state.state_id,
                changed_by=1,  # In a real app, use the authenticated user's ID
                changed_at=datetime.utcnow()
            )
            db.session.add(state_history)

            # Commit the changes
            db.session.commit()

            # Return the updated order details
            return {
                'success': True,
                'msg': f'Order status updated to {new_status}',
                'order': {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'status': new_status
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            return {
                'success': False,
                'msg': f'Error updating order status: {str(e)}'
            }, 400