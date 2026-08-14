# -*- encoding: utf-8 -*-
"""
Dashboard / listing routes:
  GET  /api/warehouses
  GET  /api/companies
  GET  /api/orders/status
  GET  /api/orders
  GET  /api/orders/bulk-export
  POST /api/orders/bulk-import
  GET  /api/orders/<order_id>
  GET  /api/orders/recent
"""

from datetime import datetime
from collections import defaultdict

import io
import os
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from flask import request, send_file

from api.shared import media
from flask_restx import Resource, fields

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.models import (
    Users, Warehouse, Company, PotentialOrder,
    PotentialOrderProduct, OrderStateHistory, OrderState, Order,
    mysql_manager
)
from api.db_manager import partition_filter
from api.permissions import (
    get_permissions, has_all_warehouse_access,
    resolve_company_scope, company_filter_sql, CompanyAccessDenied,
)
from api.core.logging import get_logger

logger = get_logger(__name__)

# ── Models ───────────────────────────────────────────────────────────────────

warehouse_model = rest_api.model('Warehouse', {
    'id':       fields.Integer(description='Warehouse ID'),
    'name':     fields.String(description='Warehouse name'),
    'location': fields.String(description='Warehouse location'),
})

warehouses_response = rest_api.model('WarehousesResponse', {
    'success':    fields.Boolean(description='Success status'),
    'warehouses': fields.List(fields.Nested(warehouse_model), description='List of warehouses'),
})

company_model = rest_api.model('Company', {
    'id':   fields.Integer(description='Company ID'),
    'name': fields.String(description='Company name'),
})

companies_response = rest_api.model('CompaniesResponse', {
    'success':   fields.Boolean(description='Success status'),
    'companies': fields.List(fields.Nested(company_model), description='List of companies'),
})

status_count_model = rest_api.model('StatusCount', {
    'count': fields.Integer(description='Number of orders with this status'),
    'label': fields.String(description='Label for the status'),
})

status_counts_model = rest_api.model('StatusCounts', {
    'submitted':           fields.Nested(status_count_model),
    'open':                fields.Nested(status_count_model),
    'picking':             fields.Nested(status_count_model),
    'packed':              fields.Nested(status_count_model),
    'invoiced':            fields.Nested(status_count_model),
    'dispatch-ready':      fields.Nested(status_count_model),
    'completed':           fields.Nested(status_count_model),
    'partially-completed': fields.Nested(status_count_model),
})

status_response = rest_api.model('StatusResponse', {
    'success':       fields.Boolean(description='Success status'),
    'status_counts': fields.Nested(status_counts_model, description='Order status counts'),
})

dash_state_history_model = rest_api.model('DashStateHistory', {
    'state_name': fields.String(description='State name'),
    'timestamp':  fields.String(description='Timestamp of state change'),
    'user':       fields.String(description='User who changed the state'),
})

order_model = rest_api.model('Order', {
    'order_request_id':  fields.String(description='Order request ID'),
    'original_order_id': fields.String(description='Original order ID'),
    'dealer_name':       fields.String(description='Dealer name'),
    'order_date':        fields.String(description='Order date'),
    'status':            fields.String(description='Current status'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to':       fields.String(description='User assigned to this order'),
    'products':          fields.Integer(description='Number of products in this order'),
    'state_history':     fields.List(fields.Nested(dash_state_history_model)),
})

orders_response = rest_api.model('OrdersResponse', {
    'success': fields.Boolean(description='Success status'),
    'orders':  fields.List(fields.Nested(order_model), description='List of orders'),
    'total':   fields.Integer(description='Total number of orders matching filters'),
    'page':    fields.Integer(description='Current page'),
    'limit':   fields.Integer(description='Page size'),
})

order_detail_response = rest_api.model('OrderDetailResponse', {
    'success': fields.Boolean(description='Success status'),
    'order':   fields.Nested(order_model, description='Order details'),
})

recent_order_model = rest_api.model('RecentOrder', {
    'order_request_id':  fields.String(description='Order request ID'),
    'dealer_name':       fields.String(description='Dealer name'),
    'status':            fields.String(description='Current status'),
    'order_date':        fields.String(description='Order date'),
    'current_state_time': fields.String(description='Time of current state'),
    'assigned_to':       fields.String(description='User assigned to this order'),
})

recent_orders_response = rest_api.model('RecentOrdersResponse', {
    'success':       fields.Boolean(description='Success status'),
    'recent_orders': fields.List(fields.Nested(recent_order_model), description='List of recent orders'),
})

dash_error_response = rest_api.model('DashErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg':     fields.String(description='Error message'),
})

# ── Status maps (module-level constants used across multiple endpoints) ───────

FRONTEND_TO_DB_STATUS = {
    'open':           'Open',
    'picking':        'Picking',
    'packed':         'Packed',
    'invoiced':       'Invoiced',
    'dispatch-ready': 'Dispatch Ready',
    'completed':      'Completed',
}

DB_TO_FRONTEND_STATUS = {v: k for k, v in FRONTEND_TO_DB_STATUS.items()}

# open→picking, picking→packed, packed→invoiced, dispatch-ready→completed
VALID_BULK_TRANSITIONS = {
    'open':           'picking',
    'picking':        'packed',
    'packed':         'invoiced',
    'dispatch-ready': 'completed',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_state(name, description):
    """Get or create an OrderState by name."""
    state = OrderState.find_by_name(name)
    if not state:
        state = OrderState(state_name=name, description=description)
        state.save()
    return state

# ── Endpoints ────────────────────────────────────────────────────────────────

@rest_api.route('/api/warehouses')
class WarehouseList(Resource):

    @rest_api.marshal_with(warehouses_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            warehouses = Warehouse.get_all()
            warehouse_list = [{'id': w.warehouse_id, 'name': w.name, 'location': w.location}
                              for w in warehouses]
            return {'success': True, 'warehouses': warehouse_list}, 200
        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving warehouses: {str(e)}'}, 400


@rest_api.route('/api/companies')
class CompanyList(Resource):

    @rest_api.marshal_with(companies_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            from api.db_manager import mysql_manager as _db
            warehouse_id = request.args.get('warehouse_id', type=int)

            # Bug 20 fix: filter companies by warehouse when warehouse_id is provided
            if warehouse_id:
                rows = _db.execute_query(
                    """SELECT DISTINCT c.company_id, c.name
                       FROM company c
                       JOIN user_warehouse_company uwc ON c.company_id = uwc.company_id
                       WHERE uwc.warehouse_id = %s
                       ORDER BY c.name""",
                    (warehouse_id,)
                )
                company_list = [{'id': r['company_id'], 'name': r['name']} for r in rows]
            else:
                companies = Company.get_all()
                company_list = [{'id': c.company_id, 'name': c.name} for c in companies]

            return {'success': True, 'companies': company_list}, 200
        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving companies: {str(e)}'}, 400


@rest_api.route('/api/orders/status')
class OrderStatusCount(Resource):
    """MySQL endpoint for retrieving order status counts."""

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID'})
    @rest_api.marshal_with(status_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403

            all_statuses = [
                ('open',                'Open',               'Open Orders'),
                ('picking',             'Picking',            'Picking'),
                ('packed',              'Packed',             'Packed'),
                ('invoiced',            'Invoiced',           'Invoiced'),
                ('dispatch-ready',      'Dispatch Ready',     'Dispatch Ready'),
                ('completed',           'Completed',          'Completed'),
                ('partially-completed', 'Partially Completed', 'Partially Completed'),
            ]

            response_data = {}

            # App-submitted orders live in their own table (submitted_orders), not
            # potential_order, so count them directly — scoped by the same warehouse /
            # company filters as the rest of the overview. "Submitted" here means orders
            # still in the Submitted Orders tab (awaiting a part-convertor upload).
            sub_where, sub_params = ["dms_status IN ('submitted','re_submitted')"], []
            if warehouse_id:
                sub_where.append("warehouse_id = %s")
                sub_params.append(warehouse_id)
            cf_sql, cf_params = company_filter_sql(company_ids)
            sub_where.append(cf_sql)
            sub_params.extend(cf_params)
            sub_rows = mysql_manager.execute_query(
                f"SELECT COUNT(*) AS c FROM submitted_orders WHERE {' AND '.join(sub_where)}",
                tuple(sub_params),
            )
            response_data['submitted'] = {
                'count': (sub_rows[0]['c'] if sub_rows else 0), 'label': 'Submitted',
            }

            for key, db_status, label in all_statuses:
                count = PotentialOrder.count_by_status(db_status, warehouse_id, company_ids)
                response_data[key] = {'count': count, 'label': label}

            return {'success': True, 'status_counts': response_data}, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error retrieving order status counts: {str(e)}'}, 400


@rest_api.route('/api/orders')
class OrdersList(Resource):
    """MySQL endpoint for retrieving orders filtered by status."""

    @rest_api.doc(params={
        'status':       'Order status (open, picking, packed, dispatch-ready, completed, partially-completed)',
        'warehouse_id': 'Warehouse ID',
        'company_id':   'Company ID',
        'limit':        'Limit number of results (default 100)',
    })
    @rest_api.marshal_with(orders_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            status       = request.args.get('status', '')
            warehouse_id = request.args.get('warehouse_id', type=int)
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403
            limit        = request.args.get('limit', 100,  type=int)
            page         = request.args.get('page',  1,    type=int)
            offset       = (page - 1) * limit

            status_map = {
                'open': 'Open', 'picking': 'Picking', 'packed': 'Packed',
                'invoiced': 'Invoiced', 'dispatch-ready': 'Dispatch Ready',
                'completed': 'Completed', 'partially-completed': 'Partially Completed',
            }
            db_status = status_map.get(status.lower(), '') if status else ''

            total = PotentialOrder.count_by_filters(
                status=db_status, warehouse_id=warehouse_id, company_ids=company_ids
            )
            potential_orders = PotentialOrder.find_by_filters(
                status=db_status, warehouse_id=warehouse_id, company_ids=company_ids,
                limit=limit, offset=offset
            )

            frontend_status_map = {
                'Open': 'open', 'Picking': 'picking', 'Packed': 'packed',
                'Invoiced': 'invoiced', 'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed', 'Partially Completed': 'partially-completed',
            }

            # Bulk-fetch product counts and state history to avoid N+1 queries
            order_ids       = [o['potential_order_id'] for o in potential_orders]
            product_counts  = {}
            state_histories = {}
            if order_ids:
                placeholders = ','.join(['%s'] * len(order_ids))
                pf_pop_sql, pf_pop_params = partition_filter('potential_order_product')
                count_rows = mysql_manager.execute_query(
                    f"SELECT potential_order_id, COUNT(*) as cnt FROM potential_order_product"
                    f" WHERE {pf_pop_sql} AND potential_order_id IN ({placeholders})"
                    f" GROUP BY potential_order_id",
                    pf_pop_params + tuple(order_ids)
                )
                product_counts = {r['potential_order_id']: r['cnt'] for r in (count_rows or [])}

                pf_osh_sql, pf_osh_params = partition_filter('order_state_history', alias='osh')
                history_rows = mysql_manager.execute_query(
                    f"SELECT osh.*, os.state_name"
                    f" FROM order_state_history osh"
                    f" JOIN order_state os ON osh.state_id = os.state_id"
                    f" WHERE {pf_osh_sql} AND osh.potential_order_id IN ({placeholders})"
                    f" ORDER BY osh.potential_order_id, osh.changed_at",
                    pf_osh_params + tuple(order_ids)
                )
                _hist_map = defaultdict(list)
                for h in (history_rows or []):
                    _hist_map[h['potential_order_id']].append(h)
                state_histories = dict(_hist_map)

            orders = []
            for order_data in potential_orders:
                try:
                    dealer_name       = order_data.get('dealer_name') or 'Unknown Dealer'
                    product_count     = product_counts.get(order_data['potential_order_id'], 0)
                    state_history_data = state_histories.get(order_data['potential_order_id'], [])

                    formatted_history = []
                    for history in state_history_data:
                        formatted_history.append({
                            'state_name': history['state_name'],
                            'timestamp':  history['changed_at'].isoformat() if history['changed_at'] else None,
                            'user':       f"User {history['changed_by']}"
                        })

                    current_state_time = (
                        state_history_data[-1]['changed_at'] if state_history_data
                        else order_data.get('updated_at') or order_data.get('created_at')
                    )
                    current_state_time_str = current_state_time.isoformat() if current_state_time else None

                    order_date = order_data.get('order_date')
                    order_date_str = order_date.isoformat() if order_date else None

                    _db_status    = order_data.get('status', '')
                    frontend_status = frontend_status_map.get(_db_status, _db_status.lower().replace(' ', '-'))

                    orders.append({
                        'order_request_id':  f"PO{order_data['potential_order_id']}",
                        'original_order_id': order_data['original_order_id'],
                        'dealer_name':       dealer_name,
                        'order_date':        order_date_str,
                        'status':            frontend_status,
                        'current_state_time': current_state_time_str,
                        'assigned_to':       order_data.get('assigned_username') or f"User {order_data['requested_by']}",
                        'products':          product_count,
                        'state_history':     formatted_history,
                        'invoice_submitted': bool(order_data.get('invoice_submitted', False)),
                    })
                except Exception as row_err:
                    logger.warning("Skipping order due to serialisation error",
                                   extra={'potential_order_id': order_data.get('potential_order_id'),
                                          'error': str(row_err)})

            return {'success': True, 'orders': orders, 'total': total, 'page': page, 'limit': limit}, 200

        except Exception as e:
            logger.exception("Error in /api/orders")
            return {'success': False, 'msg': f'Error retrieving orders: {str(e)}'}, 400


@rest_api.route('/api/orders/bulk-export')
class BulkOrderExport(Resource):
    """Download orders as Excel template for bulk status update."""

    @token_required
    @active_required
    def get(self, current_user):
        """Generate and return Excel file for bulk order status update."""
        try:
            status       = request.args.get('status', '')
            warehouse_id = request.args.get('warehouse_id', type=int)
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403

            db_status = FRONTEND_TO_DB_STATUS.get(status.lower(), '') if status else ''

            # Bug 21 fix: fetch all matching orders (no artificial cap).
            total_count = PotentialOrder.count_by_filters(
                status=db_status, warehouse_id=warehouse_id, company_ids=company_ids
            )
            potential_orders = PotentialOrder.find_by_filters(
                status=db_status,
                warehouse_id=warehouse_id,
                company_ids=company_ids,
                limit=max(total_count, 1)
            )

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Orders'

            header_fill = PatternFill(start_color='1565C0', end_color='1565C0', fill_type='solid')
            header_font = Font(color='FFFFFF', bold=True)
            headers = ['Order ID', 'Customer Name', 'Current Status', 'Expected Status', 'Number of Boxes']
            for col, h in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=h)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')

            note_fill = PatternFill(start_color='FFF9C4', end_color='FFF9C4', fill_type='solid')
            note_font = Font(italic=True, color='5D4037')
            notes = [
                '(do not edit)', '(do not edit)', '(do not edit)',
                'Fill: picking / packed / invoiced / completed',
                'Fill only when moving packed → invoiced',
            ]
            for col, note in enumerate(notes, 1):
                cell = ws.cell(row=2, column=col, value=note)
                cell.fill = note_fill
                cell.font = note_font
                cell.alignment = Alignment(horizontal='center', vertical='center')

            blocked_fill = PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid')
            ws.cell(row=3, column=1, value='NOTE').fill = blocked_fill
            note_cell = ws.cell(row=3, column=2,
                                value='invoiced → dispatch-ready is NOT allowed here. Use the Invoice Upload tab.')
            note_cell.fill = blocked_fill
            note_cell.font = Font(bold=True, color='B71C1C')
            ws.merge_cells('B3:E3')

            readonly_fill = PatternFill(start_color='F5F5F5', end_color='F5F5F5', fill_type='solid')
            for row_idx, order_data in enumerate(potential_orders, 4):
                current_fe_status = DB_TO_FRONTEND_STATUS.get(order_data['status'],
                                                               order_data['status'].lower().replace(' ', '-'))
                dealer_name = order_data.get('dealer_name', 'Unknown')

                for col, val in enumerate([
                    f"PO{order_data['potential_order_id']}",
                    dealer_name,
                    current_fe_status,
                    '',
                    '',
                ], 1):
                    cell = ws.cell(row=row_idx, column=col, value=val)
                    if col <= 3:
                        cell.fill = readonly_fill

            ws.column_dimensions['A'].width = 14
            ws.column_dimensions['B'].width = 32
            ws.column_dimensions['C'].width = 20
            ws.column_dimensions['D'].width = 30
            ws.column_dimensions['E'].width = 22
            ws.row_dimensions[1].height = 20
            ws.row_dimensions[2].height = 18

            output = io.BytesIO()
            wb.save(output)
            output.seek(0)

            filename = f'orders_bulk_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )

        except Exception as e:
            return {'success': False, 'msg': f'Error generating export: {str(e)}'}, 400


@rest_api.route('/api/orders/bulk-import')
class BulkOrderImport(Resource):
    """Upload filled Excel template to perform bulk order status transitions."""

    @token_required
    @active_required
    def post(self, current_user):
        """Process bulk order status updates from uploaded Excel."""
        try:
            if 'file' not in request.files:
                return {'success': False, 'msg': 'No file uploaded'}, 400

            file = request.files['file']
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file.read()))
                ws = wb.active
            except Exception as e:
                return {'success': False, 'msg': f'Invalid Excel file: {str(e)}'}, 400

            moved, skipped, errors = [], [], []

            # Data starts at row 4 (rows 1-3 are header / notes)
            for row in ws.iter_rows(min_row=4, values_only=True):
                order_id        = str(row[0] or '').strip() if row[0] else ''
                current_status  = str(row[2] or '').strip().lower()
                expected_status = str(row[3] or '').strip().lower()

                if not order_id:
                    continue

                if not expected_status:
                    skipped.append({'order_id': order_id, 'reason': 'No expected status provided'})
                    continue

                if current_status == expected_status:
                    skipped.append({'order_id': order_id, 'reason': 'Status unchanged'})
                    continue

                if current_status == 'invoiced' and expected_status == 'dispatch-ready':
                    errors.append({
                        'order_id': order_id,
                        'reason': 'invoiced → dispatch-ready is not allowed here. Use the Invoice Upload tab.'
                    })
                    continue

                if VALID_BULK_TRANSITIONS.get(current_status) != expected_status:
                    valid_next = VALID_BULK_TRANSITIONS.get(current_status, 'none')
                    errors.append({
                        'order_id': order_id,
                        'reason': f'Invalid transition: {current_status} → {expected_status}. Valid next: {valid_next}'
                    })
                    continue

                try:
                    numeric_id = int(order_id.replace('PO', ''))
                except ValueError:
                    errors.append({'order_id': order_id, 'reason': 'Invalid order ID format'})
                    continue

                potential_order = PotentialOrder.get_by_id(numeric_id)
                if not potential_order:
                    errors.append({'order_id': order_id, 'reason': 'Order not found'})
                    continue

                db_current = DB_TO_FRONTEND_STATUS.get(potential_order.status,
                                                        potential_order.status.lower().replace(' ', '-'))
                if db_current != current_status:
                    errors.append({
                        'order_id': order_id,
                        'reason': f'Status mismatch: DB has "{db_current}", Excel shows "{current_status}"'
                    })
                    continue

                try:
                    current_time = datetime.utcnow()

                    if expected_status == 'invoiced':
                        final_order = Order(
                            potential_order_id=numeric_id,
                            order_number=f"ORD-{numeric_id}-{current_time.strftime('%Y%m%d%H%M')}",
                            status='Dispatch Ready',
                            box_count=potential_order.box_count,
                            created_at=current_time,
                            updated_at=current_time
                        )
                        final_order.save()

                        potential_order.status     = 'Invoiced'
                        potential_order.updated_at = current_time
                        potential_order.save()

                        state = _ensure_state('Invoiced', 'Order invoiced and ready for dispatch')
                        OrderStateHistory(
                            potential_order_id=numeric_id,
                            state_id=state.state_id,
                            changed_by=current_user.id,
                            changed_at=current_time
                        ).save()

                        moved.append({
                            'order_id': order_id, 'from': current_status, 'to': expected_status,
                            'boxes': potential_order.box_count
                        })

                    elif expected_status == 'completed':
                        final_order = Order.find_by_potential_order_id(numeric_id)
                        if not final_order:
                            errors.append({'order_id': order_id,
                                           'reason': 'No final order found for dispatch-ready order'})
                            continue

                        final_order.status          = 'Completed'
                        final_order.dispatched_date = current_time
                        final_order.updated_at      = current_time
                        final_order.save()

                        potential_order.status     = 'Completed'
                        potential_order.updated_at = current_time
                        potential_order.save()

                        state = _ensure_state('Completed', 'Order completed and dispatched')
                        OrderStateHistory(
                            potential_order_id=numeric_id,
                            state_id=state.state_id,
                            changed_by=current_user.id,
                            changed_at=current_time
                        ).save()

                        moved.append({'order_id': order_id, 'from': current_status, 'to': expected_status})

                    else:
                        # Simple transitions: open→picking, picking→packed
                        new_db_status = FRONTEND_TO_DB_STATUS[expected_status]
                        potential_order.status     = new_db_status
                        potential_order.updated_at = current_time
                        potential_order.save()

                        state = _ensure_state(new_db_status, f'Order moved to {new_db_status}')
                        OrderStateHistory(
                            potential_order_id=numeric_id,
                            state_id=state.state_id,
                            changed_by=current_user.id,
                            changed_at=current_time
                        ).save()

                        moved.append({'order_id': order_id, 'from': current_status, 'to': expected_status})

                except Exception as e:
                    errors.append({'order_id': order_id, 'reason': f'Error processing: {str(e)}'})

            return {
                'success': True,
                'summary': {'moved': len(moved), 'skipped': len(skipped), 'errors': len(errors)},
                'details': {'moved': moved, 'skipped': skipped, 'errors': errors},
            }, 200

        except Exception as e:
            return {'success': False, 'msg': f'Error processing import: {str(e)}'}, 400


@rest_api.route('/api/orders/<string:order_id>')
class OrderDetail(Resource):
    """MySQL endpoint for retrieving details of a specific order."""

    @rest_api.marshal_with(order_detail_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @rest_api.response(404, 'Order not found', dash_error_response)
    def get(self, order_id):
        """Get order details - MySQL implementation."""
        try:
            numeric_id = int(order_id.replace('PO', '')) if order_id.startswith('PO') else int(order_id)

            potential_order = PotentialOrder.get_by_id(numeric_id)
            if not potential_order:
                return {'success': False, 'msg': 'Order not found'}, 404

            from api.models import Dealer
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

            current_state_time = potential_order.updated_at
            if state_history_data:
                current_state_time = state_history_data[-1]['changed_at']

            status_map = {
                'Open': 'open', 'Picking': 'picking', 'Packed': 'packed',
                'Invoiced': 'invoiced', 'Dispatch Ready': 'dispatch-ready',
                'Completed': 'completed', 'Partially Completed': 'partially-completed',
            }
            status = status_map.get(potential_order.status, 'open')

            order_data = {
                'order_request_id':  f"PO{potential_order.potential_order_id}",
                'original_order_id': potential_order.original_order_id,
                'dealer_name':       dealer_name,
                'order_date':        potential_order.order_date.isoformat(),
                'status':            status,
                'current_state_time': current_state_time.isoformat(),
                'assigned_to':       (Users.get_by_id(potential_order.requested_by).username
                                      if potential_order.requested_by else 'Unassigned'),
                'products':          product_count,
                'state_history':     formatted_history,
            }

            return {'success': True, 'order': order_data}, 200

        except Exception as e:
            logger.exception("Error in /api/orders/<order_id>", extra={'order_id': order_id})
            return {'success': False, 'msg': f'Error retrieving order details: {str(e)}'}, 400


@rest_api.route('/api/orders/recent')
class RecentOrders(Resource):
    """MySQL endpoint for retrieving recent order activity."""

    @rest_api.doc(params={
        'warehouse_id': 'Warehouse ID',
        'company_id':   'Company ID',
        'limit':        'Maximum number of orders to return (default 10)',
    })
    @rest_api.marshal_with(recent_orders_response)
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403
            limit        = request.args.get('limit', 10, type=int)

            allowed_states = get_permissions(current_user.role)['order_states']

            potential_orders = PotentialOrder.find_by_filters(
                warehouse_id=warehouse_id,
                company_ids=company_ids,
                limit=limit,
                sort_by='updated_at'
            )
            potential_orders = [o for o in potential_orders if o['status'] in allowed_states]

            recent_ids = [o['potential_order_id'] for o in potential_orders]
            recent_state_histories = {}
            if recent_ids:
                placeholders = ','.join(['%s'] * len(recent_ids))
                pf_osh_sql, pf_osh_params = partition_filter('order_state_history', alias='osh')
                history_rows = mysql_manager.execute_query(
                    f"SELECT osh.*, os.state_name"
                    f" FROM order_state_history osh"
                    f" JOIN order_state os ON osh.state_id = os.state_id"
                    f" WHERE {pf_osh_sql} AND osh.potential_order_id IN ({placeholders})"
                    f" ORDER BY osh.potential_order_id, osh.changed_at",
                    pf_osh_params + tuple(recent_ids)
                )
                _map = defaultdict(list)
                for h in (history_rows or []):
                    _map[h['potential_order_id']].append(h)
                recent_state_histories = dict(_map)

            orders = []
            for order_data in potential_orders:
                dealer_name        = order_data.get('dealer_name', 'Unknown Dealer')
                state_history_data = recent_state_histories.get(order_data['potential_order_id'], [])

                current_state_time = order_data['updated_at']
                if state_history_data:
                    current_state_time = state_history_data[-1]['changed_at']

                status_map = {
                    'Open': 'open', 'Picking': 'picking', 'Packed': 'packed',
                    'Invoiced': 'invoiced', 'Dispatch Ready': 'dispatch-ready',
                    'Completed': 'completed', 'Partially Completed': 'partially-completed',
                }
                # App-entry states (submitted / approved / rejected) have no explicit
                # slug — slugify rather than defaulting to 'open', which would mislabel
                # them all as Open on the dashboard.
                raw_status = order_data['status']
                status = status_map.get(
                    raw_status, raw_status.lower().replace(' ', '-').replace('_', '-')
                )

                orders.append({
                    'order_request_id':  f"PO{order_data['potential_order_id']}",
                    'dealer_name':       dealer_name,
                    'status':            status,
                    'order_date':        order_data['order_date'].isoformat(),
                    'current_state_time': current_state_time.isoformat(),
                    'assigned_to':       order_data.get('assigned_username') or f"User {order_data['requested_by']}",
                })

            return {'success': True, 'recent_orders': orders}, 200

        except Exception as e:
            logger.exception("Error in /api/orders/recent")
            return {'success': False, 'msg': f'Error retrieving recent orders: {str(e)}'}, 400


@rest_api.route('/api/orders/submitted')
class SubmittedOrdersList(Resource):
    """App-submitted orders, read from the app's own submitted_orders store.

    These are orders raised in the mobile app that have not yet entered the warehouse
    chain (they sit at `submitted`). They live in the submitted_* tables, separate from
    the warehouse app's potential_order. Optional warehouse_id / company_id narrow the
    list, matching the filter bar on the other Order Tracking tabs.
    """

    @rest_api.doc(params={'warehouse_id': 'Warehouse ID', 'company_id': 'Company ID',
                          'stage': "Which tab: 'submitted' (awaiting upload) | 'download' (ready/done)",
                          'dealer_id': 'Dealer ID'})
    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        try:
            warehouse_id = request.args.get('warehouse_id', type=int)
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403
            stage        = request.args.get('stage', 'submitted')
            dealer_id    = request.args.get('dealer_id', type=int)

            # The two-stage DMS pipeline maps onto dms_status:
            #   'submitted' tab  -> submitted / re_submitted  (awaiting part-convertor upload)
            #   'download'  tab  -> ready / done              (DMS ready / already downloaded)
            if stage == 'download':
                where = ["so.dms_status IN ('ready','done')"]
            else:
                where = ["so.dms_status IN ('submitted','re_submitted')"]
            params = []
            if dealer_id:
                where.append("so.dealer_id = %s")
                params.append(dealer_id)
            if warehouse_id:
                where.append("so.warehouse_id = %s")
                params.append(warehouse_id)
            cf_sql, cf_params = company_filter_sql(company_ids, alias='so')
            where.append(cf_sql)
            params.extend(cf_params)
            clause = "WHERE " + " AND ".join(where)

            rows = mysql_manager.execute_query(
                f"""SELECT so.submitted_order_id AS order_id, so.order_number, so.status,
                           so.dms_status, so.reject_note,
                           so.source, so.dealer_id, d.name AS dealer_name,
                           so.company_id, c.name AS company_name,
                           so.warehouse_id, w.name AS warehouse_name,
                           so.notes, so.created_at, so.submitted_at, so.expected_delivery_date,
                           -- Who raised the order in the app. These are sales executives
                           -- (every submitted order is created by one), so this answers
                           -- "whose order is this" without going via the dealer, whose
                           -- assigned executive can differ from whoever actually raised it.
                           so.created_by AS created_by_user_id,
                           su.name AS sales_executive_name,
                           su.role AS sales_executive_role,
                           (SELECT COUNT(*) FROM submitted_order_products p
                             WHERE p.submitted_order_id = so.submitted_order_id) AS item_count
                    FROM submitted_orders so
                    LEFT JOIN company   c ON c.company_id   = so.company_id
                    LEFT JOIN dealer    d ON d.dealer_id    = so.dealer_id
                    LEFT JOIN warehouse w ON w.warehouse_id = so.warehouse_id
                    LEFT JOIN users     su ON su.id         = so.created_by
                    {clause}
                    ORDER BY so.created_at DESC""",
                tuple(params),
            ) or []

            # Photos live in submitted_order_attachments (one per order in practice, but
            # the schema allows several). Fetch them all in one query and group by order
            # so the tab can show a "view photo" action without an extra round-trip.
            atts_by_order = defaultdict(list)
            order_ids = [r['order_id'] for r in rows]
            if order_ids:
                placeholders = ",".join(["%s"] * len(order_ids))
                att_rows = mysql_manager.execute_query(
                    f"""SELECT attachment_id, submitted_order_id, mime_type
                        FROM submitted_order_attachments
                        WHERE submitted_order_id IN ({placeholders})
                        ORDER BY attachment_id""",
                    tuple(order_ids),
                ) or []
                for a in att_rows:
                    atts_by_order[a['submitted_order_id']].append({
                        'attachment_id': a['attachment_id'],
                        'mime_type':     a['mime_type'],
                        # Web-auth photo route; the UI fetches it as an authenticated blob.
                        'url': f"/orders/submitted/{a['submitted_order_id']}/photo/{a['attachment_id']}",
                    })

            from api.modules.fulfillment.order import dms

            def _iso(v):
                return v.isoformat() if hasattr(v, 'isoformat') else v

            orders = [{
                'order_id':               r['order_id'],
                'order_number':           r['order_number'],
                'status':                 r['status'],
                'dms_status':             r['dms_status'],
                'reject_note':            r['reject_note'],
                'source':                 r['source'],
                # Whether a DMS file can be generated for this order's company (Hero only
                # for now). False => the tab shows a placeholder instead of Download.
                'dms_available':          dms.has_dms_format(r['company_name']),
                'dealer_id':              r['dealer_id'],
                'dealer_name':            r['dealer_name'] or f"Dealer {r['dealer_id']}",
                'company_id':             r['company_id'],
                'company_name':           r['company_name'],
                'warehouse_id':           r['warehouse_id'],
                'warehouse_name':         r['warehouse_name'],
                'item_count':             r['item_count'],
                # The sales executive who raised the order in the app.
                'created_by_user_id':     r['created_by_user_id'],
                'sales_executive_name':   r['sales_executive_name'],
                'notes':                  r['notes'],
                'created_at':             _iso(r['created_at']),
                'submitted_at':           _iso(r['submitted_at']),
                'expected_delivery_date': _iso(r['expected_delivery_date']),
                'attachments':            atts_by_order.get(r['order_id'], []),
            } for r in rows]

            return {'success': True, 'orders': orders}, 200

        except Exception as e:
            logger.exception("Error in /api/orders/submitted")
            return {'success': False, 'msg': f'Error retrieving submitted orders: {str(e)}'}, 400


@rest_api.route('/api/orders/submitted/<int:order_id>/photo/<int:attachment_id>')
class SubmittedOrderPhoto(Resource):
    """Serve a submitted order's photo to the web UI (behind web auth).

    The mobile app has its own photo route under /api/v1 (mobile auth); this is the
    web-authenticated equivalent so the Order Tracking → Submitted Orders tab can show
    the paper-order image. The UI fetches it as an authenticated blob (an <img> tag
    can't send the bearer token), so this returns the raw image bytes.
    """

    @rest_api.response(404, 'Not found', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user, order_id, attachment_id):
        att = mysql_manager.execute_query(
            """SELECT attachment_id, submitted_order_id, file_path, mime_type
               FROM submitted_order_attachments WHERE attachment_id = %s""",
            (attachment_id,),
        )
        att = att[0] if att else None
        # The id pair must be consistent — you can't fetch order A's photo via order B.
        if not att or att['submitted_order_id'] != order_id:
            return {'success': False, 'msg': 'attachment not found'}, 404
        try:
            resp = media.send_media(att['file_path'], att['mime_type'])
        except media.MediaError as e:
            return {'success': False, 'msg': str(e)}, 400
        if resp is None:
            return {'success': False, 'msg': 'attachment file is missing'}, 404
        return resp


@rest_api.route('/api/orders/submitted/<int:order_id>/part-convertor')
class SubmittedOrderPartConvertor(Resource):
    """Upload the part-convertor sheet for a photo order (multipart, field 'file').

    A part_convertor user reads the paper-order photo and fills a sheet
    (S.NO. | PART# | QTY | DESC. | MRP); this parses it and writes the order's line
    items into submitted_order_products, so a photo order ends up with the same lines
    an itemised order already has. Re-uploading replaces the current lines.
    """

    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        from api.modules.fulfillment.order import dms

        head = mysql_manager.execute_query(
            "SELECT submitted_order_id FROM submitted_orders WHERE submitted_order_id = %s",
            (order_id,),
        )
        if not head:
            return {'success': False, 'msg': 'order not found'}, 404

        f = request.files.get('file')
        if f is None:
            return {'success': False, 'msg': 'an Excel file is required (form field "file")'}, 422
        try:
            items = dms.parse_part_convertor(f)
        except dms.PartConvertorError as e:
            return {'success': False, 'msg': str(e)}, 422

        now = datetime.utcnow()
        with mysql_manager.get_cursor() as cursor:
            # Replace the whole line set — the operator's sheet is the source of truth.
            cursor.execute(
                "DELETE FROM submitted_order_products WHERE submitted_order_id = %s", (order_id,)
            )
            for it in items:
                cursor.execute(
                    """INSERT INTO submitted_order_products
                         (submitted_order_id, product_id, sku_code, product_name, uom,
                          quantity, mrp, created_at, updated_at)
                       VALUES (%s,
                               (SELECT product_id FROM product WHERE product_string = %s LIMIT 1),
                               %s, %s, NULL, %s, %s, %s, %s)""",
                    (order_id, it['sku_code'], it['sku_code'], it['product_name'],
                     it['quantity'], it['mrp'], now, now),
                )
            # Uploading the part convertor advances the order to the download stage
            # (dms_status='ready') and clears any prior rejection note.
            cursor.execute(
                """UPDATE submitted_orders
                     SET dms_status = 'ready', reject_note = NULL, updated_at = %s
                   WHERE submitted_order_id = %s""",
                (now, order_id),
            )
            cursor.execute(
                """INSERT INTO submitted_order_status_history
                     (submitted_order_id, status, changed_by, changed_at)
                   VALUES (%s, 'ready', %s, %s)""",
                (order_id, getattr(current_user, 'id', None), now),
            )

        return {'success': True, 'item_count': len(items)}, 200


@rest_api.route('/api/orders/inventory')
class DmsInventory(Resource):
    """Stock on hand for the DMS download step.

    Same permission as downloading a DMS file (a logged-in active user on this
    dashboard), because it is the same operator doing both: they upload the stock sheet
    they are picking from, then download the files it can cover.

    GET  — freshness summary, for the banner and to warn before a download is attempted.
    POST — apply an uploaded stock sheet (multipart, field 'file').
    """

    @token_required
    @active_required
    def get(self, current_user):
        from api.modules.fulfillment.order import temp_inventory
        return {'success': True, 'inventory': temp_inventory.status()}, 200

    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def post(self, current_user):
        from api.modules.fulfillment.order import temp_inventory

        f = request.files.get('file')
        if f is None:
            return {'success': False,
                    'msg': 'an Excel file is required (form field "file")'}, 422
        try:
            items = temp_inventory.parse_inventory_sheet(f)
        except temp_inventory.InventorySheetError as e:
            return {'success': False, 'msg': str(e)}, 422

        updated, inserted, zeroed = temp_inventory.replace_stock(items)
        return {
            'success': True,
            'parts_in_sheet': len(items),
            'updated': updated,
            'inserted': inserted,
            # Named plainly because it surprises people: a part the sheet omits is taken
            # to be out of stock, not left at its previous quantity.
            'zeroed_not_in_sheet': zeroed,
            'inventory': temp_inventory.status(),
        }, 200


@rest_api.route('/api/orders/dealers')
class OrderDealerOptions(Resource):
    """Active dealers, for the dealer picker when raising an order by hand.

    A dedicated route rather than /api/admin/dealers because that one is admin-only,
    and the operator who raises these orders is not necessarily an admin — the rest of
    this dashboard asks only for a logged-in active user. Read-only and no more than a
    picker needs. `company_id` narrows it, since an order's dealer must belong to the
    company it is raised against.
    """

    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user):
        where, params = ["(d.status IS NULL OR d.status = 'active')"], []
        raw = (request.args.get('company_id') or '').strip()
        if raw and raw != 'all':
            try:
                params.append(int(raw))
            except ValueError:
                return {'success': False, 'msg': 'company_id must be a number'}, 422
            # A dealer with no company is offered for any company: unassigned dealers are
            # still real, and create validates the pairing the same lenient way.
            where.append("(d.company_id = %s OR d.company_id IS NULL)")
        rows = mysql_manager.execute_query(
            f"""SELECT d.dealer_id, d.name, d.dealer_code, d.town
                FROM dealer d WHERE {' AND '.join(where)} ORDER BY d.name""",
            tuple(params)) or []
        return {'success': True, 'dealers': [{
            'dealer_id': r['dealer_id'], 'name': r['name'],
            'dealer_code': r['dealer_code'] or '', 'town': r['town'] or '',
        } for r in rows]}, 200


@rest_api.route('/api/orders/submitted/manual')
class SubmittedOrderManualCreate(Resource):
    """Raise an order from the web side, with its parts taken from an uploaded sheet.

    For parts that arrived outside the app — a phone or WhatsApp order the rep never
    entered. The operator fills in the order details and attaches the same parts sheet
    the part convertor uses, and the result is an ordinary submitted order: it lands in
    the Download DMS input list alongside every other one, and its DMS file is fetched
    through the existing per-order route rather than a separate download path.

    It goes straight in at dms_status='ready' for the same reason an itemised app order
    does — the lines are already present, so there is no part-convertor step to wait for.

    Multipart: 'file' plus dealer_id, company_id, and optionally warehouse_id, notes,
    expected_delivery_date.
    """

    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def post(self, current_user):
        from api.modules.fulfillment.order import dms
        from api.modules.fulfillment.order.constants import OrderStatus

        f = request.files.get('file')
        if f is None:
            return {'success': False,
                    'msg': 'a parts Excel file is required (form field "file")'}, 422

        def _int(name):
            raw = (request.form.get(name) or '').strip()
            if not raw:
                return None, None
            try:
                return int(raw), None
            except ValueError:
                return None, f'{name} must be a number'

        dealer_id, err = _int('dealer_id')
        if err:
            return {'success': False, 'msg': err}, 422
        company_id, err2 = _int('company_id')
        if err2:
            return {'success': False, 'msg': err2}, 422
        warehouse_id, err3 = _int('warehouse_id')
        if err3:
            return {'success': False, 'msg': err3}, 422
        if dealer_id is None:
            return {'success': False, 'msg': 'a dealer is required'}, 422
        if company_id is None:
            return {'success': False, 'msg': 'a company is required'}, 422

        dealer = mysql_manager.execute_query(
            "SELECT dealer_id, name, status, company_id FROM dealer WHERE dealer_id = %s",
            (dealer_id,))
        if not dealer or (dealer[0].get('status') or 'active') != 'active':
            return {'success': False,
                    'msg': f'dealer {dealer_id} not found or inactive'}, 422
        # Mirrors create_order: an order whose dealer belongs to another company would be
        # invisible to the people who could act on it.
        if dealer[0].get('company_id') not in (None, company_id):
            return {'success': False,
                    'msg': f"{dealer[0]['name']} does not belong to the selected company"}, 422

        company = mysql_manager.execute_query(
            "SELECT company_id, name FROM company WHERE company_id = %s", (company_id,))
        if not company:
            return {'success': False, 'msg': f'company {company_id} not found'}, 422
        if warehouse_id is not None and not mysql_manager.execute_query(
                "SELECT warehouse_id FROM warehouse WHERE warehouse_id = %s", (warehouse_id,)):
            return {'success': False, 'msg': f'warehouse {warehouse_id} not found'}, 422

        # Parsed before anything is written, so a sheet we can't read leaves no order
        # behind. Unknown part numbers are deliberately NOT rejected — same as the
        # part-convertor upload, whose sheets routinely name parts the catalogue lacks;
        # the DMS file needs the part number, not a catalogue match.
        try:
            items = dms.parse_part_convertor(f)
        except dms.PartConvertorError as e:
            return {'success': False, 'msg': str(e)}, 422

        expected = (request.form.get('expected_delivery_date') or '').strip() or None
        notes = (request.form.get('notes') or '').strip() or None
        created_by = getattr(current_user, 'id', None)
        now = datetime.utcnow()

        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT INTO submitted_orders
                     (dealer_id, warehouse_id, company_id, status, source, dms_status,
                      requested_by, created_by, submitted_at, expected_delivery_date,
                      notes, created_at, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (dealer_id, warehouse_id, company_id, OrderStatus.SUBMITTED.value,
                 'itemised', 'ready', created_by, created_by, now, expected, notes,
                 now, now))
            order_id = cursor.lastrowid
            order_number = f"ORD-{order_id:06d}"
            cursor.execute(
                "UPDATE submitted_orders SET order_number = %s WHERE submitted_order_id = %s",
                (order_number, order_id))
            for it in items:
                cursor.execute(
                    """INSERT INTO submitted_order_products
                         (submitted_order_id, product_id, sku_code, product_name, uom,
                          quantity, mrp, created_at, updated_at)
                       VALUES (%s,
                               (SELECT product_id FROM product
                                 WHERE product_string = %s LIMIT 1),
                               %s, %s, NULL, %s, %s, %s, %s)""",
                    (order_id, it['sku_code'], it['sku_code'], it['product_name'],
                     it['quantity'], it['mrp'], now, now))
            cursor.execute(
                """INSERT INTO submitted_order_status_history
                     (submitted_order_id, status, changed_by, changed_at)
                   VALUES (%s, 'ready', %s, %s)""",
                (order_id, created_by, now))

        return {'success': True, 'order_id': order_id, 'order_number': order_number,
                'item_count': len(items),
                'dms_available': dms.has_dms_format(company[0]['name'])}, 201


@rest_api.route('/api/orders/submitted/<int:order_id>/dms-file')
class SubmittedOrderDmsFile(Resource):
    """Download the company's DMS upload file for a submitted order.

    Built from the order's lines in submitted_order_products (present for itemised
    orders, or entered via the part-convertor upload for photo orders). Returns a CSV
    laid out for the order's company (Hero known; others fall back to Hero's layout).
    """

    @rest_api.response(400, 'Error', dash_error_response)
    @rest_api.response(409, 'No parts yet', dash_error_response)
    @token_required
    @active_required
    def get(self, current_user, order_id):
        from api.modules.fulfillment.order import dms

        head = mysql_manager.execute_query(
            """SELECT so.submitted_order_id, so.order_number, c.name AS company_name
               FROM submitted_orders so
               LEFT JOIN company c ON c.company_id = so.company_id
               WHERE so.submitted_order_id = %s""",
            (order_id,),
        )
        if not head:
            return {'success': False, 'msg': 'order not found'}, 404
        head = head[0]

        # The DMS layout is company-specific; only Hero's is known so far. For any other
        # company there's no file to generate yet — the UI shows a placeholder instead.
        if not dms.has_dms_format(head['company_name']):
            return {
                'success': False,
                'msg': f"DMS file for {head['company_name'] or 'this company'} "
                       f"isn't available yet — only Hero is configured so far.",
            }, 501

        items = mysql_manager.execute_query(
            """SELECT submitted_order_product_id, sku_code, product_name, quantity, mrp,
                      dms_quantity
               FROM submitted_order_products
               WHERE submitted_order_id = %s
               ORDER BY submitted_order_product_id""",
            (order_id,),
        ) or []
        if not items:
            return {
                'success': False,
                'msg': 'this order has no parts yet — upload the part-convertor file first',
            }, 409

        from api.modules.fulfillment.order import temp_inventory

        # An order already downloaded replays its stored allocation. It must NOT allocate
        # again: the stock it consumed is already gone, so a second pass would deduct the
        # same parts twice and — reading the reduced quantities — hand over a SMALLER file
        # than the one the DMS already received. Replaying also means a re-download is not
        # subject to the freshness rule, because it takes nothing new out of stock.
        already_allocated = any(i['dms_quantity'] is not None for i in items)
        shortfalls = []

        if already_allocated:
            lines = [dict(i, quantity=i['dms_quantity']) for i in items
                     if (i['dms_quantity'] or 0) > 0]
        else:
            # Stock older than the freshness window cannot be allocated against — someone
            # has probably picked from it since, so the file would promise parts that are
            # no longer on the shelf.
            stale = temp_inventory.staleness_error()
            if stale:
                return {'success': False, 'msg': stale}, 409

            lines, shortfalls = temp_inventory.allocate(items)
            if not lines:
                return {
                    'success': False,
                    'msg': 'none of the parts on this order are in stock — '
                           'upload current inventory, or reject the order.',
                }, 409

            supplied = {ln['submitted_order_product_id']: ln['quantity'] for ln in lines}
            now = datetime.utcnow()
            with mysql_manager.get_cursor() as cursor:
                # Every line is stamped, including the ones stock could not cover (0), so
                # the replay above reproduces exactly this set of rows.
                for it in items:
                    cursor.execute(
                        "UPDATE submitted_order_products SET dms_quantity = %s "
                        "WHERE submitted_order_product_id = %s",
                        (supplied.get(it['submitted_order_product_id'], 0),
                         it['submitted_order_product_id']))
                # Downloading marks the order Done (dms_status='done') but it STAYS in the
                # Download DMS tab, so it can still be rejected afterwards. Reject sends it
                # back to Submitted Orders; a fresh part-convertor upload brings it forward.
                cursor.execute(
                    "UPDATE submitted_orders SET dms_status = 'done', updated_at = %s "
                    "WHERE submitted_order_id = %s",
                    (now, order_id),
                )
                cursor.execute(
                    """INSERT INTO submitted_order_status_history
                         (submitted_order_id, status, changed_by, changed_at)
                       VALUES (%s, 'done', %s, %s)""",
                    (order_id, getattr(current_user, 'id', None), now),
                )

        csv_text = dms.build_dms_csv(head['company_name'], lines)

        buf = io.BytesIO(csv_text.encode('utf-8-sig'))  # BOM so Excel opens it cleanly
        buf.seek(0)
        filename = f"DMS_{head['order_number'] or order_id}.csv"
        resp = send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=filename)
        # A short-supplied file looks normal, so the fact that it was trimmed has to be
        # told to the operator. The body is the CSV, so it travels in headers instead.
        if shortfalls:
            resp.headers['X-DMS-Shortfall-Count'] = str(len(shortfalls))
            resp.headers['X-DMS-Shortfall-Summary'] = '; '.join(
                f"{s['part_number']} {s['supplied']}/{s['ordered']}"
                for s in shortfalls[:12])
            resp.headers['Access-Control-Expose-Headers'] = (
                'Content-Disposition, X-DMS-Shortfall-Count, X-DMS-Shortfall-Summary')
        return resp


@rest_api.route('/api/orders/submitted/<int:order_id>/reject')
class SubmittedOrderReject(Resource):
    """Reject a DMS-input order from the Download DMS tab, with a note.

    The order returns to the Submitted Orders tab as `re_submitted`, its parts are
    cleared, and the note is stored so the part_convertor user knows what to fix — they
    then re-upload the part convertor to bring it forward again.
    """

    @rest_api.response(400, 'Error', dash_error_response)
    @token_required
    @active_required
    def post(self, current_user, order_id):
        body = request.get_json(silent=True) or {}
        note = (body.get('note') or '').strip()
        if not note:
            return {'success': False, 'msg': 'a rejection note is required'}, 422

        head = mysql_manager.execute_query(
            "SELECT dms_status FROM submitted_orders WHERE submitted_order_id = %s",
            (order_id,),
        )
        if not head:
            return {'success': False, 'msg': 'order not found'}, 404
        if head[0]['dms_status'] not in ('ready', 'done'):
            return {'success': False, 'msg': 'only orders in the Download DMS tab can be rejected'}, 409

        now = datetime.utcnow()
        with mysql_manager.get_cursor() as cursor:
            # Clear the parts — the rejected data was wrong, so the order starts fresh.
            cursor.execute(
                "DELETE FROM submitted_order_products WHERE submitted_order_id = %s", (order_id,)
            )
            cursor.execute(
                """UPDATE submitted_orders
                     SET dms_status = 're_submitted', reject_note = %s, updated_at = %s
                   WHERE submitted_order_id = %s""",
                (note, now, order_id),
            )
            cursor.execute(
                """INSERT INTO submitted_order_status_history
                     (submitted_order_id, status, changed_by, changed_at)
                   VALUES (%s, 're_submitted', %s, %s)""",
                (order_id, getattr(current_user, 'id', None), now),
            )

        return {'success': True}, 200
