# -*- encoding: utf-8 -*-
"""
Mobile API — catalog module (/api/v1/catalog/*).

A v2 "SKU" is this backend's `product`; `sku_code` is `product.product_string`
(unique). Categories are the new `categories` table. Contracts match
wms-v2-backend exactly — see docs/V2_API_PORT.md.
"""

from datetime import datetime

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.shared.db_manager import mysql_manager
from api.shared.auth_v1 import v1_require_permission, company_filter, company_scope
from api.modules.user_auth.rbac import P

SKU_COLS = """product_string AS sku_code, name, description, nickname, category_id,
              uom, size, weight, barcode, hsn_code, price, is_active, created_at,
              company_id"""


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


def _sku_out(r):
    return {
        "sku_code": r['sku_code'], "name": r['name'], "description": r['description'],
        "nickname": r['nickname'], "category_id": r['category_id'], "uom": r['uom'],
        "size": r['size'], "weight": float(r['weight']) if r['weight'] is not None else None,
        "barcode": r['barcode'], "hsn_code": r['hsn_code'],
        "price": float(r['price']) if r['price'] is not None else None,
        "is_active": bool(r['is_active']), "created_at": _iso(r['created_at']),
    }


def _category_out(r):
    return {
        "category_id": r['category_id'], "name": r['name'], "parent_id": r['parent_id'],
        "description": r['description'], "is_active": bool(r['is_active']),
        "created_at": _iso(r['created_at']),
    }


def get_sku(sku_code, current_user=None):
    """Fetch one SKU. Pass current_user to restrict it to that caller's companies
    (used by the read/update routes so a scoped user can't reach another
    company's SKU by guessing its code)."""
    sql = f"SELECT {SKU_COLS} FROM product WHERE product_string = %s"
    params = [sku_code]
    if current_user is not None:
        frag, fparams = company_filter(current_user)
        if frag:
            sql += f" AND {frag}"
            params.extend(fparams)
    rows = mysql_manager.execute_query(sql, tuple(params))
    return rows[0] if rows else None


def sku_exists(sku_code):
    """Cross-module helper: True when the SKU exists and is active."""
    r = get_sku(sku_code)
    return bool(r) and bool(r['is_active'])


# ── sku_code <-> numeric id ──────────────────────────────────────────────────
# The inventory model is keyed on the NUMERIC sku id (entity_id == product.product_id,
# == sku_batch.sku_id), while the API speaks sku_code (product.product_string).
# These translate at the boundary so the service layer can work in ids.

def sku_id_for_code(sku_code):
    """Numeric product id for a sku_code, or None."""
    rows = mysql_manager.execute_query(
        "SELECT product_id FROM product WHERE product_string = %s", (sku_code,)
    )
    return rows[0]['product_id'] if rows else None


def codes_for_sku_ids(sku_ids):
    """{product_id: sku_code} for a batch of ids — avoids N+1 when listing stock."""
    ids = [int(i) for i in set(sku_ids or []) if i is not None]
    if not ids:
        return {}
    rows = mysql_manager.execute_query(
        "SELECT product_id, product_string, name FROM product WHERE product_id IN (%s)"
        % ','.join(['%s'] * len(ids)), tuple(ids)
    ) or []
    return {r['product_id']: {'sku_code': r['product_string'], 'name': r['name']} for r in rows}


@rest_api.route('/api/v1/catalog')
class V1CatalogStatus(Resource):
    def get(self):
        return {"module": "catalog", "status": "ok"}, 200


@rest_api.route('/api/v1/catalog/categories')
class V1Categories(Resource):
    @v1_require_permission(P.CATALOG_READ)
    def get(self, current_user):
        rows = mysql_manager.execute_query(
            """SELECT category_id, name, parent_id, description, is_active, created_at
               FROM categories ORDER BY name"""
        ) or []
        return [_category_out(r) for r in rows], 200

    @v1_require_permission(P.CATALOG_MANAGE)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        name = (body.get('name') or '').strip()
        if not name or len(name) > 100:
            return {"detail": "name is required (max 100 chars)"}, 422

        if mysql_manager.execute_query("SELECT category_id FROM categories WHERE name = %s", (name,)):
            return {"detail": f"category '{name}' already exists"}, 409

        parent_id = body.get('parent_id')
        if parent_id is not None and not mysql_manager.execute_query(
            "SELECT category_id FROM categories WHERE category_id = %s", (parent_id,)
        ):
            return {"detail": f"parent category {parent_id} not found"}, 400

        mysql_manager.execute_query(
            "INSERT INTO categories (name, parent_id, description) VALUES (%s, %s, %s)",
            (name, parent_id, body.get('description')), fetch=False,
        )
        r = mysql_manager.execute_query(
            """SELECT category_id, name, parent_id, description, is_active, created_at
               FROM categories WHERE name = %s""", (name,)
        )[0]
        return _category_out(r), 201


@rest_api.route('/api/v1/catalog/skus')
class V1Skus(Resource):
    @v1_require_permission(P.CATALOG_READ)
    def get(self, current_user):
        active_only = str(request.args.get('active_only', 'false')).lower() == 'true'
        try:
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
        except ValueError:
            return {"detail": "limit/offset must be integers"}, 422

        conds, params = [], []
        if active_only:
            conds.append("is_active = 1")
        # Catalog is company-scoped: a SKU with no company belongs to nobody and
        # stays hidden until an admin assigns it.
        frag, fparams = company_filter(current_user)
        if frag:
            conds.append(frag)
            params.extend(fparams)

        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = mysql_manager.execute_query(
            f"SELECT {SKU_COLS} FROM product {where} ORDER BY name LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        ) or []
        return [_sku_out(r) for r in rows], 200

    @v1_require_permission(P.CATALOG_MANAGE)
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        sku_code = (body.get('sku_code') or '').strip()
        name = (body.get('name') or '').strip()
        if not sku_code or not name:
            return {"detail": "sku_code and name are required"}, 422

        if get_sku(sku_code):
            return {"detail": f"sku_code '{sku_code}' already exists"}, 409

        barcode = body.get('barcode')
        if barcode and mysql_manager.execute_query(
            "SELECT product_id FROM product WHERE barcode = %s", (barcode,)
        ):
            return {"detail": f"barcode '{barcode}' already exists"}, 409

        category_id = body.get('category_id')
        if category_id is not None and not mysql_manager.execute_query(
            "SELECT category_id FROM categories WHERE category_id = %s", (category_id,)
        ):
            return {"detail": f"category {category_id} not found"}, 400

        # Stamp the owning company, else a scoped user creates SKUs they can't see.
        company_id = body.get('company_id')
        scoped = company_scope(current_user)
        if scoped is not None:
            if not scoped:
                return {"detail": "no company assigned — ask an admin for access"}, 403
            if company_id is None:
                if len(scoped) > 1:
                    return {"detail": "company_id is required (you have several)"}, 422
                company_id = scoped[0]
            elif company_id not in scoped:
                return {"detail": f"company {company_id} is not yours"}, 403

        mysql_manager.execute_query(
            """INSERT INTO product (product_string, name, description, nickname, category_id,
                                    uom, size, weight, barcode, hsn_code, price, is_active,
                                    company_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)""",
            (sku_code, name, body.get('description'), body.get('nickname'), category_id,
             body.get('uom'), body.get('size'), body.get('weight'), barcode,
             body.get('hsn_code'), body.get('price'), company_id),
            fetch=False,
        )
        return _sku_out(get_sku(sku_code)), 201


@rest_api.route('/api/v1/catalog/skus/<string:sku_code>')
class V1SkuDetail(Resource):
    @v1_require_permission(P.CATALOG_READ)
    def get(self, current_user, sku_code):
        r = get_sku(sku_code, current_user)
        if not r:
            return {"detail": f"sku {sku_code} not found"}, 404
        return _sku_out(r), 200

    @v1_require_permission(P.CATALOG_MANAGE)
    def patch(self, current_user, sku_code):
        existing = get_sku(sku_code, current_user)
        if not existing:
            return {"detail": f"sku {sku_code} not found"}, 404

        body = request.get_json(silent=True) or {}
        barcode = body.get('barcode')
        if barcode and barcode != existing['barcode'] and mysql_manager.execute_query(
            "SELECT product_id FROM product WHERE barcode = %s", (barcode,)
        ):
            return {"detail": f"barcode '{barcode}' already exists"}, 409

        category_id = body.get('category_id')
        if category_id is not None and not mysql_manager.execute_query(
            "SELECT category_id FROM categories WHERE category_id = %s", (category_id,)
        ):
            return {"detail": f"category {category_id} not found"}, 400

        # v2 quirk preserved: only non-None values are applied (a field cannot be
        # cleared to NULL through this endpoint).
        updatable = ['name', 'description', 'nickname', 'category_id', 'uom', 'size',
                     'weight', 'barcode', 'hsn_code', 'price', 'is_active']
        sets, params = [], []
        for field in updatable:
            if field in body and body[field] is not None:
                sets.append(f"{field} = %s")
                params.append(body[field])
        if sets:
            params.append(sku_code)
            mysql_manager.execute_query(
                f"UPDATE product SET {', '.join(sets)} WHERE product_string = %s",
                tuple(params), fetch=False,
            )
        return _sku_out(get_sku(sku_code)), 200
