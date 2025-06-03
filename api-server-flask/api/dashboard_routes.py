# -*- encoding: utf-8 -*-

from flask import request
from flask_restx import Resource, fields
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_

from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer
from .routes import rest_api

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
    FIXED: Endpoint for retrieving order status counts - Compatible with both MySQL and SQLite
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get counts of orders by status - Fixed version"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            print(f"Debug: warehouse_id={warehouse_id}, company_id={company_id}")  # Debug log

            # Build base query
            base_query = PotentialOrder.query

            # Apply filters if provided
            if warehouse_id:
                base_query = base_query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                base_query = base_query.filter(PotentialOrder.company_id == company_id)

            # Get counts for each status using individual queries (more reliable across databases)
            open_count = base_query.filter(PotentialOrder.status == 'Open').count()
            picking_count = base_query.filter(PotentialOrder.status == 'Picking').count()
            packing_count = base_query.filter(PotentialOrder.status == 'Packing').count()
            dispatch_ready_count = base_query.filter(PotentialOrder.status == 'Dispatch Ready').count()
            completed_count = base_query.filter(PotentialOrder.status == 'Completed').count()
            partially_completed_count = base_query.filter(PotentialOrder.status == 'Partially Completed').count()

            print(f"Debug counts: open={open_count}, picking={picking_count}, packing={packing_count}")  # Debug log

            # Prepare response
            response_data = {
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
                'dispatch-ready': {
                    'count': dispatch_ready_count,
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

            return {
                'success': True,
                'status_counts': response_data
            }, 200

        except Exception as e:
            print(f"Error in /api/orders/status: {str(e)}")  # Debug logging
            import traceback
            traceback.print_exc()  # Full traceback for debugging
            return {
                'success': False,
                'msg': f'Error retrieving order status counts: {str(e)}'
            }, 400


@rest_api.route('/api/orders')
class OrdersList(Resource):
    """
    FIXED: Endpoint for retrieving orders filtered by status
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
        """Get orders filtered by status - Fixed version"""
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

            # Use simple query approach for better compatibility
            query = db.session.query(PotentialOrder).join(
                Dealer, PotentialOrder.dealer_id == Dealer.dealer_id, isouter=True
            )

            # Apply filters
            if db_status:
                query = query.filter(PotentialOrder.status == db_status)
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Order by most recent first and limit
            query = query.order_by(PotentialOrder.created_at.desc()).limit(limit)

            # Execute query
            potential_orders = query.all()

            orders = []
            for potential_order in potential_orders:
                # Get dealer name
                dealer = Dealer.query.get(potential_order.dealer_id) if potential_order.dealer_id else None
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
                    formatted_history.append({
                        'state_name': state_name,
                        'timestamp': history.changed_at.isoformat(),
                        'user': f"User {history.changed_by}"
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
                    'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                frontend_status = frontend_status_map.get(potential_order.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'original_order_id': potential_order.original_order_id,
                    'dealer_name': dealer_name,
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
            print(f"Error in /api/orders: {str(e)}")
            import traceback
            traceback.print_exc()
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
            # Extract the numeric part from the order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get the order
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get dealer name
            dealer = Dealer.query.get(potential_order.dealer_id) if potential_order.dealer_id else None
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
                formatted_history.append({
                    'state_name': state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': f"User {history.changed_by}"
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
                'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed',
                'Partially Completed': 'partially-completed'
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
                'assigned_to': f"User {potential_order.requested_by}",
                'products': product_count,
                'state_history': formatted_history
            }

            return {
                'success': True,
                'order': order_data
            }, 200

        except Exception as e:
            print(f"Error in /api/orders/{order_id}: {str(e)}")
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

            # Base query
            query = PotentialOrder.query

            # Apply filters if provided
            if warehouse_id:
                query = query.filter(PotentialOrder.warehouse_id == warehouse_id)
            if company_id:
                query = query.filter(PotentialOrder.company_id == company_id)

            # Order by most recent and limit
            query = query.order_by(PotentialOrder.created_at.desc()).limit(limit)

            # Execute query
            potential_orders = query.all()

            orders = []
            for potential_order in potential_orders:
                # Get dealer name
                dealer = Dealer.query.get(potential_order.dealer_id) if potential_order.dealer_id else None
                dealer_name = dealer.name if dealer else 'Unknown Dealer'

                # Get the most recent state change for each order
                latest_state = db.session.query(OrderStateHistory).filter(
                    OrderStateHistory.potential_order_id == potential_order.potential_order_id
                ).order_by(OrderStateHistory.changed_at.desc()).first()

                current_state_time = potential_order.updated_at
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
                status = status_map.get(potential_order.status, 'open')

                # Format the order
                order_data = {
                    'order_request_id': f"PO{potential_order.potential_order_id}",
                    'dealer_name': dealer_name,
                    'status': status,
                    'order_date': potential_order.order_date.isoformat(),
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {potential_order.requested_by}",
                }
                orders.append(order_data)

            return {
                'success': True,
                'recent_orders': orders
            }, 200

        except Exception as e:
            print(f"Error in /api/orders/recent: {str(e)}")
            return {
                'success': False,
                'msg': f'Error retrieving recent orders: {str(e)}'
            }, 400