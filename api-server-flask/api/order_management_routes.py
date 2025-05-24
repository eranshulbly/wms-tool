# -*- encoding: utf-8 -*-
"""
Order Management API routes - Fixed with proper status update endpoint
"""

from flask import request
from flask_restx import Resource, fields

from datetime import datetime, timedelta

from .models import db, Warehouse, Company, PotentialOrder, PotentialOrderProduct, OrderStateHistory, OrderState, \
    Product, Dealer, Box, Order, OrderProduct, OrderBox, BoxProduct
from .routes import token_required, rest_api

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


@rest_api.route('/api/orders/<string:order_id>/details')
class OrderDetailWithProducts(Resource):
    """
    Endpoint for retrieving detailed order information including products
    """

    @rest_api.response(200, 'Success', order_detail_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def get(self, order_id):
        """Get detailed information for a specific order including all products"""
        try:
            # Extract the numeric part from the order_id
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            # Get the order
            potential_order = PotentialOrder.query.get_or_404(numeric_id)

            # Get dealer name
            dealer = Dealer.query.get(potential_order.dealer_id)
            dealer_name = dealer.name if dealer else 'Unknown Dealer'

            # Get products for this order with detailed information
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

                # Get product info
                product = Product.query.get(box_product.product_id)
                if product:
                    box_dict[box.box_id]['products'].append({
                        'product_id': product.product_id,
                        'quantity': box_product.quantity
                    })

            boxes = list(box_dict.values())

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
                username = f"User {history.changed_by}"
                formatted_history.append({
                    'state_name': state.state_name,
                    'timestamp': history.changed_at.isoformat(),
                    'user': username
                })

            # Get current state time
            current_state_time = potential_order.updated_at
            if formatted_history:
                current_state_time = datetime.fromisoformat(formatted_history[-1]['timestamp'].replace('Z', '+00:00'))

            # Map database status to frontend status
            status_map = {
                'Open': 'open',
                'Picking': 'picking',
                'Packing': 'packing',
                'Dispatch Ready': 'dispatch',
                'Completed': 'completed',
                'Partially Completed': 'partially-completed'
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
                'assigned_to': f"User {potential_order.requested_by}",
                'products': products,
                'boxes': boxes,
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


@rest_api.route('/api/orders/<string:order_id>/status')
class OrderStatusUpdate(Resource):
    """
    FIXED: Endpoint for updating order status - this was missing in the original routes
    """

    @rest_api.expect(update_status_model)
    @rest_api.response(200, 'Success', update_status_response)
    @rest_api.response(400, 'Error', error_response)
    @rest_api.response(404, 'Order not found', error_response)
    def post(self, order_id):
        """Update the status of an order"""
        try:
            # Extract the numeric part from the order_id
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
                'dispatch': 'Dispatch Ready',
                'completed': 'Completed',
                'partially-completed': 'Partially Completed'
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