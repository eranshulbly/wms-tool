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
                    rv.name      AS reverted_by_name
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
    # The final DELETE names no alias — a single-table DELETE cannot carry one — so it
    # needs the bare form of the same filter. Using the aliased fragment there is what
    # raised "Unknown column 'po.created_at'".
    pf_po_bare_sql, pf_po_bare_params = partition_filter('potential_order')

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
            f"DELETE FROM potential_order WHERE upload_batch_id = %s AND {pf_po_bare_sql}",
            (batch_id, *pf_po_bare_params),
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

# The dealer master's columns, in template order. Everything here is a real
# column on `dealer`; the header names ARE the column names, so an admin reading
# the template and an engineer reading the table see the same words.
#
# Only latitude/longitude and dealer_code are optional. The rest are mandatory
# because a dealer missing them is not usable downstream: reps search by name and
# town, orders print the address and gstin, and phone is how the office reaches
# the shop. Coordinates are optional since the app can capture them from the
# field later (shopfront photo -> admin approval), and dealer_code because not
# every company issues one.
DEALER_ALL_COLUMNS = [
    'name', 'dealer_code', 'town', 'latitude', 'longitude',
    'phone', 'address', 'gstin',
]
DEALER_REQUIRED_COLUMNS = ['name', 'town', 'phone', 'address', 'gstin']

# An invalid file usually has the SAME mistake on every row. Listing all of them
# makes the message unreadable without telling the admin anything new, so the
# message shows the first few and counts the rest; `errors` carries the full list.
_MAX_REPORTED_ROWS = 10


def _norm_header(col):
    """'Dealer Code' / 'DEALER_CODE' / ' dealer code ' -> 'dealer_code'."""
    return str(col).strip().lower().replace(' ', '_')


def _dealer_code_owner(company_id):
    """Returns f(dealer_code) -> owning company's name, for codes held OUTSIDE
    this company; None when the code is free or already ours.

    dealer.dealer_code carries a unique index across the whole table, not per
    company, so a code another company already holds simply cannot be inserted
    here. Looking it up during validation turns a duplicate-key exception thrown
    halfway through a write into a named row the admin can go and fix.
    """
    def owner(dealer_code):
        rows = mysql_manager.execute_query(
            """SELECT c.name AS company_name
               FROM dealer d LEFT JOIN company c ON c.company_id = d.company_id
               WHERE d.dealer_code = %s
                 AND (d.company_id IS NULL OR d.company_id <> %s)""",
            (dealer_code, company_id))
        if not rows:
            return None
        return rows[0]['company_name'] or 'no company'
    return owner


def _validate_dealer_rows(df, code_owner):
    """Every problem in the file, as [{row, name, dealer_code, reason}].

    Pure apart from [code_owner], which is injected so this can be exercised
    without a database. An empty list means the file is safe to write in full.

    Collects ALL of a row's problems rather than stopping at the first, so one
    upload attempt tells the admin everything that needs fixing instead of
    revealing the next fault only after they've corrected the last one.
    """
    errors = []
    for idx, row in df.iterrows():
        problems = [f'{c} is required' for c in DEALER_REQUIRED_COLUMNS if not row[c]]

        for coord, lo, hi in (('latitude', -90, 90), ('longitude', -180, 180)):
            if not row[coord]:
                continue
            try:
                val = float(row[coord])
            except ValueError:
                problems.append(f"{coord} '{row[coord]}' is not a number")
                continue
            if not lo <= val <= hi:
                problems.append(f'{coord} must be between {lo} and {hi}')

        if row['dealer_code']:
            owner = code_owner(row['dealer_code'])
            if owner:
                problems.append(
                    f"dealer_code '{row['dealer_code']}' already belongs to {owner}")

        if problems:
            errors.append({
                'row': idx + 2,  # 1-based, plus the header line
                'name': row['name'],
                'dealer_code': row['dealer_code'],
                'reason': '; '.join(problems),
            })
    return errors


@rest_api.route('/api/admin/dealer-town')
class DealerTownUpload(Resource):
    """
    POST /api/admin/dealer-town
    Upload an Excel/CSV file that maps dealer codes to towns, for ONE company.

    Form fields:
      - 'file'        the CSV/XLS/XLSX
      - 'company_id'  the company every row in this file belongs to

    Expected columns (header names are the dealer column names, matched
    case-insensitively with spaces treated as underscores):

      name*, dealer_code, town*, latitude, longitude, phone*, address*, gstin*

    * mandatory. The file is validated in full BEFORE anything is written: a
    missing mandatory column, a missing mandatory value in any row, an
    unparseable coordinate, or a dealer_code already owned by another company
    all reject the entire upload with a message naming the rows at fault.
    Half-importing a dealer master leaves an admin unable to tell which rows
    landed, which is worse than importing none of it.

    company_id is required, and is what makes both halves of this correct. A
    dealer code is only unique within a company, so matching on the code alone
    would update whichever company's row happened to come first; and a dealer
    created without a company is invisible to the mobile app, since every read
    path there is company-scoped. The file itself carries no company column —
    one upload is one company, chosen in the admin UI.

    Rows are matched within that company by dealer_code where the file gives
    one, else by name. A match is updated; anything else is created there.

    Returns:
      200 { success: true, updated, created, skipped, errors: [{row, reason}] }
      400 { success: false, msg, errors? }  — nothing was written
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

        raw_company = (request.form.get('company_id') or '').strip()
        if not raw_company:
            return {'success': False, 'msg': 'Select the company this file is for'}, 400
        try:
            company_id = int(raw_company)
        except (TypeError, ValueError):
            return {'success': False, 'msg': 'company_id must be a number'}, 400

        # Checked up front: a bad id would otherwise fail once per row, or worse,
        # write hundreds of dealers onto a company that doesn't exist.
        if not mysql_manager.execute_query(
            "SELECT company_id FROM company WHERE company_id = %s", (company_id,)
        ):
            return {'success': False, 'msg': f'Company {company_id} not found'}, 400

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

        # Headers are normalised, not matched literally: 'Dealer Code', 'dealer code'
        # and 'dealer_code' are the same column to anyone filling in the template,
        # and rejecting a file over capitalisation teaches nothing.
        df.columns = [_norm_header(c) for c in df.columns]

        missing = [c for c in DEALER_REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            return {
                'success': False,
                'msg': 'Missing required column(s): ' + ', '.join(missing) +
                       '. Expected: ' + ', '.join(DEALER_ALL_COLUMNS) +
                       '. Download the sample template for the exact format.',
            }, 400

        for col in DEALER_ALL_COLUMNS:
            df[col] = (df[col].fillna('').astype(str).str.strip()
                       if col in df.columns else '')

        # A row with nothing in it is a trailing blank line, not a mistake worth
        # failing a whole file over.
        blank = df[DEALER_ALL_COLUMNS].eq('').all(axis=1)
        df = df[~blank]
        if df.empty:
            return {'success': False, 'msg': 'The file has no data rows.'}, 400

        # ── Validate the WHOLE file before writing any of it ──────────────
        row_errors = _validate_dealer_rows(df, _dealer_code_owner(company_id))

        if row_errors:
            shown = row_errors[:_MAX_REPORTED_ROWS]
            more = len(row_errors) - len(shown)
            msg = f'{len(row_errors)} row(s) are invalid — nothing was uploaded. ' + \
                  '; '.join(f"row {e['row']}: {e['reason']}" for e in shown)
            if more:
                msg += f'; and {more} more row(s).'
            return {'success': False, 'msg': msg, 'errors': row_errors}, 400

        # ── Write ─────────────────────────────────────────────────────────
        updated = 0
        created = 0
        errors  = []

        for idx, row in df.iterrows():
            row_num = idx + 2
            values = {c: (row[c] or None) for c in DEALER_ALL_COLUMNS}

            try:
                # Matched within the chosen company: by code where the file gives
                # one, else by name — which is also how the Busy sales feed
                # attributes a sale, so it is the dealer's other real identifier.
                if values['dealer_code']:
                    key_sql, key_args = 'dealer_code = %s', (values['dealer_code'],)
                else:
                    key_sql, key_args = 'name = %s', (values['name'],)

                existing = mysql_manager.execute_query(
                    f"SELECT dealer_id FROM dealer WHERE {key_sql} AND company_id = %s",
                    key_args + (company_id,))

                if existing:
                    # dealer_code is left out of the SET list when the file omits
                    # it: a blank cell means "not supplied", and clearing a code
                    # the dealer already has would orphan it from its orders.
                    fields = ['name', 'town', 'latitude', 'longitude',
                              'phone', 'address', 'gstin']
                    if values['dealer_code']:
                        fields.append('dealer_code')
                    mysql_manager.execute_query(
                        'UPDATE dealer SET ' +
                        ', '.join(f'{f} = %s' for f in fields) +
                        ', updated_at = %s WHERE dealer_id = %s',
                        tuple(values[f] for f in fields) +
                        (datetime.utcnow(), existing[0]['dealer_id']),
                        fetch=False)
                    updated += 1
                else:
                    with mysql_manager.get_cursor() as cursor:
                        cursor.execute(
                            """INSERT INTO dealer (name, dealer_code, town, latitude,
                                                   longitude, phone, address, gstin,
                                                   company_id, created_at, updated_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (values['name'], values['dealer_code'], values['town'],
                             values['latitude'], values['longitude'], values['phone'],
                             values['address'], values['gstin'], company_id,
                             datetime.utcnow(), datetime.utcnow()))
                    created += 1
            except Exception as e:
                logger.exception("dealer-town: row %s failed", row_num)
                errors.append({'row': row_num, 'name': values['name'],
                               'dealer_code': values['dealer_code'] or '',
                               'reason': str(e)})

        return {
            'success': True,
            'updated': updated,
            'created': created,
            'skipped': 0,
            'errors':  errors,
        }, 200


# ---------------------------------------------------------------------------
# Dealer list + individual town update — admin only
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/dealers')
class AdminDealerList(Resource):
    """
    GET /api/admin/dealers
    Returns all dealers (regardless of order status) with their current town and
    the company they belong to. A dealer code only has to be unique WITHIN a
    company, so the company is what tells two same-coded rows apart — and a
    dealer with no company is invisible to the mobile app, which the blank
    company here is meant to make obvious.

    Query params (all optional):
      search  — filter by dealer name or dealer code (case-insensitive)
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        search = (request.args.get('search') or '').strip()
        # LEFT JOIN, not JOIN: a dealer with no company is exactly the row an
        # admin most needs to see here, and an inner join would hide it.
        base = """
            SELECT d.dealer_id, d.name, d.dealer_code, d.town,
                   d.company_id, c.name AS company_name
            FROM dealer d
            LEFT JOIN company c ON c.company_id = d.company_id
        """
        try:
            if search:
                rows = mysql_manager.execute_query(
                    base + """
                    WHERE LOWER(d.name) LIKE %s OR LOWER(d.dealer_code) LIKE %s
                    ORDER BY d.name
                    """,
                    (f'%{search.lower()}%', f'%{search.lower()}%')
                )
            else:
                rows = mysql_manager.execute_query(base + " ORDER BY d.name")
            dealers = [
                {
                    'dealer_id':    r['dealer_id'],
                    'name':         r['name'],
                    'dealer_code':  r['dealer_code'] or '',
                    'town':         r['town'] or '',
                    'company_id':   r['company_id'],
                    'company_name': r['company_name'] or '',
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
# Product master browser — admin only
# ---------------------------------------------------------------------------

@rest_api.route('/api/admin/products')
class AdminProductList(Resource):
    """
    GET /api/admin/products
    The product master for one company, so an admin can confirm what an upload
    actually loaded.

    Query params:
      company_id  — required. Products are per-company, and the master runs to
                    tens of thousands of rows for a single one; returning every
                    company's at once is neither useful nor fast.
      search      — optional. Matches name, product code or description.
      limit/offset— optional paging (default 200).
    """

    @token_required
    @active_required
    @_admin_required
    def get(self, current_user):
        from api.permissions import resolve_company_scope, CompanyAccessDenied
        try:
            scope = resolve_company_scope(current_user, request.args.get('company_id', type=int))
        except CompanyAccessDenied as e:
            return {'success': False, 'msg': str(e)}, 403

        where, params = ['1=1'], []
        if scope is not None:
            if not scope:
                return {'success': True, 'products': [], 'total': 0}, 200
            where.append('p.company_id IN (%s)' % ','.join(['%s'] * len(scope)))
            params += list(scope)

        search = (request.args.get('search') or '').strip()
        if search:
            where.append('(LOWER(p.name) LIKE %s OR LOWER(p.product_string) LIKE %s '
                         'OR LOWER(p.description) LIKE %s)')
            params += [f'%{search.lower()}%'] * 3

        clause = ' AND '.join(where)
        try:
            total = mysql_manager.execute_query(
                f'SELECT COUNT(*) AS c FROM product p WHERE {clause}', tuple(params))[0]['c']
            limit = min(int(request.args.get('limit', 200)), 1000)
            offset = int(request.args.get('offset', 0))
            rows = mysql_manager.execute_query(
                f"""SELECT p.product_id, p.product_string, p.name, p.description,
                           p.uom, p.hsn_code, p.company_id, c.name AS company_name,
                           p.is_active, p.updated_at
                      FROM product p
                      LEFT JOIN company c ON c.company_id = p.company_id
                     WHERE {clause}
                     ORDER BY p.product_id DESC
                     LIMIT %s OFFSET %s""",
                (*params, limit, offset)) or []
            products = [{
                'product_id':     r['product_id'],
                'product_string': r['product_string'] or '',
                'name':           r['name'] or '',
                'description':    r['description'] or '',
                'uom':            r['uom'] or '',
                'hsn_code':       r['hsn_code'] or '',
                'company_id':     r['company_id'],
                'company_name':   r['company_name'] or '',
                'is_active':      bool(r['is_active']),
                'updated_at':     r['updated_at'].isoformat() if r['updated_at'] else None,
            } for r in rows]
            return {'success': True, 'products': products, 'total': total}, 200
        except Exception as e:
            logger.exception("Error in GET /api/admin/products")
            return {'success': False, 'msg': f'Error fetching products: {str(e)}'}, 400


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

# Roles that may hold at most ONE warehouse. A field executive works out of a single
# depot: their orders, their stock view and their supply sheet all resolve against it, so
# a second warehouse makes "which one did this come from" unanswerable rather than
# giving them more reach. Companies are NOT limited — one rep can sell several
# principals out of the same depot, which is why the pair is (1 warehouse x N companies).
SINGLE_WAREHOUSE_ROLES = ('sales_executive',)


def _check_single_warehouse(role, grants):
    """Return an error string if `role` may hold only one warehouse and `grants` name
    more than one. Counts DISTINCT warehouses — several companies in the same depot is
    several grants but still one warehouse, and must be allowed."""
    if role not in SINGLE_WAREHOUSE_ROLES:
        return None
    wids = {g.get('warehouse_id') for g in grants if g.get('warehouse_id')}
    if len(wids) > 1:
        return (f'A {role} can be mapped to only one warehouse — '
                f'{len(wids)} were selected.')
    return None


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
                            WHERE uwc.user_id = u.id) AS grants,
                          (SELECT GROUP_CONCAT(DISTINCT co.name ORDER BY co.name SEPARATOR ', ')
                             FROM user_warehouse_company uwc
                             JOIN company co ON co.company_id = uwc.company_id
                            WHERE uwc.user_id = u.id) AS companies,
                          (SELECT GROUP_CONCAT(DISTINCT uwc.company_id)
                             FROM user_warehouse_company uwc WHERE uwc.user_id = u.id) AS company_ids,
                          (SELECT GROUP_CONCAT(DISTINCT uwc.warehouse_id)
                             FROM user_warehouse_company uwc WHERE uwc.user_id = u.id) AS warehouse_ids
                   FROM users u ORDER BY u.date_joined DESC""") or []
            # `all_companies` says the ROLE already reaches every company, so per-company
            # grants are optional for it. resolve_company_scope() keys off all_warehouses,
            # so that flag — not the company:all permission — is what actually decides.
            roles = mysql_manager.execute_query(
                "SELECT role_id, name, description, all_warehouses FROM roles ORDER BY name") or []
            return {'success': True,
                    'users': [{
                        'id': r['id'], 'name': r['name'], 'email': r['email'],
                        'status': r['status'], 'role': r['role'],
                        'roles': r['roles'] or r['role'], 'grants': r['grants'],
                        'companies': r['companies'],
                        'company_ids': [int(x) for x in (r['company_ids'] or '').split(',') if x],
                        'warehouse_ids': [int(x) for x in (r['warehouse_ids'] or '').split(',') if x],
                        'date_joined': r['date_joined'].isoformat() if r['date_joined'] else None,
                    } for r in rows],
                    'roles': [{'id': r['role_id'], 'name': r['name'],
                               'description': r['description'],
                               'all_companies': bool(r['all_warehouses'])} for r in roles]}, 200
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

        # Validate the scope before creating anything — a rejected request must not
        # leave a half-made user behind.
        pre_grants = body.get('grants') or [
            {'warehouse_id': w, 'company_id': c}
            for w in (body.get('warehouse_ids') or [])
            for c in (body.get('company_ids') or [])]
        err = _check_single_warehouse(role, pre_grants)
        if err:
            return {'success': False, 'msg': err}, 422

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

        # Scope grants are replaced wholesale rather than merged: the editor shows the
        # full picture, so what it sends IS the intended set. Sending an empty list is a
        # deliberate "no scope", not a no-op.
        regrant = None
        if 'grants' in body or 'warehouse_ids' in body or 'company_ids' in body:
            regrant = body.get('grants')
            if regrant is None:
                wids = body.get('warehouse_ids') or []
                cids = body.get('company_ids') or []
                regrant = [{'warehouse_id': w, 'company_id': c} for w in wids for c in cids]
            changed.append('scope')

        # Check against the role the user will hold AFTER this request: changing role and
        # scope in one call must be judged on the outcome, not the previous role.
        if regrant is not None:
            effective_role = (body.get('role') or row[0]['role'] or '').strip()
            err = _check_single_warehouse(effective_role, regrant)
            if err:
                return {'success': False, 'msg': err}, 422

        if not sets and regrant is None:
            return {'success': False, 'msg': 'Nothing to update.'}, 422
        try:
            if sets:
                mysql_manager.execute_query(
                    f"UPDATE users SET {', '.join(sets)} WHERE id = %s",
                    tuple(params + [user_id]), fetch=False)
            if regrant is not None:
                mysql_manager.execute_query(
                    "DELETE FROM user_warehouse_company WHERE user_id = %s",
                    (user_id,), fetch=False)
                for g in regrant:
                    if g.get('warehouse_id') and g.get('company_id'):
                        mysql_manager.execute_query(
                            """INSERT IGNORE INTO user_warehouse_company
                                 (user_id, warehouse_id, company_id) VALUES (%s, %s, %s)""",
                            (user_id, g['warehouse_id'], g['company_id']), fetch=False)
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
