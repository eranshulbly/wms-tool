# -*- encoding: utf-8 -*-

from flask import request
from flask_restx import Resource, fields
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_

from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer
from .routes import token_required, rest_api

# Response models (same as before, but optimized for MySQL)
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
    'dispatch-ready': fields.Nested(status_count_model),
    'completed': fields.Nested(status_count_model),
    'partially-completed': fields.Nested(status_count_model)
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
    Endpoint for retrieving all warehouses - MySQL optimized
    """

    @rest_api.marshal_with(warehouses_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get list of all warehouses"""
        try:
            # Use MySQL-optimized query with explicit column selection
            warehouses = db.session.query(
                Warehouse.warehouse_id,
                Warehouse.name,
                Warehouse.location
            ).all()

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
    Endpoint for retrieving all companies - MySQL optimized
    """

    @rest_api.marshal_with(companies_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get list of all companies"""
        try:
            # Use MySQL-optimized query with explicit column selection
            companies = db.session.query(
                Company.company_id,
                Company.name
            ).all()

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


@rest_api.route('/api`/orders/status`')
class OrderStatusCount(Resource):
    """
    MySQL Optimized: Endpoint for retrieving order status counts
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get counts of orders by status - MySQL optimized with single query"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            # Build base query with filters
            base_query = db.session.query(PotentialOrder.status, func.count(PotentialOrder.potential_order_id))

            # Apply filters if provided
            if warehouse_id:
                base_query = base_query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                base_query = base_query.filter(PotentialOrder.company_id == company_id)

            # Group by status and get counts in a single query
            status_counts = base_query.group_by(PotentialOrder.status).all()

            # Convert to dictionary
            counts_dict = {status: count for status, count in status_counts}

            # Prepare response with all possible statuses
            response_data = {
                'open': {
                    'count': counts_dict.get('Open', 0),
                    'label': 'Open Orders'
                },
                'picking': {
                    'count': counts_dict.get('Picking', 0),
                    'label': 'Picking'
                },
                'packing': {
                    'count': counts_dict.get('Packing', 0),
                    'label': 'Packing'
                },
                'dispatch-ready': {
                    'count': counts_dict.get('Dispatch Ready', 0),
                    'label': 'Dispatch Ready'
                },
                'completed': {
                    'count': counts_dict.get('Completed', 0),
                    'label': 'Completed'
                },
                'partially-completed': {
                    'count': counts_dict.get('Partially Completed', 0),
                    'label': 'Partially Completed'
                }
            }

            return {
                'success': True,
                'status_counts': response_data
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving order status counts: {str(e)}'
            }, 400


@rest_api.route('/api/orders')
class OrdersList(Resource):
    """
    MySQL Optimized: Endpoint for retrieving orders filtered by status
    """

    @rest_api.doc(params={
        'status': 'Order status (open, picking, packing, dispatch-ready, completed, partially-completed)',
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID',
        'limit': 'Limit number of results (default 100)'
    })
    @rest_api.marshal_with(orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get orders filtered by status - MySQL optimized with joins"""
        try:
            status = request.args.get('status', '')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            limit = request.args.get('limit', 100, type=int)

            # Map frontend status names to database status names
            status_map = {
                'open': 'Open',
                'picking': 'Picking',
                'packing': 'Packing',
                'dispatch-ready': 'Dispatch Ready',
                'completed': 'Completed',
                'partially-completed': 'Partially Completed'
            }

            db_status = status_map.get(status.lower(), '') if status else ''

            # MySQL optimized query with proper joins and subquery for product count
            query = db.session.query(
                PotentialOrder.potential_order_id,
                PotentialOrder.original_order_id,
                PotentialOrder.order_date,
                PotentialOrder.status,
                PotentialOrder.requested_by,
                PotentialOrder.created_at,
                PotentialOrder.updated_at,
                Dealer.name.label('dealer_name'),
                func.count(PotentialOrderProduct.potential_order_product_id).label('product_count')
            ).outerjoin(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id
            ).outerjoin(
                PotentialOrderProduct,
                PotentialOrder.potential_order_id == PotentialOrderProduct.potential_order_id
            )

            # Apply filters
            if db_status:
                query = query.filter(PotentialOrder.status == db_status)
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Group by order fields
            query = query.group_by(
                PotentialOrder.potential_order_id,
                PotentialOrder.original_order_id,
                PotentialOrder.order_date,
                PotentialOrder.status,
                PotentialOrder.requested_by,
                PotentialOrder.created_at,
                PotentialOrder.updated_at,
                Dealer.name
            )

            # Order by most recent first and limit
            query = query.order_by(PotentialOrder.created_at.desc()).limit(limit)

            # Execute query
            results = query.all()

            orders = []
            for result in results:
                # Get the most recent state change for this order
                latest_state = db.session.query(
                    OrderStateHistory.changed_at,
                    OrderState.state_name
                ).join(
                    OrderState, OrderStateHistory.state_id == OrderState.state_id
                ).filter(
                    OrderStateHistory.potential_order_id == result.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at.desc()
                ).first()

                current_state_time = result.updated_at
                if latest_state:
                    current_state_time = latest_state.changed_at

                # Get complete state history for this order
                state_history_query = db.session.query(
                    OrderStateHistory.changed_at,
                    OrderStateHistory.changed_by,
                    OrderState.state_name
                ).join(
                    OrderState, OrderStateHistory.state_id == OrderState.state_id
                ).filter(
                    OrderStateHistory.potential_order_id == result.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at
                )

                formatted_history = []
                for history in state_history_query.all():
                    formatted_history.append({
                        'state_name': history.state_name,
                        'timestamp': history.changed_at.isoformat(),
                        'user': f"User {history.changed_by}"
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
                frontend_status = frontend_status_map.get(result.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{result.potential_order_id}",
                    'original_order_id': result.original_order_id,
                    'dealer_name': result.dealer_name or 'Unknown Dealer',
                    'order_date': result.order_date.isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {result.requested_by}",
                    'products': result.product_count,
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
    MySQL Optimized: Endpoint for retrieving details of a specific order
    """

    @rest_api.marshal_with(order_detail_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get order details - MySQL optimized"""
        try:
            # Extract the numeric part from the order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # MySQL optimized query with joins
            order_query = db.session.query(
                PotentialOrder.potential_order_id,
                PotentialOrder.original_order_id,
                PotentialOrder.order_date,
                PotentialOrder.status,
                PotentialOrder.requested_by,
                PotentialOrder.updated_at,
                Dealer.name.label('dealer_name')
            ).outerjoin(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id
            ).filter(
                PotentialOrder.potential_order_id == numeric_id
            ).first()

            if not order_query:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Get product count
            product_count = db.session.query(
                func.count(PotentialOrderProduct.potential_order_product_id)
            ).filter(
                PotentialOrderProduct.potential_order_id == numeric_id
            ).scalar()

            # Get state history with a single optimized query
            state_history = db.session.query(
                OrderStateHistory.changed_at,
                OrderStateHistory.changed_by,
                OrderState.state_name
            ).join(
                OrderState, OrderStateHistory.state_id == OrderState.state_id
            ).filter(
                OrderStateHistory.potential_order_id == numeric_id
            ).order_by(
                OrderStateHistory.changed_at
            ).all()

            # Format state history
            formatted_history = []
            for history in state_history:
                formatted_history.append({
                    'state_name': history.state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': f"User {history.changed_by}"
                })

            # Get the time of the most recent state change
            current_state_time = order_query.updated_at
            if formatted_history:
                current_state_time = state_history[-1].changed_at

            # Map database status to frontend status
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed',
                'Partially Completed': 'partially-completed'
            }
            status = status_map.get(order_query.status, 'open')

            # Format the order
            order_data = {
                'order_request_id': f"PO{order_query.potential_order_id}",
                'original_order_id': order_query.original_order_id,
                'dealer_name': order_query.dealer_name or 'Unknown Dealer',
                'order_date': order_query.order_date.isoformat(),
                'status': status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to': f"User {order_query.requested_by}",
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
    MySQL Optimized: Endpoint for retrieving recent order activity
    """

    @rest_api.doc(params={
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID',
        'limit': 'Maximum number of orders to return (default 10)'
    })
    @rest_api.marshal_with(recent_orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get recent order activity - MySQL optimized"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            limit = request.args.get('limit', 10, type=int)

            # MySQL optimized query for recent orders
            query = db.session.query(
                PotentialOrder.potential_order_id,
                PotentialOrder.order_date,
                PotentialOrder.status,
                PotentialOrder.requested_by,
                PotentialOrder.created_at,
                PotentialOrder.updated_at,
                Dealer.name.label('dealer_name')
            ).outerjoin(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id
            )

            # Apply filters if provided
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Order by most recent and limit
            query = query.order_by(PotentialOrder.created_at.desc()).limit(limit)

            # Execute query
            results = query.all()

            orders = []
            for result in results:
                # Get the most recent state change for each order
                latest_state = db.session.query(
                    OrderStateHistory.changed_at
                ).filter(
                    OrderStateHistory.potential_order_id == result.potential_order_id
                ).order_by(
                    OrderStateHistory.changed_at.desc()
                ).first()

                current_state_time = result.updated_at
                if latest_state:
                    current_state_time = latest_state.changed_at

                # Map database status to frontend status
                status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                status = status_map.get(result.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{result.potential_order_id}",
                    'dealer_name': result.dealer_name or 'Unknown Dealer',
                    'status': status,
                    'order_date': result.order_date.isoformat(),
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {result.requested_by}",
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