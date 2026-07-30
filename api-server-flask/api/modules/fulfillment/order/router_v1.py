# -*- encoding: utf-8 -*-
"""
Mobile API — order module (/api/v1/orders/*).

Contracts match wms-v2-backend; storage is the app's own submitted_* tables
(see modules/order/schema.py and service_v1.py), no longer shared with the warehouse
app's potential_order (see docs/V2_API_PORT.md).
"""

import os
from datetime import datetime, date

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.shared import media
from api.shared.auth_v1 import v1_require_permission
from api.modules.platform.user_auth.rbac import P
from api.modules.fulfillment.order import service_v1 as svc


def _iso(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two points, or None if any is missing.

    Haversine — accurate to well within a metre at the ranges that matter here
    (a rep standing at, or near, a dealer's shop).
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    import math
    r = 6371000.0  # mean earth radius, metres
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(r * 2 * math.asin(math.sqrt(a)), 1)


def _item_out(i):
    return {
        "order_item_id": i['order_item_id'], "sku_code": i['sku_code'],
        "product_name": i['product_name'], "uom": i['uom'],
        "quantity_requested": i['quantity_requested'],
        "quantity_fulfilled": i['quantity_fulfilled'], "status": i['status'],
    }


def _company_scope(current_user):
    """None => the caller sees every company; a list => restrict to it."""
    return None if current_user['has_all_companies'] else current_user['company_ids']


def _creator_scope(current_user):
    """None => the caller sees every order in scope; a user id => only their own.

    Company users raise orders but don't oversee the order book, so they get
    order:read but not order:read_all.
    """
    if P.ORDER_READ_ALL in (current_user.get('permissions') or []):
        return None
    return current_user['user_id']


def _visible_order(current_user, order_id):
    """The order as this caller may see it, or None (callers 404 on None)."""
    return svc.get_order(order_id,
                         company_ids=_company_scope(current_user),
                         created_by=_creator_scope(current_user))


def _order_out(o):
    return {
        "order_id": o['order_id'], "order_number": o['order_number'],
        "dealer_id": o['dealer_id'], "created_by": o['created_by'],
        "company_id": o.get('company_id'), "company_name": o.get('company_name'),
        "warehouse_id": o['warehouse_id'], "status": o['status'],
        "approved_by": o['approved_by'], "approved_at": _iso(o['approved_at']),
        "rejection_reason": o['rejection_reason'], "notes": o['notes'],
        "submitted_at": _iso(o['submitted_at']),
        "expected_delivery_date": _iso(o['expected_delivery_date']),
        "created_at": _iso(o['created_at']),
        "latitude": float(o['latitude']) if o.get('latitude') is not None else None,
        "longitude": float(o['longitude']) if o.get('longitude') is not None else None,
        "location_accuracy_m": o.get('location_accuracy_m'),
        "location_captured_at": _iso(o.get('location_captured_at')),
        # How far the rep stood from the dealer's shop when raising the order.
        "distance_from_dealer_m": _distance_m(
            o.get('latitude'), o.get('longitude'),
            o.get('dealer_lat'), o.get('dealer_lng')),
        "items": [_item_out(i) for i in o.get('items', [])],
        "attachments": [
            {
                "attachment_id": a['attachment_id'],
                "mime_type": a['mime_type'],
                "size_bytes": a['size_bytes'],
                "uploaded_at": _iso(a['uploaded_at']),
                # Relative to the API root; the client appends it to its base URL.
                "url": f"/orders/{o['order_id']}/photo/{a['attachment_id']}",
            }
            for a in svc.attachments_for(o['order_id'])
        ],
    }


@rest_api.route('/api/v1/orders')
class V1Orders(Resource):
    def get(self):
        return {"module": "order", "status": "ok"}, 200

    @v1_require_permission(P.ORDER_WRITE)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        dealer_id = body.get('dealer_id')
        items = body.get('items') or []
        if not dealer_id or not items:
            return {"detail": "dealer_id and at least one item are required"}, 422

        seen = set()
        for it in items:
            sku = it.get('sku_code')
            qty = it.get('quantity_requested')
            if not sku or not isinstance(qty, int) or qty <= 0:
                return {"detail": "each item needs sku_code and quantity_requested > 0"}, 422
            if sku in seen:
                return {"detail": "duplicate sku_code in order items"}, 422
            seen.add(sku)

        # Where the rep was standing. Required: orders are audited against the
        # dealer's location, so one without coordinates is not worth recording.
        lat, lng = body.get('latitude'), body.get('longitude')
        if lat is None or lng is None:
            return {"detail": "latitude and longitude are required"}, 422
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return {"detail": "latitude/longitude must be numbers"}, 422
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return {"detail": "latitude/longitude out of range"}, 422
        accuracy = body.get('location_accuracy_m')
        try:
            accuracy = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            accuracy = None

        # Stamp the owning company, else the new order is invisible to its creator.
        company_id = body.get('company_id')
        scoped = _company_scope(current_user)
        if scoped is not None:
            if not scoped:
                return {"detail": "no company assigned — ask an admin for access"}, 403
            if company_id is None:
                if len(scoped) > 1:
                    return {"detail": "company_id is required (you have several)"}, 422
                company_id = scoped[0]
            elif company_id not in scoped:
                return {"detail": f"company {company_id} is not yours"}, 403

        # Same for the warehouse: a NULL warehouse_id is excluded by the caller's own
        # `warehouse_id IN (...)` scope, so the order would vanish from their list.
        warehouse_id = body.get('warehouse_id')
        if warehouse_id is None and not current_user['has_all_warehouses']:
            granted = current_user['warehouse_ids'] or []
            if len(granted) == 1:
                warehouse_id = granted[0]

        try:
            order = svc.create_order(
                dealer_id=dealer_id, items=items, created_by=current_user['user_id'],
                warehouse_id=warehouse_id,
                expected_delivery_date=body.get('expected_delivery_date'),
                notes=body.get('notes'), company_id=company_id,
                latitude=lat, longitude=lng, location_accuracy_m=accuracy,
            )
        except svc.ValidationError as e:
            return {"detail": str(e)}, 400
        return _order_out(order), 201


@rest_api.route('/api/v1/orders/photo')
class V1PhotoOrder(Resource):
    """Capture a paper order as a photo (multipart/form-data).

    Fields: dealer_id, latitude, longitude, [location_accuracy_m], [notes], photo.
    Creates the order in `submitted` with no line items; the back office
    transcribes it later via PATCH /orders/<id>. An order with no lines can't be
    approved, so it can't slip through the warehouse before it is entered.
    """

    @v1_require_permission(P.ORDER_WRITE)
    def post(self, current_user):
        form = request.form
        dealer_id = form.get('dealer_id', type=int)
        if not dealer_id:
            return {"detail": "dealer_id is required"}, 422

        lat, lng = form.get('latitude'), form.get('longitude')
        if lat is None or lng is None:
            return {"detail": "latitude and longitude are required"}, 422
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            return {"detail": "latitude/longitude must be numbers"}, 422
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return {"detail": "latitude/longitude out of range"}, 422
        try:
            accuracy = float(form['location_accuracy_m']) if form.get('location_accuracy_m') else None
        except (TypeError, ValueError):
            accuracy = None

        photo = request.files.get('photo')
        if photo is None:
            return {"detail": "a photo of the order is required"}, 422

        company_id = form.get('company_id', type=int)
        scoped = _company_scope(current_user)
        if scoped is not None:
            if not scoped:
                return {"detail": "no company assigned — ask an admin for access"}, 403
            if company_id is None:
                if len(scoped) > 1:
                    return {"detail": "company_id is required (you have several)"}, 422
                company_id = scoped[0]
            elif company_id not in scoped:
                return {"detail": f"company {company_id} is not yours"}, 403

        warehouse_id = form.get('warehouse_id', type=int)
        if warehouse_id is None and not current_user['has_all_warehouses']:
            granted = current_user['warehouse_ids'] or []
            if len(granted) == 1:
                warehouse_id = granted[0]

        try:
            order = svc.create_photo_order(
                dealer_id=dealer_id, created_by=current_user['user_id'],
                company_id=company_id, warehouse_id=warehouse_id,
                notes=form.get('notes'), latitude=lat, longitude=lng,
                location_accuracy_m=accuracy,
            )
        except svc.ValidationError as e:
            return {"detail": str(e)}, 400

        try:
            path, mime, size = media.save_order_photo(photo, order['order_id'])
        except media.MediaError as e:
            # The order row exists but has no photo, which is the whole point of it —
            # drop it rather than leave a useless shell behind.
            svc.delete_order(order['order_id'])
            return {"detail": str(e)}, 422

        svc.add_attachment(order['order_id'], path, mime, size, current_user['user_id'])
        return _order_out(svc.get_order(order['order_id'])), 201


@rest_api.route('/api/v1/orders/<int:order_id>/photo/<int:attachment_id>')
class V1OrderPhoto(Resource):
    """Serve an order photo to someone allowed to see that order."""

    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user, order_id, attachment_id):
        if not _visible_order(current_user, order_id):
            return {"detail": f"order {order_id} not found"}, 404
        att = svc.get_attachment(attachment_id)
        if not att or att['submitted_order_id'] != order_id:
            return {"detail": "attachment not found"}, 404
        try:
            path = media.absolute_path(att['file_path'])
        except media.MediaError as e:
            return {"detail": str(e)}, 400
        if not os.path.exists(path):
            return {"detail": "attachment file is missing"}, 404
        return send_file(path, mimetype=att['mime_type'] or 'image/jpeg')


@rest_api.route('/api/v1/orders/list')
class V1OrderList(Resource):
    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user):
        a = request.args
        try:
            limit, offset = int(a.get('limit', 50)), int(a.get('offset', 0))
        except ValueError:
            return {"detail": "limit/offset must be integers"}, 422

        scoped = None if current_user['has_all_warehouses'] else current_user['warehouse_ids']

        # Salesperson filter: only users who can see others' orders (order:read_all)
        # may filter by creator. For everyone else the own-orders scope stands.
        created_by = _creator_scope(current_user)
        if created_by is None:
            created_by = a.get('created_by', type=int)

        rows = svc.list_orders(
            status=a.get('status'), dealer_id=a.get('dealer_id'),
            warehouse_id=a.get('warehouse_id', type=int), date_from=a.get('date_from'),
            date_to=a.get('date_to'), sku_code=a.get('sku_code'),
            warehouse_ids=scoped, company_ids=_company_scope(current_user),
            created_by=created_by, company_id=a.get('company_id', type=int),
            limit=limit, offset=offset,
        )
        return [{
            "order_id": r['order_id'], "order_number": r['order_number'],
            "dealer_id": r['dealer_id'], "status": r['status'],
            "company_id": r['company_id'], "company_name": r['company_name'],
            "warehouse_id": r['warehouse_id'], "created_at": _iso(r['created_at']),
            "created_by": r['created_by'],
        } for r in rows], 200


@rest_api.route('/api/v1/orders/<int:order_id>')
class V1OrderDetail(Resource):
    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user, order_id):
        order = _visible_order(current_user, order_id)
        if not order:
            return {"detail": f"order {order_id} not found"}, 404
        return _order_out(order), 200

    @v1_require_permission(P.ORDER_WRITE)
    def patch(self, current_user, order_id):
        """Amend an order you raised, while it is still awaiting approval."""
        order = _visible_order(current_user, order_id)
        if not order:
            return {"detail": f"order {order_id} not found"}, 404

        body = request.get_json(silent=True) or {}
        items = body.get('items')
        if items is not None:
            if not items:
                return {"detail": "an order needs at least one item"}, 422
            seen = set()
            for it in items:
                sku = it.get('sku_code')
                qty = it.get('quantity_requested')
                if not sku or not isinstance(qty, int) or qty <= 0:
                    return {"detail": "each item needs sku_code and quantity_requested > 0"}, 422
                if sku in seen:
                    return {"detail": "duplicate sku_code in order items"}, 422
                seen.add(sku)

        # 'dealer_id' only counts as a change when the key is present, so a plain
        # notes edit doesn't clear it.
        dealer_id = body['dealer_id'] if 'dealer_id' in body else svc._UNSET

        try:
            updated = svc.update_order(
                order_id, items=items, notes=body.get('notes'),
                expected_delivery_date=body.get('expected_delivery_date'),
                company_id=order.get('company_id'), dealer_id=dealer_id,
            )
        except svc.ValidationError as e:
            return {"detail": str(e)}, 400
        except svc.InvalidTransitionError as e:
            return {"detail": str(e)}, 409
        except svc.NotFoundError as e:
            return {"detail": str(e)}, 404
        return _order_out(updated), 200


@rest_api.route('/api/v1/orders/<int:order_id>/photo')
class V1OrderPhotoReplace(Resource):
    """Replace the photo on a captured paper order (multipart, field 'photo').

    Only while the order is still `submitted` (before approval) — once it is
    approved or rejected, the image is a fixed record.
    """

    @v1_require_permission(P.ORDER_WRITE)
    def post(self, current_user, order_id):
        order = _visible_order(current_user, order_id)
        if not order:
            return {"detail": f"order {order_id} not found"}, 404
        if order['status'] != 'submitted':
            return {"detail": "the photo can only be changed before approval"}, 409

        photo = request.files.get('photo')
        if photo is None:
            return {"detail": "a photo file is required"}, 422
        try:
            path, mime, size = media.save_order_photo(photo, order_id)
        except media.MediaError as e:
            return {"detail": str(e)}, 422

        svc.clear_attachments(order_id)
        svc.add_attachment(order_id, path, mime, size, current_user['user_id'])
        return _order_out(svc.get_order(order_id)), 200


# The /approve and /reject endpoints were removed — there is no approve/reject step.
# App orders enter the warehouse (Open) via the DMS-output upload (being re-architected).


@rest_api.route('/api/v1/orders/<int:order_id>/fulfillment')
class V1OrderFulfillment(Resource):
    @v1_require_permission(P.ORDER_READ)
    def get(self, current_user, order_id):
        if not _visible_order(current_user, order_id):
            return {"detail": f"order {order_id} not found"}, 404
        preview = svc.fulfillment_preview(order_id)
        if preview is None:
            return {"detail": f"order {order_id} not found"}, 404
        return preview, 200
