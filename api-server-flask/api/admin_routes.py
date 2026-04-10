"""
Admin Controls API — admin only.

Routes:
  GET    /api/admin/upload-batches               list batches with filters
  GET    /api/admin/upload-batches/<id>/details  full record details for a batch
  DELETE /api/admin/upload-batches/<id>          hard-delete a batch with business-rule enforcement

Deletion rules
--------------
Order uploads:
  - BLOCKED if any order in the batch has status:
    'Invoiced', 'Dispatch Ready', 'Completed', or 'Partially Completed'.
  - On success: hard-deletes potential_order_product, order_state_history
    (FK requirement), and potential_order rows; marks batch as 'reverted'.

Invoice uploads:
  - Always allowed (invoice can be reverted even when orders are already Invoiced).
  - Each affected order is rolled back to the state it held just before 'Invoiced',
    derived from order_state_history (defaults to 'Packed' if history is absent).
  - invoice_submitted flag on each order is reset to 0.
  - All invoice rows in the batch are hard-deleted; order_state_history is preserved
    for audit.
"""

from datetime import datetime
from flask import request
from flask_restx import Resource

from .routes import rest_api, token_required, active_required
from .db_manager import mysql_manager

# States that permanently block reverting an order upload.
BLOCKING_STATES = ('Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed')


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def _admin_required(f):
    """Ensure the current user carries the 'admin' role."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        current_user = args[1] if len(args) > 1 else kwargs.get('current_user')
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class DeleteBlockedError(Exception):
    """Raised when business rules prevent deletion of a batch."""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/upload-batches')
class UploadBatchList(Resource):

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        """
        List upload batches.

        Query params (all optional):
          upload_type  — 'orders' | 'invoices'
          warehouse_id — int
          company_id   — int
          date_from    — YYYY-MM-DD  (inclusive, based on uploaded_at)
          date_to      — YYYY-MM-DD  (inclusive)
        """
        try:
            upload_type  = request.args.get('upload_type')
            warehouse_id = request.args.get('warehouse_id', type=int)
            company_id   = request.args.get('company_id',   type=int)
            date_from    = request.args.get('date_from')
            date_to      = request.args.get('date_to')

            query = """
                SELECT
                    ub.id,
                    ub.upload_type,
                    ub.filename,
                    ub.record_count,
                    ub.status,
                    ub.uploaded_at,
                    ub.reverted_at,
                    w.name       AS warehouse_name,
                    c.name       AS company_name,
                    u.username   AS uploaded_by_name,
                    rv.username  AS reverted_by_name
                FROM upload_batches ub
                LEFT JOIN warehouse w  ON ub.warehouse_id = w.warehouse_id
                LEFT JOIN company   c  ON ub.company_id   = c.company_id
                LEFT JOIN users     u  ON ub.uploaded_by  = u.id
                LEFT JOIN users     rv ON ub.reverted_by  = rv.id
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
            if date_from:
                query += " AND DATE(ub.uploaded_at) >= %s"
                params.append(date_from)
            if date_to:
                query += " AND DATE(ub.uploaded_at) <= %s"
                params.append(date_to)

            query += " ORDER BY ub.uploaded_at DESC"

            rows = mysql_manager.execute_query(query, params if params else None)

            batches = [
                {
                    'id':             r['id'],
                    'upload_type':    r['upload_type'],
                    'filename':       r['filename'],
                    'record_count':   r['record_count'],
                    'status':         r['status'],
                    'uploaded_at':    r['uploaded_at'].isoformat() if r['uploaded_at'] else None,
                    'reverted_at':    r['reverted_at'].isoformat() if r['reverted_at'] else None,
                    'warehouse_name': r['warehouse_name'],
                    'company_name':   r['company_name'],
                    'uploaded_by':    r['uploaded_by_name'],
                    'reverted_by':    r['reverted_by_name'],
                }
                for r in (rows or [])
            ]

            return {'success': True, 'batches': batches}, 200

        except Exception as e:
            return {'success': False, 'msg': str(e)}, 500


@rest_api.route('/api/admin/upload-batches/<int:batch_id>/details')
class UploadBatchDetails(Resource):

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user, batch_id):
        """Return the full record details for a single upload batch."""
        try:
            batch_rows = mysql_manager.execute_query(
                "SELECT * FROM upload_batches WHERE id = %s", (batch_id,)
            )
            if not batch_rows:
                return {'success': False, 'msg': 'Batch not found.'}, 404

            batch = batch_rows[0]
            records = _fetch_batch_records(batch['id'], batch['upload_type'])

            return {
                'success': True,
                'batch': {
                    'id':           batch['id'],
                    'upload_type':  batch['upload_type'],
                    'filename':     batch['filename'],
                    'record_count': batch['record_count'],
                    'status':       batch['status'],
                    'uploaded_at':  batch['uploaded_at'].isoformat() if batch['uploaded_at'] else None,
                },
                'records': records,
            }, 200

        except Exception as e:
            return {'success': False, 'msg': str(e)}, 500


@rest_api.route('/api/admin/upload-batches/<int:batch_id>')
class UploadBatchDelete(Resource):

    @token_required
    @active_required
    @_admin_required
    def delete(self, current_user, batch_id):
        """
        Hard-delete all data belonging to this batch.

        Returns 409 Conflict when an order upload cannot be reverted
        because orders have already progressed past the Invoiced state.
        """
        try:
            batch_rows = mysql_manager.execute_query(
                "SELECT * FROM upload_batches WHERE id = %s", (batch_id,)
            )
            if not batch_rows:
                return {'success': False, 'msg': 'Batch not found.'}, 404

            batch = batch_rows[0]

            if batch['status'] == 'reverted':
                return {'success': False, 'msg': 'This upload has already been deleted.'}, 400

            upload_type = batch['upload_type']

            if upload_type == 'orders':
                _delete_order_batch(batch_id)
            elif upload_type == 'invoices':
                _delete_invoice_batch(batch_id)
            else:
                return {'success': False, 'msg': f'Unknown upload type: {upload_type}'}, 400

            mysql_manager.execute_query(
                """UPDATE upload_batches
                   SET status = 'reverted', reverted_by = %s, reverted_at = %s
                   WHERE id = %s""",
                (current_user.id, datetime.utcnow(), batch_id),
                fetch=False,
            )

            return {
                'success': True,
                'msg': f'Upload #{batch_id} ({upload_type}) has been permanently deleted.',
            }, 200

        except DeleteBlockedError as e:
            return {'success': False, 'msg': str(e)}, 409

        except Exception as e:
            return {'success': False, 'msg': str(e)}, 500


# ---------------------------------------------------------------------------
# Helpers — record fetching
# ---------------------------------------------------------------------------

def _fetch_batch_records(batch_id: int, upload_type: str) -> list:
    """Return the detailed rows for a batch depending on its upload type."""

    if upload_type == 'orders':
        rows = mysql_manager.execute_query(
            """
            SELECT
                po.potential_order_id,
                po.original_order_id,
                po.b2b_po_number,
                po.order_type,
                po.status,
                po.order_date,
                po.vin_number,
                po.shipping_address,
                po.purchaser_name,
                po.purchaser_sap_code,
                po.invoice_submitted,
                d.name         AS dealer_name,
                d.dealer_code  AS dealer_code,
                w.name         AS warehouse_name,
                c.name         AS company_name,
                (
                    SELECT COUNT(*)
                    FROM potential_order_product pop
                    WHERE pop.potential_order_id = po.potential_order_id
                ) AS product_count,
                (
                    SELECT COALESCE(SUM(pop.quantity), 0)
                    FROM potential_order_product pop
                    WHERE pop.potential_order_id = po.potential_order_id
                ) AS total_quantity
            FROM potential_order po
            LEFT JOIN dealer    d ON po.dealer_id    = d.dealer_id
            LEFT JOIN warehouse w ON po.warehouse_id = w.warehouse_id
            LEFT JOIN company   c ON po.company_id   = c.company_id
            WHERE po.upload_batch_id = %s
            ORDER BY po.potential_order_id
            """,
            (batch_id,),
        )
        return [
            {
                'potential_order_id': r['potential_order_id'],
                'original_order_id':  r['original_order_id'],
                'b2b_po_number':      r['b2b_po_number'],
                'order_type':         r['order_type'],
                'status':             r['status'],
                'order_date':         r['order_date'].isoformat() if r['order_date'] else None,
                'vin_number':         r['vin_number'],
                'shipping_address':   r['shipping_address'],
                'purchaser_name':     r['purchaser_name'],
                'purchaser_sap_code': r['purchaser_sap_code'],
                'invoice_submitted':  bool(r['invoice_submitted']),
                'dealer_name':        r['dealer_name'],
                'dealer_code':        r['dealer_code'],
                'warehouse_name':     r['warehouse_name'],
                'company_name':       r['company_name'],
                'product_count':      int(r['product_count'] or 0),
                'total_quantity':     int(r['total_quantity'] or 0),
            }
            for r in (rows or [])
        ]

    elif upload_type == 'invoices':
        rows = mysql_manager.execute_query(
            """
            SELECT
                inv.invoice_id,
                inv.invoice_number,
                inv.original_order_id,
                inv.invoice_date,
                inv.invoice_type,
                inv.invoice_header_type,
                inv.total_invoice_amount,
                inv.b2b_purchase_order_number,
                inv.b2b_order_type,
                inv.account_tin,
                inv.cash_customer_name,
                inv.contact_first_name,
                inv.contact_last_name,
                inv.customer_category,
                inv.round_off_amount,
                inv.irn_number,
                inv.irn_status,
                inv.cancellation_date,
                inv.potential_order_id,
                po.status      AS order_status,
                d.name         AS dealer_name,
                d.dealer_code  AS dealer_code,
                w.name         AS warehouse_name,
                c.name         AS company_name
            FROM invoice inv
            LEFT JOIN potential_order po ON inv.potential_order_id = po.potential_order_id
            LEFT JOIN dealer    d ON po.dealer_id     = d.dealer_id
            LEFT JOIN warehouse w ON inv.warehouse_id = w.warehouse_id
            LEFT JOIN company   c ON inv.company_id   = c.company_id
            WHERE inv.upload_batch_id = %s
            ORDER BY inv.invoice_id
            """,
            (batch_id,),
        )
        return [
            {
                'invoice_id':                  r['invoice_id'],
                'invoice_number':              r['invoice_number'],
                'original_order_id':           r['original_order_id'],
                'invoice_date':                r['invoice_date'].isoformat() if r['invoice_date'] else None,
                'invoice_type':                r['invoice_type'],
                'invoice_header_type':         r['invoice_header_type'],
                'total_invoice_amount':        float(r['total_invoice_amount']) if r['total_invoice_amount'] is not None else None,
                'b2b_purchase_order_number':   r['b2b_purchase_order_number'],
                'b2b_order_type':              r['b2b_order_type'],
                'account_tin':                 r['account_tin'],
                'cash_customer_name':          r['cash_customer_name'],
                'contact_first_name':          r['contact_first_name'],
                'contact_last_name':           r['contact_last_name'],
                'customer_category':           r['customer_category'],
                'round_off_amount':            float(r['round_off_amount']) if r['round_off_amount'] is not None else None,
                'irn_number':                  r['irn_number'],
                'irn_status':                  r['irn_status'],
                'cancellation_date':           r['cancellation_date'].isoformat() if r['cancellation_date'] else None,
                'potential_order_id':          r['potential_order_id'],
                'order_status':                r['order_status'],
                'dealer_name':                 r['dealer_name'],
                'dealer_code':                 r['dealer_code'],
                'warehouse_name':              r['warehouse_name'],
                'company_name':                r['company_name'],
            }
            for r in (rows or [])
        ]

    return []


# ---------------------------------------------------------------------------
# Helpers — deletion
# ---------------------------------------------------------------------------

def _delete_order_batch(batch_id: int) -> None:
    """
    Hard-delete an order upload batch.

    Raises DeleteBlockedError if any order has progressed to
    'Invoiced' or any state beyond it.
    """
    blocking = mysql_manager.execute_query(
        f"""
        SELECT potential_order_id, original_order_id, status
        FROM potential_order
        WHERE upload_batch_id = %s
          AND status IN ({', '.join(['%s'] * len(BLOCKING_STATES))})
        """,
        (batch_id, *BLOCKING_STATES),
    )

    if blocking:
        sample_ids = ', '.join(str(r['original_order_id']) for r in blocking[:5])
        suffix = f' and {len(blocking) - 5} more' if len(blocking) > 5 else ''
        raise DeleteBlockedError(
            f"Cannot delete this upload. {len(blocking)} order(s) are in a state "
            f"that cannot be reverted ('{blocking[0]['status']}' or later). "
            f"Affected orders: {sample_ids}{suffix}."
        )

    # Delete child records in FK-safe order.
    # order_state_history is deleted here because the FK prevents deleting the
    # parent potential_order row while history rows still reference it.
    mysql_manager.execute_query(
        """DELETE osh FROM order_state_history osh
           INNER JOIN potential_order po ON osh.potential_order_id = po.potential_order_id
           WHERE po.upload_batch_id = %s""",
        (batch_id,),
        fetch=False,
    )
    mysql_manager.execute_query(
        """DELETE pop FROM potential_order_product pop
           INNER JOIN potential_order po ON pop.potential_order_id = po.potential_order_id
           WHERE po.upload_batch_id = %s""",
        (batch_id,),
        fetch=False,
    )
    mysql_manager.execute_query(
        "DELETE FROM potential_order WHERE upload_batch_id = %s",
        (batch_id,),
        fetch=False,
    )


def _delete_invoice_batch(batch_id: int) -> None:
    """
    Hard-delete an invoice upload batch and roll back affected orders.

    For each order linked to an invoice in this batch:
      1. Look up order_state_history to find the most recent state
         recorded before 'Invoiced' — this becomes the rollback target.
         Falls back to 'Packed' when no prior history exists.
      2. Update the order's status to that state and clear invoice_submitted.

    order_state_history rows are intentionally left intact for audit.
    """
    invoices = mysql_manager.execute_query(
        "SELECT invoice_id, potential_order_id FROM invoice WHERE upload_batch_id = %s",
        (batch_id,),
    )
    if not invoices:
        return

    # Deduplicate — one order may appear across multiple invoices in the batch.
    order_ids = list({r['potential_order_id'] for r in invoices if r['potential_order_id']})
    now = datetime.utcnow()

    for order_id in order_ids:
        previous_state = _state_before_invoiced(order_id)
        mysql_manager.execute_query(
            """UPDATE potential_order
               SET status = %s, invoice_submitted = 0, updated_at = %s
               WHERE potential_order_id = %s""",
            (previous_state, now, order_id),
            fetch=False,
        )

    mysql_manager.execute_query(
        "DELETE FROM invoice WHERE upload_batch_id = %s",
        (batch_id,),
        fetch=False,
    )


def _state_before_invoiced(potential_order_id: int) -> str:
    """
    Query order_state_history for the most recent state this order held
    before it was transitioned to 'Invoiced'.

    Returns 'Packed' as a safe default if no earlier state is found.
    """
    rows = mysql_manager.execute_query(
        """
        SELECT os.state_name
        FROM order_state_history osh
        JOIN order_state os ON osh.state_id = os.state_id
        WHERE osh.potential_order_id = %s
          AND os.state_name != 'Invoiced'
        ORDER BY osh.changed_at DESC
        LIMIT 1
        """,
        (potential_order_id,),
    )
    return rows[0]['state_name'] if rows else 'Packed'
