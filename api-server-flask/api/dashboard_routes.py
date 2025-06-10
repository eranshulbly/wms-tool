# -*- encoding: utf-8 -*-

from flask import request
from flask_restx import Resource, fields
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_

from .models import (
    Users, JWTTokenBlocklist, Warehouse, Company, PotentialOrder,
    PotentialOrderProduct, OrderStateHistory, OrderState, Product,
    Dealer, Box, Order, OrderProduct, OrderBox, BoxProduct, Invoice,
    mysql_manager
)
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
    MySQL endpoint for retrieving all warehouses
    """

    @rest_api.marshal_with(warehouses_response)
    @rest_api.response(400, 'Error', error_response)
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

    @rest_api.marshal_with(companies_response)
    @rest_api.response(400, 'Error', error_response)
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


@rest_api.route('/api/orders/status')
class OrderStatusCount(Resource):
    """
    MySQL endpoint for retrieving order status counts
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get counts of orders by status - MySQL implementation"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            print(f"Debug: warehouse_id={warehouse_id}, company_id={company_id}")

            # Get counts for each status using MySQL
            open_count = PotentialOrder.count_by_status('Open', warehouse_id, company_id)
            picking_count = PotentialOrder.count_by_status('Picking', warehouse_id, company_id)
            packing_count = PotentialOrder.count_by_status('Packing', warehouse_id, company_id)
            dispatch_ready_count = PotentialOrder.count_by_status('Dispatch Ready', warehouse_id, company_id)
            completed_count = PotentialOrder.count_by_status('Completed', warehouse_id, company_id)
            partially_completed_count = PotentialOrder.count_by_status('Partially Completed', warehouse_id, company_id)

            print(f"Debug counts: open={open_count}, picking={picking_count}, packing={packing_count}")

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
            print(f"Error in /api/orders/status: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'msg': f'Error retrieving order status counts: {str(e)}'
            }, 400

@rest_api.route('/api/orders')
class OrdersList(Resource):
    """
    MySQL endpoint for retrieving orders filtered by status
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
        """Get orders filtered by status - MySQL implementation"""
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

            # Use MySQL query to get orders with dealer information
            potential_orders = PotentialOrder.find_by_filters(
                status=db_status,
                warehouse_id=warehouse_id,
                company_id=company_id,
                limit=limit
            )

            orders = []
            for order_data in potential_orders:
                # Get dealer name
                dealer_name = order_data.get('dealer_name', 'Unknown Dealer')

                # Get product count
                product_count = PotentialOrderProduct.count_by_order(order_data['potential_order_id'])

                # Get state history
                state_history_data = OrderStateHistory.get_history_for_order(order_data['potential_order_id'])

                # Format state history
                formatted_history = []
                for history in state_history_data:
                    formatted_history.append({
                        'state_name': history['state_name'],
                        'timestamp': history['changed_at'].isoformat(),
                        'user': f"User {history['changed_by']}"
                    })

                # Get the time of the most recent state change
                current_state_time = order_data['updated_at']
                if state_history_data:
                    current_state_time = state_history_data[-1]['changed_at']

                # Map database status to frontend status
                frontend_status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                frontend_status = frontend_status_map.get(order_data['status'], 'open')

                # Format the order
                order_result = {
                    'order_request_id': f"PO{order_data['potential_order_id']}",
                    'original_order_id': order_data['original_order_id'],
                    'dealer_name': dealer_name,
                    'order_date': order_data['order_date'].isoformat(),
                    'status': frontend_status,
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {order_data['requested_by']}",
                    'products': product_count,
                    'state_history': formatted_history
                }
                orders.append(order_result)

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
    MySQL endpoint for retrieving details of a specific order
    """

    @rest_api.marshal_with(order_detail_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get order details - MySQL implementation"""
        try:
            # Extract the numeric part from the order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get the order using MySQL
            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {
                    'success': False,
                    'msg': 'Order not found'
                }, 404

            # Get dealer information
            dealer = None
            if potential_order.dealer_id:
                dealer = Dealer.get_by_id(potential_order.dealer_id)
            dealer_name = dealer.name if dealer else 'Unknown Dealer'

            # Get product count
            product_count = PotentialOrderProduct.count_by_order(numeric_id)

            # Get state history
            state_history_data = OrderStateHistory.get_history_for_order(numeric_id)

            # Format state history
            formatted_history = []
            for history in state_history_data:
                formatted_history.append({
                    'state_name': history['state_name'],
                    'timestamp': history['changed_at'].isoformat(),
                    'user': f"User {history['changed_by']}"
                })

            # Get the time of the most recent state change
            current_state_time = potential_order.updated_at
            if state_history_data:
                current_state_time = state_history_data[-1]['changed_at']

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
    MySQL endpoint for retrieving recent order activity
    """

    @rest_api.doc(params={
        'warehouse_id': 'Warehouse ID',
        'company_id': 'Company ID',
        'limit': 'Maximum number of orders to return (default 10)'
    })
    @rest_api.marshal_with(recent_orders_response)
    @rest_api.response(400, 'Error', error_response)
    def get(self):
        """Get recent order activity - MySQL implementation"""
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)
            limit = request.args.get('limit', 10, type=int)

            # Get recent orders using MySQL
            potential_orders = PotentialOrder.find_by_filters(
                warehouse_id=warehouse_id,
                company_id=company_id,
                limit=limit
            )

            orders = []
            for order_data in potential_orders:
                # Get dealer name
                dealer_name = order_data.get('dealer_name', 'Unknown Dealer')

                # Get the most recent state change for each order
                state_history_data = OrderStateHistory.get_history_for_order(order_data['potential_order_id'])

                current_state_time = order_data['updated_at']
                if state_history_data:
                    current_state_time = state_history_data[-1]['changed_at']

                # Map database status to frontend status
                status_map = {
                    'Open': 'open',
                    'Picking': 'picking',
                    'Packing': 'packing',
                    'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed',
                    'Partially Completed': 'partially-completed'
                }
                status = status_map.get(order_data['status'], 'open')

                # Format the order
                order_result = {
                    'order_request_id': f"PO{order_data['potential_order_id']}",
                    'dealer_name': dealer_name,
                    'status': status,
                    'order_date': order_data['order_date'].isoformat(),
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to': f"User {order_data['requested_by']}",
                }
                orders.append(order_result)

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