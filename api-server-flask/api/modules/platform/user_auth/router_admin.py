# -*- encoding: utf-8 -*-
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

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.permissions import (
    resolve_company_scope, company_filter_sql, CompanyAccessDenied,
)
from api.db_manager import mysql_manager, partition_filter
from api.core.logging import get_logger

logger = get_logger(__name__)

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
            date_from    = request.args.get('date_from')
            date_to      = request.args.get('date_to')
            try:
                company_ids = resolve_company_scope(
                    current_user, request.args.get('company_id', type=int))
            except CompanyAccessDenied as e:
                return {'success': False, 'msg': str(e)}, 403

            pf_ub_sql, pf_ub_params = partition_filter('upload_batches', alias='ub')
            query = f"""
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
                    u.name   AS uploaded_by_name,
                    rv.username  AS reverted_by_name
                FROM upload_batches ub
                LEFT JOIN warehouse w  ON ub.warehouse_id = w.warehouse_id
                LEFT JOIN company   c  ON ub.company_id   = c.company_id
                LEFT JOIN users     u  ON ub.uploaded_by  = u.id
                LEFT JOIN users     rv ON ub.reverted_by  = rv.id
                WHERE {pf_ub_sql}
            """
            params = list(pf_ub_params)

            if upload_type:
                query += " AND ub.upload_type = %s"
                params.append(upload_type)
            if warehouse_id:
                query += " AND ub.warehouse_id = %s"
                params.append(warehouse_id)
            cf_sql, cf_params = company_filter_sql(company_ids, alias='ub')
            query += f" AND {cf_sql}"
            params.extend(cf_params)
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
            pf_sql, pf_params = partition_filter('upload_batches')
            batch_rows = mysql_manager.execute_query(
                f"SELECT * FROM upload_batches WHERE id = %s AND {pf_sql}",
                (batch_id, *pf_params)
            )
            if not batch_rows:
                return {'success': False, 'msg': 'Batch not found.'}, 404

            batch   = batch_rows[0]
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
            pf_sql, pf_params = partition_filter('upload_batches')
            batch_rows = mysql_manager.execute_query(
                f"SELECT * FROM upload_batches WHERE id = %s AND {pf_sql}",
                (batch_id, *pf_params)
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
            elif upload_type == 'picklists':
                _delete_picklist_batch(batch_id)
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
        pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')
        pf_pop_sql, pf_pop_params = partition_filter('potential_order_product', alias='pop')
        rows = mysql_manager.execute_query(
            f"""
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
                      AND {pf_pop_sql}
                ) AS product_count,
                (
                    SELECT COALESCE(SUM(pop.quantity), 0)
                    FROM potential_order_product pop
                    WHERE pop.potential_order_id = po.potential_order_id
                      AND {pf_pop_sql}
                ) AS total_quantity
            FROM potential_order po
            LEFT JOIN dealer    d ON po.dealer_id    = d.dealer_id
            LEFT JOIN warehouse w ON po.warehouse_id = w.warehouse_id
            LEFT JOIN company   c ON po.company_id   = c.company_id
            WHERE po.upload_batch_id = %s
              AND {pf_po_sql}
            ORDER BY po.potential_order_id
            """,
            (batch_id, *pf_po_params, *pf_pop_params, *pf_pop_params),
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
        pf_inv_sql, pf_inv_params = partition_filter('invoice', alias='inv')
        pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')
        rows = mysql_manager.execute_query(
            f"""
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
                AND {pf_po_sql}
            LEFT JOIN dealer    d ON po.dealer_id     = d.dealer_id
            LEFT JOIN warehouse w ON inv.warehouse_id = w.warehouse_id
            LEFT JOIN company   c ON inv.company_id   = c.company_id
            WHERE inv.upload_batch_id = %s
              AND {pf_inv_sql}
            ORDER BY inv.invoice_id
            """,
            (batch_id, *pf_po_params, *pf_inv_params),
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

    elif upload_type == 'picklists':
        pf_po_sql, pf_po_params = partition_filter('potential_order', alias='po')
        rows = mysql_manager.execute_query(
            f"""
            SELECT
                pl.picklist_id,
                pl.original_order_id,
                pl.picklist_code,
                pl.picklist_date,
                pl.line_count,
                pl.qr_token,
                po.potential_order_id,
                po.status AS order_status,
                d.name    AS dealer_name,
                w.name    AS warehouse_name,
                c.name    AS company_name
            FROM order_picklist pl
            JOIN potential_order po
              ON po.potential_order_id = pl.potential_order_id
            LEFT JOIN dealer    d ON d.dealer_id    = po.dealer_id
            LEFT JOIN warehouse w ON w.warehouse_id = pl.warehouse_id
            LEFT JOIN company   c ON c.company_id   = pl.company_id
            WHERE pl.upload_batch_id = %s AND {pf_po_sql}
            ORDER BY pl.picklist_id
            """,
            (batch_id, *pf_po_params),
        )
        return [
            {
                'picklist_id':       r['picklist_id'],
                'original_order_id': r['original_order_id'],
                'picklist_code':     r['picklist_code'],
                'picklist_date':     r['picklist_date'].isoformat() if r['picklist_date'] else None,
                'line_count':        r['line_count'],
                'qr_token':          r['qr_token'],
                'potential_order_id': r['potential_order_id'],
                'order_status':      r['order_status'],
                'dealer_name':       r['dealer_name'],
                'warehouse_name':    r['warehouse_name'],
                'company_name':      r['company_name'],
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
    pf_po_sql,  pf_po_params  = partition_filter('potential_order', alias='po')
    pf_osh_sql, pf_osh_params = partition_filter('order_state_history', alias='osh')
    pf_pop_sql, pf_pop_params = partition_filter('potential_order_product', alias='pop')

    blocking = mysql_manager.execute_query(
        f"""
        SELECT po.potential_order_id, po.original_order_id, po.status
        FROM potential_order po
        WHERE po.upload_batch_id = %s
          AND po.status IN ({', '.join(['%s'] * len(BLOCKING_STATES))})
          AND {pf_po_sql}
        """,
        (batch_id, *BLOCKING_STATES, *pf_po_params),
    )

    if blocking:
        sample_ids = ', '.join(str(r['original_order_id']) for r in blocking[:5])
        suffix = f' and {len(blocking) - 5} more' if len(blocking) > 5 else ''
        raise DeleteBlockedError(
            f"Cannot delete this upload. {len(blocking)} order(s) are in a state "
            f"that cannot be reverted ('{blocking[0]['status']}' or later). "
            f"Affected orders: {sample_ids}{suffix}."
        )

    # Bug 18 fix: wrap all three DELETEs in a single connection so that a partial
    # failure leaves the DB unchanged instead of producing orphaned rows.
    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            f"""DELETE osh FROM order_state_history osh
               INNER JOIN potential_order po ON osh.potential_order_id = po.potential_order_id
               WHERE po.upload_batch_id = %s
                 AND {pf_osh_sql}
                 AND {pf_po_sql}""",
            (batch_id, *pf_osh_params, *pf_po_params),
        )
        cursor.execute(
            f"""DELETE pop FROM potential_order_product pop
               INNER JOIN potential_order po ON pop.potential_order_id = po.potential_order_id
               WHERE po.upload_batch_id = %s
                 AND {pf_pop_sql}
                 AND {pf_po_sql}""",
            (batch_id, *pf_pop_params, *pf_po_params),
        )
        cursor.execute(
            f"DELETE FROM potential_order WHERE upload_batch_id = %s AND {pf_po_sql}",
            (batch_id, *pf_po_params),
        )


def _delete_picklist_batch(batch_id: int) -> None:
    """Remove the pick-list documents a batch created, and any order it invented.

    Two halves, treated differently.

    The documents always go. So does any order the SAME upload created — a
    pick-list import creates the order when none exists, and leaving those behind
    made reverting useless: the batch disappeared from the upload history while
    the orders it had conjured stayed in Manage Orders with no way to reach them.
    An order that existed before the pick list is left alone; it belongs to
    whoever made it, and the pick list was only ever a document attached to it.

    What cannot be undone is the line replacement. The upload overwrote each
    matched order's potential_order_product rows and nothing records what they
    held first, so for a PRE-EXISTING order the lines stay as they are: removing
    them would not restore the old ones, it would just leave the order empty.

    order_picklist_scan rows are kept as an audit of scans that really happened.
    """
    # Orders this upload created, as opposed to ones it merely attached to.
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    own = mysql_manager.execute_query(
        f"""SELECT DISTINCT po.potential_order_id
              FROM potential_order po
             WHERE po.upload_batch_id = %s AND {pf_sql}""",
        (batch_id, *pf_params),
    ) or []
    own_ids = [r['potential_order_id'] for r in own]

    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            "DELETE FROM order_picklist WHERE upload_batch_id = %s", (batch_id,))

        if own_ids:
            placeholders = ', '.join(['%s'] * len(own_ids))
            args = tuple(own_ids)
            cursor.execute(
                f"DELETE FROM potential_order_product "
                f"WHERE potential_order_id IN ({placeholders})", args)
            cursor.execute(
                f"DELETE FROM order_state_history "
                f"WHERE potential_order_id IN ({placeholders})", args)
            cursor.execute(
                f"DELETE FROM `order` WHERE potential_order_id IN ({placeholders})", args)
            cursor.execute(
                f"DELETE FROM potential_order "
                f"WHERE potential_order_id IN ({placeholders})", args)


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
    pf_inv_sql, pf_inv_params = partition_filter('invoice')
    invoices = mysql_manager.execute_query(
        f"SELECT invoice_id, potential_order_id FROM invoice WHERE upload_batch_id = %s AND {pf_inv_sql}",
        (batch_id, *pf_inv_params),
    )
    if not invoices:
        return

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

        # The Order record was created when the invoice was uploaded.
        # Rolling back the invoice must also remove the Order.
        # Bug 35 fix: do NOT apply partition filter here.
        existing_order = mysql_manager.execute_query(
            "SELECT order_id FROM `order` WHERE potential_order_id = %s",
            (order_id,),
        )
        if existing_order:
            db_order_id = existing_order[0]['order_id']
            mysql_manager.execute_query(
                "DELETE FROM `order` WHERE order_id = %s",
                (db_order_id,),
                fetch=False,
            )

    mysql_manager.execute_query(
        f"DELETE FROM invoice WHERE upload_batch_id = %s AND {pf_inv_sql}",
        (batch_id, *pf_inv_params),
        fetch=False,
    )


def _state_before_invoiced(potential_order_id: int) -> str:
    """
    Query order_state_history for the most recent state this order held
    before it was transitioned to 'Invoiced'.

    Returns 'Packed' as a safe default if no earlier state is found.
    """
    pf_osh_sql, pf_osh_params = partition_filter('order_state_history', alias='osh')
    rows = mysql_manager.execute_query(
        f"""
        SELECT os.state_name
        FROM order_state_history osh
        JOIN order_state os ON osh.state_id = os.state_id
        WHERE osh.potential_order_id = %s
          AND os.state_name != 'Invoiced'
          AND {pf_osh_sql}
        ORDER BY osh.changed_at DESC
        LIMIT 1
        """,
        (potential_order_id, *pf_osh_params),
    )
    return rows[0]['state_name'] if rows else 'Packed'


# ---------------------------------------------------------------------------
# Dealer Town Upload — admin only
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/dealer-town')
class DealerTownUpload(Resource):
    """
    POST /api/admin/dealer-town
    Upload an Excel/CSV file that maps dealer codes to towns.

    Expected columns:
      - 'Dealer Code'  (matched against dealer.dealer_code)
      - 'Town'

    Rows whose dealer_code does not exist are created as new dealers
    (name defaults to the dealer code until overridden by an order upload).
    Existing dealers are updated with the new town value.

    Returns:
      { success, updated, created, skipped, errors: [{row, reason}] }
    """

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user):
        import pandas as pd
        from io import BytesIO

        uploaded_file = request.files.get('file')
        if not uploaded_file:
            return {'success': False, 'msg': 'No file uploaded'}, 400

        filename = uploaded_file.filename or ''
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in ('csv', 'xls', 'xlsx'):
            return {'success': False, 'msg': 'File must be CSV, XLS, or XLSX'}, 400

        try:
            raw = uploaded_file.read()
            if ext == 'csv':
                df = pd.read_csv(BytesIO(raw), dtype=str)
            else:
                df = pd.read_excel(BytesIO(raw), dtype=str)
        except Exception as e:
            return {'success': False, 'msg': f'Could not parse file: {str(e)}'}, 400

        df.columns = [c.strip() for c in df.columns]

        required = {'Dealer Code', 'Town'}
        missing  = required - set(df.columns)
        if missing:
            return {
                'success': False,
                'msg':     f'Missing required columns: {", ".join(sorted(missing))}',
            }, 400

        df = df.dropna(subset=['Dealer Code'])
        df['Dealer Code'] = df['Dealer Code'].str.strip()
        df['Town']        = df['Town'].fillna('').str.strip()

        updated  = 0
        created  = 0
        skipped  = 0
        errors   = []

        for idx, row in df.iterrows():
            dealer_code = row['Dealer Code']
            town        = row['Town']
            row_num     = idx + 2  # 1-based + header

            if not dealer_code:
                skipped += 1
                continue

            try:
                existing = mysql_manager.execute_query(
                    "SELECT dealer_id FROM dealer WHERE dealer_code = %s",
                    (dealer_code,)
                )
                if existing:
                    mysql_manager.execute_query(
                        "UPDATE dealer SET town = %s, updated_at = %s WHERE dealer_code = %s",
                        (town, datetime.utcnow(), dealer_code),
                        fetch=False
                    )
                    updated += 1
                else:
                    # Create dealer with code as placeholder name
                    with mysql_manager.get_cursor() as cursor:
                        cursor.execute(
                            """INSERT INTO dealer (name, dealer_code, town, created_at, updated_at)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (dealer_code, dealer_code, town,
                             datetime.utcnow(), datetime.utcnow())
                        )
                    created += 1
            except Exception as e:
                errors.append({'row': row_num, 'dealer_code': dealer_code, 'reason': str(e)})

        return {
            'success': True,
            'updated': updated,
            'created': created,
            'skipped': skipped,
            'errors':  errors,
        }, 200


# ---------------------------------------------------------------------------
# Dealer list + individual town update — admin only
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/dealers')
class AdminDealerList(Resource):
    """
    GET /api/admin/dealers
    Returns all dealers (regardless of order status) with their current town.
    Used to populate the editable dealer table in the admin panel.

    Query params (all optional):
      search  — filter by dealer name or dealer code (case-insensitive)
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        search = (request.args.get('search') or '').strip()
        try:
            if search:
                rows = mysql_manager.execute_query(
                    """
                    SELECT dealer_id, name, dealer_code, town
                    FROM dealer
                    WHERE LOWER(name) LIKE %s OR LOWER(dealer_code) LIKE %s
                    ORDER BY name
                    """,
                    (f'%{search.lower()}%', f'%{search.lower()}%')
                )
            else:
                rows = mysql_manager.execute_query(
                    "SELECT dealer_id, name, dealer_code, town FROM dealer ORDER BY name"
                )
            dealers = [
                {
                    'dealer_id':   r['dealer_id'],
                    'name':        r['name'],
                    'dealer_code': r['dealer_code'] or '',
                    'town':        r['town'] or '',
                }
                for r in (rows or [])
            ]
            return {'success': True, 'dealers': dealers}, 200

        except Exception as e:
            logger.exception("Error in GET /api/admin/dealers")
            return {'success': False, 'msg': f'Error fetching dealers: {str(e)}'}, 400


@rest_api.route('/api/admin/dealers/<int:dealer_id>/town')
class AdminDealerTown(Resource):
    """
    PATCH /api/admin/dealers/<dealer_id>/town
    Update the town for a single dealer.

    JSON body:
      { "town": "New Town Name" }
    """

    @token_required
    @active_required
    @_admin_required
    def patch(self, current_user, dealer_id):
        data = request.get_json(force=True) or {}
        town = (data.get('town') or '').strip()

        try:
            existing = mysql_manager.execute_query(
                "SELECT dealer_id, name FROM dealer WHERE dealer_id = %s",
                (dealer_id,)
            )
            if not existing:
                return {'success': False, 'msg': 'Dealer not found'}, 404

            mysql_manager.execute_query(
                "UPDATE dealer SET town = %s, updated_at = %s WHERE dealer_id = %s",
                (town or None, datetime.utcnow(), dealer_id),
                fetch=False
            )
            return {
                'success': True,
                'dealer_id': dealer_id,
                'town':      town,
            }, 200

        except Exception as e:
            logger.exception("Error in PATCH /api/admin/dealers/<dealer_id>/town")
            return {'success': False, 'msg': f'Error updating town: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# Product Nickname — admin only
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/products')
class AdminProductList(Resource):
    """
    GET /api/admin/products
    Returns all products with their current nickname.
    Used to populate the editable product table in the admin panel.

    Query params (all optional):
      search  — filter by product name, description, or product_string (case-insensitive)
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        search = (request.args.get('search') or '').strip()
        try:
            if search:
                rows = mysql_manager.execute_query(
                    """
                    SELECT product_id, product_string, name, description, nickname
                    FROM product
                    WHERE LOWER(name) LIKE %s
                       OR LOWER(description) LIKE %s
                       OR LOWER(product_string) LIKE %s
                    ORDER BY name
                    """,
                    (f'%{search.lower()}%', f'%{search.lower()}%', f'%{search.lower()}%')
                )
            else:
                rows = mysql_manager.execute_query(
                    "SELECT product_id, product_string, name, description, nickname FROM product ORDER BY name"
                )
            products = [
                {
                    'product_id':     r['product_id'],
                    'product_string': r['product_string'] or '',
                    'name':           r['name'] or '',
                    'description':    r['description'] or '',
                    'nickname':       r['nickname'] or '',
                }
                for r in (rows or [])
            ]
            return {'success': True, 'products': products}, 200

        except Exception as e:
            logger.exception("Error in GET /api/admin/products")
            return {'success': False, 'msg': f'Error fetching products: {str(e)}'}, 400


@rest_api.route('/api/admin/product-nickname')
class ProductNicknameUpload(Resource):
    """
    POST /api/admin/product-nickname
    Upload an Excel/CSV file that maps product strings to nicknames.

    Expected columns:
      - 'Product String'  (matched against product.product_string)
      - 'Nickname'

    Returns:
      { success, updated, skipped, errors: [{row, product_string, reason}] }
    """

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user):
        import pandas as pd
        from io import BytesIO as _BytesIO

        uploaded_file = request.files.get('file')
        if not uploaded_file:
            return {'success': False, 'msg': 'No file uploaded'}, 400

        filename = uploaded_file.filename or ''
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in ('csv', 'xls', 'xlsx'):
            return {'success': False, 'msg': 'File must be CSV, XLS, or XLSX'}, 400

        try:
            raw = uploaded_file.read()
            if ext == 'csv':
                df = pd.read_csv(_BytesIO(raw), dtype=str)
            else:
                df = pd.read_excel(_BytesIO(raw), dtype=str)
        except Exception as e:
            return {'success': False, 'msg': f'Could not parse file: {str(e)}'}, 400

        df.columns = [c.strip() for c in df.columns]

        required = {'Product String', 'Nickname'}
        missing  = required - set(df.columns)
        if missing:
            return {
                'success': False,
                'msg':     f'Missing required columns: {", ".join(sorted(missing))}',
            }, 400

        df = df.dropna(subset=['Product String'])
        df['Product String'] = df['Product String'].str.strip()
        df['Nickname']       = df['Nickname'].fillna('').str.strip()

        updated = 0
        skipped = 0
        errors  = []

        for idx, row in df.iterrows():
            product_string = row['Product String']
            nickname       = row['Nickname']
            row_num        = idx + 2  # 1-based + header

            if not product_string:
                skipped += 1
                continue

            try:
                existing = mysql_manager.execute_query(
                    "SELECT product_id FROM product WHERE product_string = %s",
                    (product_string,)
                )
                if existing:
                    mysql_manager.execute_query(
                        "UPDATE product SET nickname = %s, updated_at = %s WHERE product_string = %s",
                        (nickname or None, datetime.utcnow(), product_string),
                        fetch=False
                    )
                    updated += 1
                else:
                    skipped += 1
                    errors.append({
                        'row':            row_num,
                        'product_string': product_string,
                        'reason':         'Product not found',
                    })
            except Exception as e:
                errors.append({'row': row_num, 'product_string': product_string, 'reason': str(e)})

        return {
            'success': True,
            'updated': updated,
            'skipped': skipped,
            'errors':  errors,
        }, 200


@rest_api.route('/api/admin/products/<int:product_id>/nickname')
class AdminProductNickname(Resource):
    """
    PATCH /api/admin/products/<product_id>/nickname
    Update the nickname for a single product.

    JSON body:
      { "nickname": "Short Name" }
    """

    @token_required
    @active_required
    @_admin_required
    def patch(self, current_user, product_id):
        data     = request.get_json(force=True) or {}
        nickname = (data.get('nickname') or '').strip()

        try:
            existing = mysql_manager.execute_query(
                "SELECT product_id, name FROM product WHERE product_id = %s",
                (product_id,)
            )
            if not existing:
                return {'success': False, 'msg': 'Product not found'}, 404

            mysql_manager.execute_query(
                "UPDATE product SET nickname = %s, updated_at = %s WHERE product_id = %s",
                (nickname or None, datetime.utcnow(), product_id),
                fetch=False
            )
            return {
                'success':    True,
                'product_id': product_id,
                'nickname':   nickname,
            }, 200

        except Exception as e:
            logger.exception("Error in PATCH /api/admin/products/<product_id>/nickname")
            return {'success': False, 'msg': f'Error updating nickname: {str(e)}'}, 400


# ---------------------------------------------------------------------------
# User management — admin only
#
# Until now the web app could not create a user at all. A person could only get an
# account by self-registering (/api/users/register), which lands them 'pending' with the
# 'viewer' role, and then being approved from the separate Flask-Admin panel. The mobile
# API could create users properly (POST /api/v1/auth/users) but needs a mobile JWT, so an
# admin at a desk had no route to it. These endpoints close that gap for the web app.
#
# `status` matters more than it looks: the mobile app refuses to log in unless it is
# exactly 'active', while the web app accepts anything that is not 'pending'. Creating a
# user 'active' is therefore the only value that works for both, and is the default here.
# ---------------------------------------------------------------------------

VALID_STATUSES = ('active', 'pending', 'blocked')


def _role_map():
    return {r['name']: r['role_id'] for r in
            (mysql_manager.execute_query("SELECT role_id, name FROM roles") or [])}


@rest_api.route('/api/admin/users')
class AdminUsers(Resource):
    """GET  — every user with role, status and scope grants.
       POST — create a user and their login."""

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        try:
            rows = mysql_manager.execute_query(
                """SELECT u.id, u.name, u.email, u.status, u.role, u.date_joined,
                          (SELECT GROUP_CONCAT(DISTINCT r2.name ORDER BY r2.name SEPARATOR ', ')
                             FROM user_roles ur JOIN roles r2 ON r2.role_id = ur.role_id
                            WHERE ur.user_id = u.id) AS roles,
                          (SELECT COUNT(*) FROM user_warehouse_company uwc
                            WHERE uwc.user_id = u.id) AS grants
                   FROM users u ORDER BY u.date_joined DESC""") or []
            roles = mysql_manager.execute_query(
                "SELECT role_id, name, description FROM roles ORDER BY name") or []
            return {'success': True,
                    'users': [{
                        'id': r['id'], 'name': r['name'], 'email': r['email'],
                        'status': r['status'], 'role': r['role'],
                        'roles': r['roles'] or r['role'], 'grants': r['grants'],
                        'date_joined': r['date_joined'].isoformat() if r['date_joined'] else None,
                    } for r in rows],
                    'roles': [{'id': r['role_id'], 'name': r['name'],
                               'description': r['description']} for r in roles]}, 200
        except Exception as e:
            logger.exception('Error listing users')
            return {'success': False, 'msg': str(e)}, 400

    @token_required
    @active_required
    @_admin_required
    def post(self, current_user):
        from werkzeug.security import generate_password_hash
        body = request.get_json(silent=True) or {}
        # `name` is the person's display name; `email` is the credential. The request
        # still accepts `username` as an alias so nothing calling the older shape breaks.
        name = (body.get('name') or body.get('username') or '').strip()
        email = (body.get('email') or '').strip()
        password = body.get('password') or ''
        role = (body.get('role') or 'viewer').strip()
        status = (body.get('status') or 'active').strip()

        if not 3 <= len(name) <= 32:
            return {'success': False, 'msg': 'Name must be 3–32 characters.'}, 422
        # Email is the login for both apps, so an account without one cannot sign in.
        if '@' not in email or len(email) > 64:
            return {'success': False, 'msg': 'A valid email is required — it is the login.'}, 422
        # The web login model caps the password at 16, so a longer one would be created
        # here and then rejected at sign-in — bound it to what can actually be used.
        if not 8 <= len(password) <= 16:
            return {'success': False, 'msg': 'Password must be 8–16 characters.'}, 422
        if status not in VALID_STATUSES:
            return {'success': False, 'msg': f'status must be one of {", ".join(VALID_STATUSES)}'}, 422

        roles = _role_map()
        if role not in roles:
            return {'success': False, 'msg': f'Unknown role "{role}".'}, 422
        if mysql_manager.execute_query("SELECT id FROM users WHERE email = %s", (email,)):
            return {'success': False, 'msg': f'Email "{email}" already has an account.'}, 409

        try:
            mysql_manager.execute_query(
                """INSERT INTO users (name, email, password, jwt_auth_active,
                                      date_joined, status, role)
                   VALUES (%s, %s, %s, 0, %s, %s, %s)""",
                (name, email, generate_password_hash(password),
                 datetime.utcnow(), status, role), fetch=False)
            new_id = mysql_manager.execute_query(
                "SELECT id FROM users WHERE email = %s", (email,))[0]['id']

            # users.role is the legacy single-role column; user_roles is what the unified
            # RBAC reads. Write both, or the user's permissions fall back to legacy
            # defaults and quietly differ from the role that was chosen.
            mysql_manager.execute_query(
                "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                (new_id, roles[role]), fetch=False)

            # Warehouse/company scope. Grants are (warehouse, company) pairs because
            # company_id is NOT NULL; a warehouse list alone cannot be stored.
            grants = body.get('grants') or []
            if not grants:
                wids, cids = body.get('warehouse_ids') or [], body.get('company_ids') or []
                grants = [{'warehouse_id': w, 'company_id': c} for w in wids for c in cids]
            for g in grants:
                mysql_manager.execute_query(
                    """INSERT IGNORE INTO user_warehouse_company (user_id, warehouse_id, company_id)
                       VALUES (%s, %s, %s)""",
                    (new_id, g.get('warehouse_id'), g.get('company_id')), fetch=False)

            logger.info('admin %s created user %s <%s> (%s)', current_user.id, name, email, role)
            return {'success': True, 'id': new_id, 'name': name, 'email': email,
                    'role': role, 'status': status, 'grants': len(grants),
                    'msg': f'User "{name}" created — they sign in with {email}.'}, 201
        except Exception as e:
            logger.exception('Error creating user')
            return {'success': False, 'msg': str(e)}, 400


@rest_api.route('/api/admin/users/<int:user_id>')
class AdminUserDetail(Resource):
    """Change a user's role, status, or password. Only the fields sent are touched."""

    @token_required
    @active_required
    @_admin_required
    def put(self, current_user, user_id):
        from werkzeug.security import generate_password_hash
        body = request.get_json(silent=True) or {}
        row = mysql_manager.execute_query(
            "SELECT id, name, role FROM users WHERE id = %s", (user_id,))
        if not row:
            return {'success': False, 'msg': 'User not found.'}, 404

        sets, params, changed = [], [], []
        if 'status' in body:
            status = (body.get('status') or '').strip()
            if status not in VALID_STATUSES:
                return {'success': False, 'msg': f'status must be one of {", ".join(VALID_STATUSES)}'}, 422
            # An admin locking themselves out is a support call, not a feature.
            if user_id == current_user.id and status != 'active':
                return {'success': False, 'msg': 'You cannot change your own status.'}, 422
            sets.append('status = %s'); params.append(status); changed.append('status')
        if 'role' in body:
            role = (body.get('role') or '').strip()
            roles = _role_map()
            if role not in roles:
                return {'success': False, 'msg': f'Unknown role "{role}".'}, 422
            if user_id == current_user.id and role != row[0]['role']:
                return {'success': False, 'msg': 'You cannot change your own role.'}, 422
            sets.append('role = %s'); params.append(role); changed.append('role')
        if 'password' in body:
            pw = body.get('password') or ''
            if not 8 <= len(pw) <= 16:
                return {'success': False, 'msg': 'Password must be 8–16 characters.'}, 422
            sets.append('password = %s'); params.append(generate_password_hash(pw))
            changed.append('password')

        if not sets:
            return {'success': False, 'msg': 'Nothing to update.'}, 422
        try:
            mysql_manager.execute_query(
                f"UPDATE users SET {', '.join(sets)} WHERE id = %s",
                tuple(params + [user_id]), fetch=False)
            # Keep user_roles in step with the legacy column, as on create.
            if 'role' in body:
                roles = _role_map()
                mysql_manager.execute_query(
                    "DELETE FROM user_roles WHERE user_id = %s", (user_id,), fetch=False)
                mysql_manager.execute_query(
                    "INSERT IGNORE INTO user_roles (user_id, role_id) VALUES (%s, %s)",
                    (user_id, roles[body['role'].strip()]), fetch=False)
            logger.info('admin %s updated user %s: %s', current_user.id, user_id, changed)
            return {'success': True, 'msg': f"Updated {', '.join(changed)} for "
                                            f"\"{row[0]['name']}\"."}, 200
        except Exception as e:
            logger.exception('Error updating user')
            return {'success': False, 'msg': str(e)}, 400
