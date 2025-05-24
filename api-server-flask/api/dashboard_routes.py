# -*- encoding: utf-8 -*-

from flask import request
from flask_restx import Resource, fields
from datetime import datetime, timedelta

from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer
from .routes import token_required, rest_api

# Response models
warehouse_model = rest_api.model('Warehouse', {
    'id': fields.Integer(description='Warehouse ID'),
    'name': fields.String(description='Warehouse name'),
    'location': fields.String(description='Warehouse location')
})

warehouses_response = rest_api.model('WarehousesResponse', {
    'success': fields.Boolean(description='Success status'),
    'warehouses': fields.List(fields.Nested(warehouse_model), description='List of warehouses')
})

company_model = rest_api.model('Company', {
    'id': fields.Integer(description='Company ID'),
    'name': fields.String(description='Company name')
})

companies_response = rest_api.model('CompaniesResponse', {
    'success': fields.Boolean(description='Success status'),
    'companies': fields.List(fields.Nested(company_model), description='List of companies')
})

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

state_history_model = rest_api.model('StateHistory', {
    'state_name': fields.String(description='State name'),
    'timestamp': fields.String(description='Timestamp of state change'),
    'user': fields.String(description='User who changed the state')
})

order_model = rest_api.model('Order', {
    'order_request_id': fields.String(description='Order request ID'),
    'original_order_id': fields.String(description='Original order ID'),
    'dealer_name': fields.String(description='Dealer name'),
    'order_date': fields.String(description='Order date'),
    'status': fields.String(description='Current status'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to': fields.String(description='User assigned to this order'),
    'products': fields.Integer(description='Number of products in this order'),
    'state_history': fields.List(fields.Nested(state_history_model))
})

orders_response = rest_api.model('OrdersResponse', {
    'success': fields.Boolean(description='Success status'),
    'orders': fields.List(fields.Nested(order_model), description='List of orders')
})

order_detail_response = rest_api.model('OrderDetailResponse', {
    'success': fields.Boolean(description='Success status'),
    'order': fields.Nested(order_model, description='Order details')
})

recent_order_model = rest_api.model('RecentOrder', {
    'order_request_id': fields.String(description='Order request ID'),
    'dealer_name': fields.String(description='Dealer name'),
    'status': fields.String(description='Current status'),
    'order_date': fields.String(description='Order date'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to': fields.String(description='User assigned to this order')
})

recent_orders_response = rest_api.model('RecentOrdersResponse', {
    'success': fields.Boolean(description='Success status'),
    'recent_orders': fields.List(fields.Nested(recent_order_model), description='List of recent orders')
})

error_response = rest_api.model('ErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Error message')
})


@rest_api.route('/api/warehouses')
class WarehouseList(Resource):
    """
    Endpoint for retrieving all warehouses
    """

    @rest_api.marshal_with(warehouses_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get list of all warehouses"""
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

    @rest_api.marshal_with(companies_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get list of all companies"""
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


@rest_api.route('/api/orders/status')
class OrderStatusCount(Resource):
    """
    Endpoint for retrieving order status counts for dashboard
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
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

            # Get counts for each status
            open_count = query.filter(PotentialOrder.status == 'Open').count()
            picking_count = query.filter(PotentialOrder.status == 'Picking').count()
            packing_count = query.filter(PotentialOrder.status == 'Packing').count()
            dispatch_count = query.filter(PotentialOrder.status == 'Dispatch Ready').count()

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
    Endpoint for retrieving orders filtered by status
    """

    @rest_api.doc(params={
        'status': 'Order status (open, picking, packing, dispatch)',
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID'
    })
    @rest_api.marshal_with(orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get orders filtered by status"""
        try:
            status = request.args.get('status', '')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            # Map frontend status names to database status names
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch': 'Dispatch Ready'
            }

            db_status = status_map.get(status.lower(), '') if status else ''

            # Base query for potential orders
            query = db.session.query(
                PotentialOrder,
                Dealer.name.label('dealer_name'),
                db.func.count(PotentialOrderProduct.potential_order_product_id).label('product_count')
            ).join(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id, isouter=True
            ).join(
                PotentialOrderProduct, PotentialOrder.potential_order_id == PotentialOrderProduct.potential_order_id,
                isouter=True
            )

            # Apply filters
            if db_status:
                query = query.filter(PotentialOrder.status == db_status)
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Group by order and dealer
            query = query.group_by(PotentialOrder.potential_order_id, Dealer.name)

            # Order by most recent first
            query = query.order_by(PotentialOrder.created_at.desc())

            # Get the results
            results = query.all()

            orders = []
            for potential_order, dealer_name, product_count in results:
                # Get state history for the order
                state_history = db.session.query(
                    OrderStateHistory, OrderState.state_name
                ).join(
                    OrderState, OrderStateHistory.state_id == OrderState.state_id
                ).filter(
                    OrderStateHistory.potential_order_id == potential_order.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at
                ).all()

                # Format state history
                formatted_history = []
                for history, state_name in state_history:
                    user = f"User {history.changed_by}"  # In a real app, you would get the actual username
                    formatted_history.append({
                        'state_name': state_name,
                        'timestamp': history.changed_at.isoformat(),
                        'user': user
                    })

                # Get the time of the most recent state change
                current_state_time = potential_order.updated_at
                if state_history:
                    current_state_time = state_history[-1][0].changed_at

                # Map database status to frontend status
                frontend_status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch'
                }
                frontend_status = frontend_status_map.get(potential_order.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name or 'Unknown Dealer',
                    'order_date': potential_order.order_date.isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",  # In a real app, get the actual username
                    'products': product_count,
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
    Endpoint for retrieving details of a specific order
    """

    @rest_api.marshal_with(order_detail_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get order details"""
        try:
            # Extract the numeric part from the order_id (e.g., "PO123" -> 123)
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else order_id

            # Get the order
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get dealer name
            dealer = Dealer.query.get(potential_order.dealer_id)
            dealer_name = dealer.name if dealer else 'Unknown Dealer'

            # Get product count
            product_count = PotentialOrderProduct.query.filter(
                PotentialOrderProduct.potential_order_id == potential_order.potential_order_id
            ).count()

            # Get state history
            state_history = db.session.query(
                OrderStateHistory, OrderState.state_name
            ).join(
                OrderState, OrderStateHistory.state_id == OrderState.state_id
            ).filter(
                OrderStateHistory.potential_order_id == potential_order.potential_order_id
            ).order_by(
                OrderStateHistory.changed_at
            ).all()

            # Format state history
            formatted_history = []
            for history, state_name in state_history:
                user = f"User {history.changed_by}"  # In a real app, you would get the actual username
                formatted_history.append({
                    'state_name': state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': user
                })

            # Get the time of the most recent state change
            current_state_time = potential_order.updated_at
            if state_history:
                current_state_time = state_history[-1][0].changed_at

            # Map database status to frontend status
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch'
            }
            status = status_map.get(potential_order.status, 'open')

            # Format the order
            order_data = {
                'order_request_id': f"PO{potential_order.potential_order_id}",
                'original_order_id': potential_order.original_order_id,
                'dealer_name': dealer_name,
                'order_date': potential_order.order_date.isoformat(),
                'status': status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to': f"User {potential_order.requested_by}",  # In a real app, get the actual username
                'products': product_count,
                'state_history': formatted_history
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


@rest_api.route('/api/orders/recent')
class RecentOrders(Resource):
    """
    Endpoint for retrieving recent order activity
    """

    @rest_api.doc(params={
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID',
        'limit': 'Maximum number of orders to return (default 10)'
    })
    @rest_api.marshal_with(recent_orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get recent order activity"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            limit = request.args.get('limit', 10, type=int)

            # Base query for potential orders
            query = db.session.query(
                PotentialOrder,
                Dealer.name.label('dealer_name'),
                db.func.count(PotentialOrderProduct.potential_order_product_id).label('product_count')
            ).join(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id, isouter=True
            ).join(
                PotentialOrderProduct, PotentialOrder.potential_order_id == PotentialOrderProduct.potential_order_id,
                isouter=True
            )

            # Apply filters if provided
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Group by order and dealer
            query = query.group_by(PotentialOrder.potential_order_id, Dealer.name)

            # Order by most recent first
            query = query.order_by(PotentialOrder.created_at.desc())

            # Limit the results
            query = query.limit(limit)

            # Get the results
            results = query.all()

            orders = []
            for potential_order, dealer_name, product_count in results:
                # Get the time of the most recent state change
                state_history = db.session.query(
                    OrderStateHistory
                ).filter(
                    OrderStateHistory.potential_order_id == potential_order.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at.desc()
                ).first()

                current_state_time = potential_order.updated_at
                if state_history:
                    current_state_time = state_history.changed_at

                # Map database status to frontend status
                status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch'
                }
                status = status_map.get(potential_order.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'dealer_name': dealer_name or 'Unknown Dealer',
                    'status': status,
                    'order_date': potential_order.order_date.isoformat(),
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",  # In a real app, get the actual username
                }
                orders.append(order_data)

            return {
                'success': True,
                'recent_orders': orders
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving recent orders: {str(e)}'
            }, 400


@rest_api.route('/api/orders/status')
class OrderStatusCount(Resource):
    """
    FIXED: Endpoint for retrieving order status counts including new states
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get counts of orders by status including completed and partially completed"""
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

            # Get counts for each status
            open_count = query.filter(PotentialOrder.status == 'Open').count()
            picking_count = query.filter(PotentialOrder.status == 'Picking').count()
            packing_count = query.filter(PotentialOrder.status == 'Packing').count()
            dispatch_count = query.filter(PotentialOrder.status == 'Dispatch Ready').count()
            completed_count = query.filter(PotentialOrder.status == 'Completed').count()
            partially_completed_count = query.filter(PotentialOrder.status == 'Partially Completed').count()

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
                    },
                    'completed': {
                        'count': completed_count,
                        'label': 'Completed'
                    },
                    'partially-completed': {
                        'count': partially_completed_count,
                        'label': 'Partially Completed'
                    }
                }
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order status counts: {str(e)}'
            }, 400


# Also update the OrdersList get method to handle new statuses
@rest_api.route('/api/orders')
class OrdersList(Resource):
    """
    FIXED: Endpoint for retrieving orders filtered by status including new states
    """

    @rest_api.doc(params={
        'status': 'Order status (open, picking, packing, dispatch, completed, partially-completed)',
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID'
    })
    @rest_api.marshal_with(orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get orders filtered by status including completed and partially completed"""
        try:
            status = request.args.get('status', '')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            # FIXED: Map frontend status names to database status names including new states
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch': 'Dispatch Ready',
                'completed': 'Completed',
                'partially-completed': 'Partially Completed'
            }

            db_status = status_map.get(status.lower(), '') if status else ''

            # Base query for potential orders
            query = db.session.query(
                PotentialOrder,
                Dealer.name.label('dealer_name'),
                db.func.count(PotentialOrderProduct.potential_order_product_id).label('product_count')
            ).join(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id, isouter=True
            ).join(
                PotentialOrderProduct, PotentialOrder.potential_order_id == PotentialOrderProduct.potential_order_id,
                isouter=True
            )

            # Apply filters
            if db_status:
                query = query.filter(PotentialOrder.status == db_status)
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Group by order and dealer
            query = query.group_by(PotentialOrder.potential_order_id, Dealer.name)

            # Order by most recent first
            query = query.order_by(PotentialOrder.created_at.desc())

            # Get the results
            results = query.all()

            orders = []
            for potential_order, dealer_name, product_count in results:
                # Get state history for the order
                state_history = db.session.query(
                    OrderStateHistory, OrderState.state_name
                ).join(
                    OrderState, OrderStateHistory.state_id == OrderState.state_id
                ).filter(
                    OrderStateHistory.potential_order_id == potential_order.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at
                ).all()

                # Format state history
                formatted_history = []
                for history, state_name in state_history:
                    user = f"User {history.changed_by}"
                    formatted_history.append({
                        'state_name': state_name,
                        'timestamp': history.changed_at.isoformat(),
                        'user': user
                    })

                # Get the time of the most recent state change
                current_state_time = potential_order.updated_at
                if state_history:
                    current_state_time = state_history[-1][0].changed_at

                # FIXED: Map database status to frontend status including new states
                frontend_status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                frontend_status = frontend_status_map.get(potential_order.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name or 'Unknown Dealer',
                    'order_date': potential_order.order_date.isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",
                    'products': product_count,
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