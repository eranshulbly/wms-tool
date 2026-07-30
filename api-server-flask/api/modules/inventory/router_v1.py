# -*- encoding: utf-8 -*-
"""
Mobile API — inventory module (/api/v1/inventory/*).

Redesigned around the bin- and batch-level model (GRN_STACKING_DESIGN.md). The old
v2-shaped endpoints could only express a warehouse+sku total, which cannot represent
bins, batches or the movement engine, so the contracts are new:

  GET  /inventory                              module status
  GET  /inventory/locations                    the location master
  GET  /inventory/warehouses                   list
  POST /inventory/warehouses                   create
  GET  /inventory/stock                        bin+batch rows (filterable)
  GET  /inventory/stock/{warehouse_id}/{sku}   one SKU: totals + per-bin breakdown
  GET  /inventory/ledger                       append-only stock ledger
  GET  /inventory/movement-requests            jobs: stacking | picking | moves
  GET  /inventory/movement-requests/{id}       job + details + recommendations

  POST /inventory/stock/receive                501 — GRN flow, next step
  POST /inventory/stock/adjust                 501
  POST /inventory/movement-requests/{id}/complete  501

Wire format stays `sku_code`; the service layer works in numeric entity ids.
"""

from datetime import datetime

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_require_permission
from api.modules.platform.user_auth.rbac import P
from api.modules.inventory import service as svc
from api.modules.platform.catalog.router_v1 import sku_id_for_code, codes_for_sku_ids

NOT_IMPLEMENTED = 501


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _num(v):
    return float(v) if v is not None else None


def _planogram_arg():
    """Callers pass warehouse_id; planogram is 1:1 with it."""
    wid = request.args.get('warehouse_id', type=int)
    return svc.planogram_for_warehouse(wid) if wid is not None else None


def _stock_out(r, sku_map):
    meta = sku_map.get(r['entity_id'], {})
    return {
        "stock_id": r['stock_id'],
        "warehouse_id": r['planogram_id'],
        "location_id": r['location_id'],
        "bin_id": r['bin_id'],
        "bin_location": r['bin_location'],
        "sku_code": meta.get('sku_code'),
        "product_name": meta.get('name'),
        "entity_id": r['entity_id'],
        "entity_type": r['entity_type'],
        "batch_id": r['batch_id'],
        "bin_priority_order": r['bin_priority_order'],
        "quantity": _num(r['quantity']),
        "updated_on": _iso(r['updated_on']),
    }


def _ledger_out(r, sku_map):
    meta = sku_map.get(r['entity_id'], {})
    return {
        "ledger_id": r['ledger_id'],
        "warehouse_id": r['planogram_id'],
        "location_id": r['location_id'],
        "bin_id": r['bin_id'],
        "bin_location": r['bin_location'],
        "sku_code": meta.get('sku_code'),
        "entity_id": r['entity_id'],
        "entity_type": r['entity_type'],
        "batch_id": r['batch_id'],
        "quantity_changed": _num(r['quantity_changed']),
        "quantity_after_change": _num(r['quantity_after_change']),
        "reference_id": r['reference_id'],
        "reference_type": r['reference_type'],
        "cost_price": _num(r['cost_price']),
        "created_by": r['created_by'],
        "created_on": _iso(r['created_on']),
    }


def _request_out(r, with_details=False, sku_map=None):
    out = {
        "request_id": r['request_id'],
        "warehouse_id": r['planogram_id'],
        "movement_type": r['movement_type'],
        "request_status": r['request_status'],
        "reference_type": r.get('reference_type'),
        "request_identifier": r.get('request_identifier'),
        "metadata": r.get('metadata'),
        "created_by": r.get('created_by_id'),
        "created_on": _iso(r['created_on']),
    }
    if with_details:
        sku_map = sku_map or {}
        out['details'] = [{
            "detail_id": d['detail_id'],
            "sku_code": sku_map.get(d['entity_id'], {}).get('sku_code'),
            "entity_id": d['entity_id'],
            "entity_type": d['entity_type'],
            "source_location_id": d['source_location_id'],
            "source_bin_id": d['source_bin_id'],
            "picked_quantity": _num(d['picked_quantity']),
            "underpick_reason_id": d['underpick_reason_id'],
            "recommendations": [{
                "recommendation_id": rc['recommendation_id'],
                "core_recommendation_id": rc['core_recommendation_id'],
                "recommendation_type": rc['recommendation_type'],
                "sequence": rc['sequence'],
                "batch_id": rc['batch_id'],
                "source_location_id": rc['source_location_id'],
                "source_bin_id": rc['source_bin_id'],
                "source_bin_location": rc['source_bin_location'],
                "destination_location_id": rc['destination_location_id'],
                "destination_bin_id": rc['destination_bin_id'],
                "destination_bin_location": rc['destination_bin_location'],
                "operation": rc['operation'],
                "qty_to_process": _num(rc['qty_to_process']),
                "qty_processed": _num(rc['qty_processed']),
                "status": rc['status'],
            } for rc in d.get('recommendations', [])],
        } for d in r.get('details', [])]
    return out


@rest_api.route('/api/v1/inventory')
class V1InventoryStatus(Resource):
    def get(self):
        return {"module": "inventory", "status": "ok"}, 200


@rest_api.route('/api/v1/inventory/locations')
class V1Locations(Resource):
    """The location master — ids are semantic constants (8 = unstacked, 1 = primary …)."""

    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user):
        return [{
            "location_id": r['id'],
            "location_type": r['location_type'],
            "is_picking_enabled": bool(r['is_picking_enabled']),
            "is_bulk_location": bool(r['is_bulk_location']),
            "description": r['location_description'],
        } for r in svc.list_locations()], 200


@rest_api.route('/api/v1/inventory/warehouses')
class V1Warehouses(Resource):
    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user):
        return [{
            "warehouse_id": r['warehouse_id'], "code": r['code'], "name": r['name'],
            "address": r['address'], "is_active": bool(r['is_active']),
            "created_at": _iso(r['created_at']),
        } for r in svc.list_warehouses()], 200

    @v1_require_permission(P.WAREHOUSE_ALL)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        code = (body.get('code') or '').strip()
        name = (body.get('name') or '').strip()
        if not code or not name:
            return {"detail": "code and name are required"}, 422
        try:
            wh = svc.create_warehouse(code, name, body.get('address'))
        except svc.ConflictError as e:
            return {"detail": str(e)}, 409
        return {
            "warehouse_id": wh['warehouse_id'], "code": wh['code'], "name": wh['name'],
            "address": wh['address'], "is_active": bool(wh['is_active']),
            "created_at": _iso(wh['created_at']),
        }, 201


@rest_api.route('/api/v1/inventory/stock')
class V1Stock(Resource):
    """Bin- and batch-level stock. Includes unstacked (location 8) — this is the
    complete on-hand picture."""

    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user):
        a = request.args
        try:
            limit, offset = int(a.get('limit', 200)), int(a.get('offset', 0))
        except ValueError:
            return {"detail": "limit/offset must be integers"}, 422

        entity_id = None
        if a.get('sku_code'):
            entity_id = sku_id_for_code(a['sku_code'])
            if entity_id is None:
                return {"detail": f"sku {a['sku_code']} not found"}, 404

        rows = svc.list_stock(
            planogram_id=_planogram_arg(), entity_id=entity_id,
            location_id=a.get('location_id', type=int),
            bin_id=a.get('bin_id', type=int), batch_id=a.get('batch_id', type=int),
            limit=limit, offset=offset,
        )
        sku_map = codes_for_sku_ids([r['entity_id'] for r in rows])
        return [_stock_out(r, sku_map) for r in rows], 200


@rest_api.route('/api/v1/inventory/stock/<int:warehouse_id>/<string:sku_code>')
class V1StockDetail(Resource):
    """One SKU at one warehouse: totals plus the per-bin/batch breakdown, and where the
    unstacked portion came from."""

    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user, warehouse_id, sku_code):
        entity_id = sku_id_for_code(sku_code)
        if entity_id is None:
            return {"detail": f"sku {sku_code} not found"}, 404

        planogram_id = svc.planogram_for_warehouse(warehouse_id)
        breakdown = svc.stock_breakdown(entity_id, planogram_id)
        sku_map = codes_for_sku_ids([entity_id])

        return {
            "warehouse_id": warehouse_id,
            "sku_code": sku_code,
            "entity_id": entity_id,
            "total_quantity": breakdown['total_quantity'],
            "pickable_quantity": breakdown['pickable_quantity'],
            "stock": [_stock_out(r, sku_map) for r in breakdown['rows']],
            "unstacked_sources": [{
                "transferin_info_id": u['transferin_info_id'],
                "transferin_id": u['transferin_id'],
                "batch_id": u['batch_id'],
                "quantity": _num(u['quantity']),
                "unstacked_quantity": _num(u['unstacked_quantity']),
                "mrp": _num(u['mrp']),
                "cost_price": _num(u['cost_price']),
                "status": u['transferin_status'],
                "created_on": _iso(u['created_on']),
            } for u in svc.unstacked_breakdown(entity_id, planogram_id)],
        }, 200


@rest_api.route('/api/v1/inventory/ledger')
class V1Ledger(Resource):
    """Append-only record of every stock change."""

    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user):
        a = request.args
        try:
            limit, offset = int(a.get('limit', 100)), int(a.get('offset', 0))
        except ValueError:
            return {"detail": "limit/offset must be integers"}, 422

        entity_id = None
        if a.get('sku_code'):
            entity_id = sku_id_for_code(a['sku_code'])
            if entity_id is None:
                return {"detail": f"sku {a['sku_code']} not found"}, 404

        rows = svc.list_ledger(
            planogram_id=_planogram_arg(), entity_id=entity_id,
            batch_id=a.get('batch_id', type=int), reference_type=a.get('reference_type'),
            limit=limit, offset=offset,
        )
        sku_map = codes_for_sku_ids([r['entity_id'] for r in rows])
        return [_ledger_out(r, sku_map) for r in rows], 200


@rest_api.route('/api/v1/inventory/movement-requests')
class V1MovementRequests(Resource):
    """Warehouse jobs: stacking, picking and stock moves all live here."""

    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user):
        a = request.args
        try:
            limit, offset = int(a.get('limit', 50)), int(a.get('offset', 0))
        except ValueError:
            return {"detail": "limit/offset must be integers"}, 422

        rows = svc.list_movement_requests(
            planogram_id=_planogram_arg(),
            movement_type=a.get('movement_type'),
            request_status=a.get('status'),
            reference_type=a.get('reference_type'),
            request_identifier=a.get('order_id', type=int),
            limit=limit, offset=offset,
        )
        return [_request_out(r) for r in rows], 200


@rest_api.route('/api/v1/inventory/movement-requests/<int:request_id>')
class V1MovementRequestDetail(Resource):
    @v1_require_permission(P.INVENTORY_READ)
    def get(self, current_user, request_id):
        req = svc.get_movement_request(request_id)
        if not req:
            return {"detail": f"movement request {request_id} not found"}, 404
        sku_map = codes_for_sku_ids([d['entity_id'] for d in req.get('details', [])])
        return _request_out(req, with_details=True, sku_map=sku_map), 200


# ── Write flows — next step ──────────────────────────────────────────────────
@rest_api.route('/api/v1/inventory/stock/receive')
class V1StockReceive(Resource):
    @v1_require_permission(P.INVENTORY_MOVE)
    def post(self, current_user):
        return {"detail": svc._NOT_BUILT, "flow": "grn"}, NOT_IMPLEMENTED


@rest_api.route('/api/v1/inventory/stock/adjust')
class V1StockAdjust(Resource):
    @v1_require_permission(P.INVENTORY_MOVE)
    def post(self, current_user):
        return {"detail": svc._NOT_BUILT, "flow": "adjust"}, NOT_IMPLEMENTED


@rest_api.route('/api/v1/inventory/movement-requests/<int:request_id>/complete')
class V1MovementRequestComplete(Resource):
    @v1_require_permission(P.INVENTORY_PICK)
    def post(self, current_user, request_id):
        return {"detail": svc._NOT_BUILT, "flow": "stacking/picking"}, NOT_IMPLEMENTED
