# -*- encoding: utf-8 -*-
"""picklist module — SQL. Every read here is company-scoped by the caller's own
resolved scope, never by a request parameter (see api/permissions.py).

order_picklist is not partitioned, but every join to potential_order is, so each
one carries partition_filter(). Without it MySQL touches every monthly partition
instead of the active window.
"""

import json
from datetime import datetime

from api.db_manager import mysql_manager, partition_filter
from api.permissions import company_filter_sql
from api.core.logging import get_logger

logger = get_logger(__name__)

# Order statuses that leave a pick list "open" — still issuable to the floor.
#
# Only Open. The moment a picker scans the QR and the order moves to Picking, the
# sheet is closed: someone is walking the aisles with the paper copy, and a second
# copy printed behind them means two people picking the same order against two
# sheets. Everything from Picking onwards reads as closed, and a closed sheet
# cannot be printed or downloaded again (see fetch_for_render's open_only).
#
# There is no status column on order_picklist: a stored copy would drift the first
# time an order moved by a path that forgot to update it.
OPEN_STATUSES = ('Open',)


def find_by_token(token: str):
    """One pick list by its QR token. The ONLY lookup a scan may use."""
    rows = mysql_manager.execute_query(
        """SELECT picklist_id, potential_order_id, original_order_id, picklist_code,
                  qr_token, company_id, warehouse_id
           FROM order_picklist WHERE qr_token = %s""",
        (token,),
    )
    return rows[0] if rows else None


def find_existing(potential_order_id: int, picklist_code: str):
    """The row a re-upload of the same document would replace, if any."""
    rows = mysql_manager.execute_query(
        """SELECT picklist_id, qr_token FROM order_picklist
           WHERE potential_order_id = %s AND picklist_code = %s""",
        (potential_order_id, picklist_code or ''),
    )
    return rows[0] if rows else None


def insert(cursor, row: dict) -> int:
    cursor.execute(
        """INSERT INTO order_picklist
             (potential_order_id, original_order_id, picklist_code, picklist_date,
              qr_token, line_count, meta, warehouse_id, company_id, upload_batch_id,
              created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (row['potential_order_id'], row['original_order_id'], row['picklist_code'],
         row['picklist_date'], row['qr_token'], row['line_count'],
         json.dumps(row['meta'], ensure_ascii=False), row['warehouse_id'],
         row['company_id'], row['upload_batch_id'], row['created_by']),
    )
    return cursor.lastrowid


def update_in_place(cursor, picklist_id: int, row: dict) -> None:
    """Refresh a re-uploaded pick list.

    qr_token is deliberately NOT touched: sheets already printed and clipped to a
    trolley must keep resolving after someone re-uploads the same document.
    """
    cursor.execute(
        """UPDATE order_picklist
              SET picklist_date = %s, line_count = %s, meta = %s,
                  warehouse_id = %s, company_id = %s, upload_batch_id = %s
            WHERE picklist_id = %s""",
        (row['picklist_date'], row['line_count'],
         json.dumps(row['meta'], ensure_ascii=False), row['warehouse_id'],
         row['company_id'], row['upload_batch_id'], picklist_id),
    )


def mark_printed(picklist_ids, user_id) -> int:
    """Stamp a batch as printed, bumping the reprint counter.

    Called by the download route when the client asked to PRINT, not merely to
    save a copy. Done server-side on purpose: the browser cannot tell us whether
    ink hit paper — the print dialog can be cancelled, the tab closed, the printer
    offline — so the only honest thing to record is that the sheet was issued for
    printing. "Mark as not printed" is the correction for the rest.
    """
    if not picklist_ids:
        return 0
    placeholders = ', '.join(['%s'] * len(picklist_ids))
    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            f"""UPDATE order_picklist
                   SET printed_at = %s,
                       printed_by = %s,
                       print_count = print_count + 1
                 WHERE picklist_id IN ({placeholders})""",
            (datetime.utcnow(), user_id, *picklist_ids),
        )
        return cursor.rowcount


def unmark_printed(picklist_ids) -> int:
    """Put a batch back to never-printed.

    The escape hatch for a paper jam, or for a Print that opened the dialog and
    was then cancelled. Clears the counter too — a sheet that was never
    successfully printed has not been printed twice either.
    """
    if not picklist_ids:
        return 0
    placeholders = ', '.join(['%s'] * len(picklist_ids))
    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            f"""UPDATE order_picklist
                   SET printed_at = NULL, printed_by = NULL, print_count = 0
                 WHERE picklist_id IN ({placeholders})""",
            tuple(picklist_ids),
        )
        return cursor.rowcount


def clear_printed_on(cursor, picklist_id) -> None:
    """Forget that a pick list was printed, because it has just been re-uploaded.

    The paper already on the trolley describes the previous version of the sheet,
    so it is no longer a printed copy of THIS one. The QR token deliberately
    survives a re-upload; the print state deliberately does not.
    """
    cursor.execute(
        "UPDATE order_picklist SET printed_at = NULL, printed_by = NULL, "
        "print_count = 0 WHERE picklist_id = %s",
        (picklist_id,),
    )


def list_picklists(company_ids, warehouse_id=None, state='open', printed=None,
                   owner_id=None, limit=500, offset=0):
    """Pick lists joined to their order's live status.

    `meta` is deliberately absent from the SELECT. Eight lines is ~2KB but a
    200-line pick list is ~40KB, and a 500-row page would drag megabytes of JSON
    across the wire to render a table that shows none of it. The download reads it.
    """
    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')

    where = [pf_sql, cf_sql]
    params = list(pf_params) + list(cf_params)

    if state == 'open':
        where.append('po.status IN (%s)' % ', '.join(['%s'] * len(OPEN_STATUSES)))
        params.extend(OPEN_STATUSES)
    elif state == 'closed':
        where.append('po.status NOT IN (%s)' % ', '.join(['%s'] * len(OPEN_STATUSES)))
        params.extend(OPEN_STATUSES)

    if warehouse_id:
        where.append('pl.warehouse_id = %s')
        params.append(warehouse_id)

    # "Not printed" is the work queue — the sheets still waiting to go out to the
    # floor — so it is a first-class filter rather than something to eyeball.
    if printed is True:
        where.append('pl.printed_at IS NOT NULL')
    elif printed is False:
        where.append('pl.printed_at IS NULL')

    # Each uploader works their own pile. Scoped on created_by — the person who
    # uploaded the sheet — so two people importing for the same warehouse do not
    # end up printing each other's work.
    #
    # Deliberately ONLY here and on fetch_for_render. The scan path is not
    # scoped: a handheld on the floor resolves a QR by token, and which office
    # user happened to import that sheet is none of the picker's business.
    if owner_id is not None:
        where.append('pl.created_by = %s')
        params.append(owner_id)

    rows = mysql_manager.execute_query(
        """SELECT pl.picklist_id, pl.original_order_id, pl.picklist_code,
                  pl.picklist_date, pl.line_count, pl.created_at,
                  pl.printed_at, pl.print_count,
                  po.status AS order_status, po.potential_order_id,
                  d.name AS dealer_name, u.name AS printed_by_name,
                  pl.created_by, owner.name AS uploaded_by_name
             FROM order_picklist pl
             JOIN potential_order po
               ON po.potential_order_id = pl.potential_order_id
             LEFT JOIN dealer d ON d.dealer_id = po.dealer_id
             LEFT JOIN users  u     ON u.id = pl.printed_by
             LEFT JOIN users  owner ON owner.id = pl.created_by
            WHERE %s
            -- Newest first, and picklist_id breaks the ties. created_at is a
            -- DATETIME, so a batch upload stamps a dozen rows with the same
            -- second and MySQL is then free to return them in any order — which
            -- it does, differently between page loads. The id is monotonic with
            -- insert order, so it settles them into the order they arrived.
            ORDER BY pl.created_at DESC, pl.picklist_id DESC
            LIMIT %%s OFFSET %%s""" % ' AND '.join(where),
        tuple(params) + (limit, offset),
    )
    return rows or []


def fetch_for_render(picklist_ids: list, company_ids, owner_id=None):
    """Full rows, meta included, for the ids the caller selected.

    Company-scoped in the same query rather than filtered afterwards, so a caller
    cannot pull another tenant's pick list by guessing an id.

    Carries the order's live status so the caller can tell an OPEN sheet from a
    CLOSED one. Deliberately does NOT filter closed sheets out: the download route
    refuses the whole batch and names them, which is a far better answer than a
    PDF that silently came back one sheet short.
    """
    if not picklist_ids:
        return []

    pf_sql, pf_params = partition_filter('potential_order', alias='po')
    cf_sql, cf_params = company_filter_sql(company_ids, alias='po')
    placeholders = ', '.join(['%s'] * len(picklist_ids))

    # The owner filter belongs HERE as well as in the listing, not only there.
    # Download, print and the printed mark all resolve ids through this function,
    # and a filtered list is no protection at all if another user's id still
    # works when typed into the request body.
    owner_sql = 'pl.created_by = %s' if owner_id is not None else '1=1'
    owner_params = (owner_id,) if owner_id is not None else ()

    rows = mysql_manager.execute_query(
        """SELECT pl.picklist_id, pl.original_order_id, pl.picklist_code,
                  pl.qr_token, pl.meta, po.status AS order_status
             FROM order_picklist pl
             JOIN potential_order po
               ON po.potential_order_id = pl.potential_order_id
            WHERE pl.picklist_id IN (%s) AND %s AND %s AND %s
            ORDER BY pl.created_at""" % (placeholders, pf_sql, cf_sql, owner_sql),
        tuple(picklist_ids) + tuple(pf_params) + tuple(cf_params) + owner_params,
    )

    for row in rows or []:
        # PyMySQL hands a JSON column back as str on some server/driver combinations
        # and as a parsed dict on others. Normalise rather than depend on which.
        if isinstance(row.get('meta'), (str, bytes, bytearray)):
            row['meta'] = json.loads(row['meta'])
    return rows or []


def record_scan(picklist_id, qr_payload, scanned_by, device_id,
                from_status, to_status, result, reason=None) -> None:
    """Append to the scan audit. Never raises — a failed audit write must not undo
    a transition that already succeeded, nor mask the rejection it was recording."""
    try:
        mysql_manager.execute_query(
            """INSERT INTO order_picklist_scan
                 (picklist_id, qr_payload, scanned_by, device_id,
                  from_status, to_status, result, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (picklist_id, (qr_payload or '')[:255], scanned_by, device_id,
             from_status, to_status, result, (reason or '')[:500] or None),
            fetch=False,
        )
    except Exception:
        logger.exception("Could not write pick-list scan audit row",
                         extra={'picklist_id': picklist_id, 'result': result})
