# -*- encoding: utf-8 -*-
"""
order module — service layer for the mobile API (/api/v1/orders).

Backed by the app's OWN order store — the submitted_* tables (see schema.py):

    submitted_orders            — order header
    submitted_order_products    — line items (requested qty + SKU snapshot only)
    submitted_order_attachments — photo of a paper order (app-only)
    submitted_order_status_history — status log

These forked off potential_order / potential_order_product, which the app used to
share with the warehouse app. The app no longer reads or writes potential_order.

App orders land at `submitted` and stay there; entering the warehouse chain (Open →
Picking → …) happens later via the DMS-output upload (that matching flow is being
re-architected). There is no approve/reject step. `approved_by` / `approved_at` /
`rejection_reason` are kept in the API response (always NULL) for shape compatibility,
but no longer exist as columns.
"""

from datetime import datetime

from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.modules.order.constants import OrderStatus
from api.shared.timeutil import now_local

logger = get_logger(__name__)


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


# approved_by / approved_at / rejection_reason are emitted as constant NULLs so the
# response shape is unchanged now that approve/reject (and their columns) are gone.
ORDER_COLS = """so.submitted_order_id AS order_id, so.order_number, so.dealer_id, so.created_by,
                so.warehouse_id, so.status, so.source,
                NULL AS approved_by, NULL AS approved_at, NULL AS rejection_reason,
                so.notes, so.submitted_at, so.expected_delivery_date, so.created_at,
                so.company_id, c.name AS company_name,
                so.latitude, so.longitude, so.location_accuracy_m, so.location_captured_at,
                d.latitude AS dealer_lat, d.longitude AS dealer_lng"""

# Orders are the company-scoped entity; every read joins the company for its name
# and the dealer for its pin (to measure how far the rep was from the shop).
ORDER_FROM = ("FROM submitted_orders so "
              "LEFT JOIN company c ON c.company_id = so.company_id "
              "LEFT JOIN dealer  d ON d.dealer_id  = so.dealer_id")


def _items_for(order_id):
    # The app records only requested quantity + SKU snapshot. Warehouse-progress
    # fields don't exist here: quantity_fulfilled is genuinely unknown (NULL), but
    # item status is always 'pending' at submission — return that literal rather
    # than NULL so clients expecting a non-null status string don't break.
    return mysql_manager.execute_query(
        """SELECT submitted_order_product_id AS order_item_id, sku_code, product_name, uom,
                  quantity AS quantity_requested, NULL AS quantity_fulfilled,
                  'pending' AS status
           FROM submitted_order_products WHERE submitted_order_id = %s
           ORDER BY submitted_order_product_id""",
        (order_id,),
    ) or []


def get_order(order_id, company_ids=None, created_by=None):
    """Fetch one order. `company_ids` (None => unscoped) restricts it to the caller's
    companies so a scoped user can't reach another company's order by guessing an id.
    `created_by` further restricts it to orders that user raised."""
    sql = f"SELECT {ORDER_COLS} {ORDER_FROM} WHERE so.submitted_order_id = %s"
    params = [order_id]
    if company_ids is not None:
        if not company_ids:
            return None
        sql += " AND so.company_id IN (%s)" % ",".join(["%s"] * len(company_ids))
        params.extend(company_ids)
    if created_by is not None:
        sql += " AND so.created_by = %s"
        params.append(created_by)

    rows = mysql_manager.execute_query(sql, tuple(params))
    if not rows:
        return None
    order = rows[0]
    order['items'] = _items_for(order_id)
    return order


def list_orders(status=None, dealer_id=None, warehouse_id=None, date_from=None, date_to=None,
                sku_code=None, warehouse_ids=None, company_ids=None, created_by=None,
                company_id=None, limit=50, offset=0):
    where, params = [], []
    if created_by is not None:
        # Two roles: the own-orders scope for company users, and an explicit
        # salesperson filter an admin picks. Both are just "created_by = X".
        where.append("so.created_by = %s")
        params.append(created_by)
    if company_id is not None:
        # Explicit company filter (admin picking one company). ANDs with the
        # company_ids scope below, so a scoped user can't widen their view.
        where.append("so.company_id = %s")
        params.append(company_id)
    if status:
        where.append("so.status = %s")
        params.append(status)
    if dealer_id:
        where.append("so.dealer_id = %s")
        params.append(dealer_id)
    if warehouse_id is not None:
        where.append("so.warehouse_id = %s")
        params.append(warehouse_id)
    if warehouse_ids is not None:
        # Scoped user: an empty list legitimately matches nothing.
        if not warehouse_ids:
            return []
        where.append("so.warehouse_id IN (%s)" % ",".join(["%s"] * len(warehouse_ids)))
        params.extend(warehouse_ids)
    if company_ids is not None:
        # Same convention as warehouse_ids: None => unscoped, [] => matches nothing.
        if not company_ids:
            return []
        where.append("so.company_id IN (%s)" % ",".join(["%s"] * len(company_ids)))
        params.extend(company_ids)
    if date_from:
        where.append("so.created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("so.created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        params.append(date_to)
    if sku_code:
        where.append("""so.submitted_order_id IN (
            SELECT submitted_order_id FROM submitted_order_products WHERE sku_code = %s)""")
        params.append(sku_code)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params += [limit, offset]
    return mysql_manager.execute_query(
        f"""SELECT so.submitted_order_id AS order_id, so.order_number, so.dealer_id, so.status,
                   so.warehouse_id, so.created_at, so.company_id, c.name AS company_name,
                   so.created_by
            {ORDER_FROM} {clause}
            ORDER BY so.created_at DESC LIMIT %s OFFSET %s""",
        tuple(params),
    ) or []


def create_order(dealer_id, items, created_by, warehouse_id=None,
                 expected_delivery_date=None, notes=None, company_id=None,
                 latitude=None, longitude=None, location_accuracy_m=None):
    """Create an app order in `submitted`, snapshotting SKU details onto each line.

    `company_id` stamps the owning company. When set, the dealer and every SKU must
    belong to it — otherwise a user could build an order out of another company's
    records, and the resulting order would be invisible to them anyway.
    """
    dealer = mysql_manager.execute_query(
        "SELECT dealer_id, status, company_id FROM dealer WHERE dealer_id = %s", (dealer_id,)
    )
    if not dealer or (dealer[0].get('status') or 'active') != 'active':
        raise ValidationError(f"dealer {dealer_id} not found or inactive")
    if company_id is not None and dealer[0].get('company_id') != company_id:
        raise ValidationError(f"dealer {dealer_id} does not belong to this company")

    from api.modules.inventory import service as inventory_service
    if warehouse_id is not None and not inventory_service.warehouse_exists(warehouse_id):
        raise ValidationError(f"warehouse {warehouse_id} not found or inactive")

    from api.modules.catalog.router_v1 import get_sku
    resolved = []
    for it in items:
        sku = get_sku(it['sku_code'])
        if not sku or not sku['is_active']:
            raise ValidationError(f"sku {it['sku_code']} not found or inactive")
        if company_id is not None and sku.get('company_id') != company_id:
            raise ValidationError(f"sku {it['sku_code']} does not belong to this company")
        resolved.append((sku, it))

    now = now_local()
    with mysql_manager.get_cursor() as cursor:
        # Itemised orders already carry their lines, so they're ready for the DMS
        # download stage immediately (dms_status='ready') — no part-convertor step.
        cursor.execute(
            """INSERT INTO submitted_orders
                 (dealer_id, warehouse_id, company_id, status, source, dms_status,
                  requested_by, created_by, submitted_at, expected_delivery_date, notes,
                  latitude, longitude, location_accuracy_m, location_captured_at,
                  created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (dealer_id, warehouse_id, company_id, OrderStatus.SUBMITTED.value, 'itemised', 'ready',
             created_by, created_by, now, expected_delivery_date, notes,
             latitude, longitude, location_accuracy_m,
             now if latitude is not None else None, now, now),
        )
        order_id = cursor.lastrowid
        order_number = f"ORD-{order_id:06d}"
        cursor.execute(
            "UPDATE submitted_orders SET order_number = %s WHERE submitted_order_id = %s",
            (order_number, order_id),
        )

        for sku, it in resolved:
            cursor.execute(
                """INSERT INTO submitted_order_products
                     (submitted_order_id, product_id, sku_code, product_name, uom, quantity,
                      mrp, created_at, updated_at)
                   VALUES (%s,
                           (SELECT product_id FROM product WHERE product_string = %s),
                           %s,%s,%s,%s,%s,%s,%s)""",
                (order_id, sku['sku_code'], sku['sku_code'], sku['name'], sku['uom'],
                 it['quantity_requested'], sku['price'], now, now),
            )

        _record_status_change(cursor, order_id, None, OrderStatus.SUBMITTED.value,
                              created_by, "Order created")

    from api.shared.events import event_bus
    from api.modules.assignment.events import OrderSubmitted
    event_bus.publish(OrderSubmitted(order_id=order_id, dealer_id=dealer_id))
    return get_order(order_id)


def _record_status_change(cursor, order_id, from_status, to_status, changed_by, note=None):
    """Append to submitted_order_status_history and set the order's status."""
    cursor.execute(
        """INSERT INTO submitted_order_status_history
             (submitted_order_id, status, changed_by, changed_at)
           VALUES (%s,%s,%s,%s)""",
        (order_id, to_status, changed_by, now_local()),
    )
    cursor.execute(
        "UPDATE submitted_orders SET status = %s, updated_at = %s WHERE submitted_order_id = %s",
        (to_status, now_local(), order_id),
    )
    logger.info("order %s: %s -> %s (%s)", order_id, from_status, to_status, note or '')


def create_photo_order(dealer_id, created_by, company_id, warehouse_id=None,
                       notes=None, latitude=None, longitude=None,
                       location_accuracy_m=None):
    """Raise a paper-order capture: a real `submitted` order with a photo but no
    line items. The back office transcribes the photo into lines (via update_order)
    before the order moves on to the warehouse.
    """
    dealer = mysql_manager.execute_query(
        "SELECT dealer_id, status, company_id FROM dealer WHERE dealer_id = %s", (dealer_id,)
    )
    if not dealer or (dealer[0].get('status') or 'active') != 'active':
        raise ValidationError(f"dealer {dealer_id} not found or inactive")
    if company_id is not None and dealer[0].get('company_id') != company_id:
        raise ValidationError(f"dealer {dealer_id} does not belong to this company")

    now = now_local()
    with mysql_manager.get_cursor() as cursor:
        cursor.execute(
            """INSERT INTO submitted_orders
                 (dealer_id, warehouse_id, company_id, status, source,
                  requested_by, created_by, submitted_at, notes,
                  latitude, longitude, location_accuracy_m, location_captured_at,
                  created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (dealer_id, warehouse_id, company_id, OrderStatus.SUBMITTED.value, 'photo',
             created_by, created_by, now, notes,
             latitude, longitude, location_accuracy_m,
             now if latitude is not None else None, now, now),
        )
        order_id = cursor.lastrowid
        order_number = f"ORD-{order_id:06d}"
        cursor.execute(
            "UPDATE submitted_orders SET order_number = %s WHERE submitted_order_id = %s",
            (order_number, order_id),
        )
        _record_status_change(cursor, order_id, None, OrderStatus.SUBMITTED.value,
                              created_by, "Paper order captured")

    return get_order(order_id)


def delete_order(order_id):
    """Remove an order and its lines. Only used to roll back a failed capture —
    a photo order whose image never saved has no reason to exist."""
    with mysql_manager.get_cursor() as cursor:
        cursor.execute("DELETE FROM submitted_order_products WHERE submitted_order_id = %s",
                       (order_id,))
        cursor.execute("DELETE FROM submitted_order_attachments WHERE submitted_order_id = %s",
                       (order_id,))
        cursor.execute("DELETE FROM submitted_order_status_history WHERE submitted_order_id = %s",
                       (order_id,))
        cursor.execute("DELETE FROM submitted_orders WHERE submitted_order_id = %s",
                       (order_id,))


def add_attachment(order_id, file_path, mime_type, size_bytes, uploaded_by):
    mysql_manager.execute_query(
        """INSERT INTO submitted_order_attachments
             (submitted_order_id, file_path, mime_type, size_bytes, uploaded_by)
           VALUES (%s,%s,%s,%s,%s)""",
        (order_id, file_path, mime_type, size_bytes, uploaded_by), fetch=False,
    )


def attachments_for(order_id):
    return mysql_manager.execute_query(
        """SELECT attachment_id, submitted_order_id, file_path, mime_type, size_bytes,
                  uploaded_by, uploaded_at
           FROM submitted_order_attachments WHERE submitted_order_id = %s ORDER BY attachment_id""",
        (order_id,),
    ) or []


def clear_attachments(order_id):
    """Remove an order's attachment rows and delete their files from disk.

    Used when a photo order is re-photographed — the old image is superseded.
    """
    import os
    from api.shared import media
    rows = attachments_for(order_id)
    mysql_manager.execute_query(
        "DELETE FROM submitted_order_attachments WHERE submitted_order_id = %s",
        (order_id,), fetch=False,
    )
    for a in rows:
        try:
            os.remove(media.absolute_path(a['file_path']))
        except (OSError, media.MediaError):
            pass  # best-effort: a missing file must not block the replacement


def get_attachment(attachment_id):
    rows = mysql_manager.execute_query(
        """SELECT attachment_id, submitted_order_id, file_path, mime_type
           FROM submitted_order_attachments WHERE attachment_id = %s""",
        (attachment_id,),
    )
    return rows[0] if rows else None


_UNSET = object()


def update_order(order_id, items=None, notes=None, expected_delivery_date=None,
                 company_id=None, dealer_id=_UNSET):
    """Amend an order the creator still owns.

    Only legal while the order is still `submitted` — once it has entered the
    warehouse (Open onward), the floor has acted on it and it is frozen. Passing
    `items` replaces the whole line set (this is how a photographed paper order
    gets its lines entered); passing `dealer_id` reassigns it.
    """
    order = get_order(order_id)
    if not order:
        raise NotFoundError(f"order {order_id} not found")
    if order['status'] != OrderStatus.SUBMITTED.value:
        raise InvalidTransitionError(
            f"cannot edit order in status '{order['status']}' (must be 'submitted')"
        )

    if dealer_id is not _UNSET and dealer_id is not None:
        dealer = mysql_manager.execute_query(
            "SELECT dealer_id, status, company_id FROM dealer WHERE dealer_id = %s", (dealer_id,)
        )
        if not dealer or (dealer[0].get('status') or 'active') != 'active':
            raise ValidationError(f"dealer {dealer_id} not found or inactive")
        if company_id is not None and dealer[0].get('company_id') != company_id:
            raise ValidationError(f"dealer {dealer_id} does not belong to this company")

    resolved = None
    if items is not None:
        if not items:
            raise ValidationError("an order needs at least one item")
        from api.modules.catalog.router_v1 import get_sku
        resolved = []
        for it in items:
            sku = get_sku(it['sku_code'])
            if not sku or not sku['is_active']:
                raise ValidationError(f"sku {it['sku_code']} not found or inactive")
            if company_id is not None and sku.get('company_id') != company_id:
                raise ValidationError(f"sku {it['sku_code']} does not belong to this company")
            resolved.append((sku, it))

    now = now_local()
    with mysql_manager.get_cursor() as cursor:
        sets, params = ["updated_at = %s"], [now]
        if notes is not None:
            sets.append("notes = %s")
            params.append(notes)
        if expected_delivery_date is not None:
            sets.append("expected_delivery_date = %s")
            params.append(expected_delivery_date)
        if dealer_id is not _UNSET and dealer_id is not None:
            sets.append("dealer_id = %s")
            params.append(dealer_id)
        params.append(order_id)
        cursor.execute(
            f"UPDATE submitted_orders SET {', '.join(sets)} WHERE submitted_order_id = %s",
            tuple(params),
        )

        if resolved is not None:
            # Nothing has been picked yet (status is still submitted), so replacing
            # the lines wholesale cannot orphan warehouse progress.
            cursor.execute(
                "DELETE FROM submitted_order_products WHERE submitted_order_id = %s", (order_id,)
            )
            for sku, it in resolved:
                cursor.execute(
                    """INSERT INTO submitted_order_products
                         (submitted_order_id, product_id, sku_code, product_name, uom, quantity,
                          mrp, created_at, updated_at)
                       VALUES (%s,
                               (SELECT product_id FROM product WHERE product_string = %s),
                               %s,%s,%s,%s,%s,%s,%s)""",
                    (order_id, sku['sku_code'], sku['sku_code'], sku['name'], sku['uom'],
                     it['quantity_requested'], sku['price'], now, now),
                )

    return get_order(order_id)


# NOTE: approve_order / reject_order were removed — there is no approve/reject step.
# App orders sit at `submitted` until the DMS-output upload moves them to Open (that
# matching flow is being re-architected). The picking job, previously raised on approve,
# will be raised when the order enters Open under that new design.


def fulfillment_preview(order_id):
    order = get_order(order_id)
    if not order:
        return None

    from api.modules.inventory import service as inventory_service
    from api.modules.catalog.router_v1 import sku_id_for_code

    wh = order['warehouse_id']
    planogram_id = inventory_service.planogram_for_warehouse(wh) if wh is not None else None
    items, all_ok = [], True
    for it in order['items']:
        entity_id = sku_id_for_code(it['sku_code']) if it['sku_code'] else None
        if wh is not None and entity_id is not None:
            # Only stock in picking-enabled locations can fulfil an order — that is
            # primary plus unstacked (see planogram_locations.is_picking_enabled).
            available = inventory_service.pickable_on_hand(entity_id, planogram_id)
            fulfillable = available >= it['quantity_requested']
            if not fulfillable:
                all_ok = False
        else:
            available, fulfillable = None, None
            all_ok = False
        items.append({
            'sku_code': it['sku_code'], 'product_name': it['product_name'], 'uom': it['uom'],
            'quantity_requested': it['quantity_requested'],
            'available': available, 'fulfillable': fulfillable,
        })
    return {'order_id': order_id, 'warehouse_id': wh, 'can_fulfill_all': all_ok, 'items': items}
