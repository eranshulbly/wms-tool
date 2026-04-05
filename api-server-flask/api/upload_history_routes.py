"""
Upload History API — admin only.
GET  /api/admin/upload-batches          list all batches
POST /api/admin/upload-batches/<id>/revert  hard-delete all records in a batch
"""

from datetime import datetime
from flask import request
from flask_restx import Resource

from .routes import rest_api, token_required, active_required
from .db_manager import mysql_manager


def _admin_required(f):
    """Decorator that ensures the current user has the admin role."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        # args = (self, current_user, ...)  after token_required fix
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        return f(*args, **kwargs)

    return wrapper


@rest_api.route('/api/admin/upload-batches')
class UploadBatchList(Resource):

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        """List all upload batches with warehouse, company, and uploader details."""
        try:
            upload_type = request.args.get('upload_type')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id = request.args.get('company_id', type=int)

            query = """
                SELECT
                    ub.id,
                    ub.upload_type,
                    ub.filename,
                    ub.record_count,
                    ub.status,
                    ub.uploaded_at,
                    ub.reverted_at,
                    w.name  AS warehouse_name,
                    c.name  AS company_name,
                    u.username AS uploaded_by_name,
                    rv.username AS reverted_by_name
                FROM upload_batches ub
                LEFT JOIN warehouse w  ON ub.warehouse_id  = w.warehouse_id
                LEFT JOIN company  c  ON ub.company_id    = c.company_id
                LEFT JOIN users    u  ON ub.uploaded_by   = u.id
                LEFT JOIN users    rv ON ub.reverted_by   = rv.id
                WHERE 1=1
            """
            params = []

            if upload_type:
                query += " AND ub.upload_type = %s"
                params.append(upload_type)
            if warehouse_id:
                query += " AND ub.warehouse_id = %s"
                params.append(warehouse_id)
            if company_id:
                query += " AND ub.company_id = %s"
                params.append(company_id)

            query += " ORDER BY ub.uploaded_at DESC"

            rows = mysql_manager.execute_query(query, params if params else None)

            batches = []
            for r in (rows or []):
                batches.append({
                    'id': r['id'],
                    'upload_type': r['upload_type'],
                    'filename': r['filename'],
                    'record_count': r['record_count'],
                    'status': r['status'],
                    'uploaded_at': r['uploaded_at'].isoformat() if r['uploaded_at'] else None,
                    'reverted_at': r['reverted_at'].isoformat() if r['reverted_at'] else None,
                    'warehouse_name': r['warehouse_name'],
                    'company_name': r['company_name'],
                    'uploaded_by': r['uploaded_by_name'],
                    'reverted_by': r['reverted_by_name'],
                })

            return {'success': True, 'batches': batches}, 200

        except Exception as e:
            return {'success': False, 'msg': str(e)}, 500


@rest_api.route('/api/admin/upload-batches/<int:batch_id>/revert')
class UploadBatchRevert(Resource):

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user, batch_id):
        """Hard-delete all records belonging to this batch and mark it reverted."""
        try:
            batch = mysql_manager.execute_query(
                "SELECT * FROM upload_batches WHERE id = %s", (batch_id,)
            )
            if not batch:
                return {'success': False, 'msg': 'Batch not found.'}, 404

            batch = batch[0]

            if batch['status'] == 'reverted':
                return {'success': False, 'msg': 'Batch has already been reverted.'}, 400

            upload_type = batch['upload_type']
            deleted_count = 0

            if upload_type == 'orders':
                # Check how many orders are in non-Open states (warn, but still delete)
                non_open = mysql_manager.execute_query(
                    """SELECT COUNT(*) as cnt FROM potential_order
                       WHERE upload_batch_id = %s AND status != 'Open'""",
                    (batch_id,)
                )
                non_open_count = non_open[0]['cnt'] if non_open else 0

                # Hard-delete: cascade removes potential_order_product, order_state_history, etc.
                # Delete child records first to respect FK constraints
                mysql_manager.execute_query(
                    """DELETE pop FROM potential_order_product pop
                       INNER JOIN potential_order po ON pop.potential_order_id = po.potential_order_id
                       WHERE po.upload_batch_id = %s""",
                    (batch_id,), fetch=False
                )
                mysql_manager.execute_query(
                    """DELETE osh FROM order_state_history osh
                       INNER JOIN potential_order po ON osh.potential_order_id = po.potential_order_id
                       WHERE po.upload_batch_id = %s""",
                    (batch_id,), fetch=False
                )
                result = mysql_manager.execute_query(
                    "DELETE FROM potential_order WHERE upload_batch_id = %s",
                    (batch_id,), fetch=False
                )
                deleted_count = batch['record_count']

            elif upload_type == 'invoices':
                non_open_count = 0
                mysql_manager.execute_query(
                    "DELETE FROM invoice WHERE upload_batch_id = %s",
                    (batch_id,), fetch=False
                )
                deleted_count = batch['record_count']

            # Mark batch as reverted
            mysql_manager.execute_query(
                """UPDATE upload_batches
                   SET status='reverted', reverted_by=%s, reverted_at=%s
                   WHERE id=%s""",
                (current_user.id, datetime.utcnow(), batch_id), fetch=False
            )

            msg = f'Batch reverted. {deleted_count} {upload_type} record(s) deleted.'
            if upload_type == 'orders' and non_open_count > 0:
                msg += f' Warning: {non_open_count} order(s) were past Open state.'

            return {'success': True, 'msg': msg, 'deleted_count': deleted_count}, 200

        except Exception as e:
            return {'success': False, 'msg': str(e)}, 500
