# -*- encoding: utf-8 -*-
"""
Mobile API — catalog module (/api/v1/catalog/*).

A v2 "SKU" is this backend's `product`; `sku_code` is `product.product_string`
(unique). Categories are the new `categories` table. Contracts match
wms-v2-backend exactly — see docs/V2_API_PORT.md.
"""

import hashlib
from datetime import datetime

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.shared.auth_v1 import v1_require_permission, company_filter, company_scope
from api.modules.platform.user_auth.rbac import P

logger = get_logger(__name__)

# product_id is selected but never serialised: it is the key _skus_out joins the
# packaging ladder and the price/stock rows on. Leaving it out made both lookups
# silently receive an empty id list, so every SKU went out with `order_units: []`
# — the app then showed one quantity box for a product that can only be ordered
# by the box or the case, and nothing anywhere errored.
SKU_COLS = """product_id, product_string AS sku_code, name, description, nickname,
              category_id, uom, size, weight, barcode, hsn_code, price, is_active,
              created_at, company_id"""


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else dt


# ── Orderable units ──────────────────────────────────────────────────────────────
#
# What units a product may be ordered in comes from its packaging ladder, per product —
# NOT from a rule about the company. Cadila's tablets can only be ordered by the box or
# the case; a Hero part is ordered in pieces; both are the same statement expressed as
# product_uom rows, so the app renders whatever it is given and needs no notion of who
# the supplier is.
#
# A product with no ladder returns an empty list, which the app reads as "one implicit
# unit" — exactly today's behaviour for all 60k Hero parts, so nothing changes for them.
#
# `qty_in_price_uom` is the multiplier the app shows the rep ("2 CASE = 3,960 strips")
# and submits the order in. Sent rather than derived client-side so the conversion has
# one definition, on the server, next to the data it comes from.

def order_units_for(product_ids):
    """{product_id: {'price_uom': code, 'order_units': [...]}} for the given products.

    ONE query for the whole page. The picker fetches up to 5000 SKUs, so a per-SKU
    lookup here would be 5000 round trips — the N+1 the coding standards call out, and
    the same shape of bug that made this endpoint take two minutes before.
    """
    if not product_ids:
        return {}
    ids = list(product_ids)
    out = {}
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        ph = ','.join(['%s'] * len(chunk))
        for r in (mysql_manager.execute_query(
                f"""SELECT product_id, uom_code, factor_to_base, label, level_no,
                           is_order_unit, is_price_unit
                      FROM product_uom
                     WHERE product_id IN ({ph})
                     ORDER BY product_id, level_no""", tuple(chunk)) or []):
            out.setdefault(r['product_id'], []).append(r)

    shaped = {}
    for pid, rungs in out.items():
        price_rung = next((r for r in rungs if r['is_price_unit']), None)
        price_factor = price_rung['factor_to_base'] if price_rung else None
        shaped[pid] = {
            'price_uom': price_rung['uom_code'] if price_rung else None,
            'order_units': [{
                'code': r['uom_code'],
                'label': r['label'],
                # How many priced units one of these is. 1 when nothing is priced, so
                # the app still has a usable multiplier rather than a null.
                'qty_in_price_uom': float(r['factor_to_base'] / price_factor)
                                    if price_factor else 1.0,
            } for r in rungs if r['is_order_unit']],
        }
    return shaped


# The working set, as a FROM clause: parts sold in the last 6 months plus this
# month's target part groups, joined to the catalogue. The sales window is
# bounded so this can't grow without limit as history accumulates.
#
# Joined as a derived table, driving from it, rather than
# `product_string IN (SELECT ... UNION ...)`:
#
#  * The IN form was rated a DEPENDENT SUBQUERY with a DEPENDENT UNION — i.e.
#    re-executed for each of ~54k candidate product rows. It ran for over two
#    minutes, past both the app's 30s receive timeout (the picker just spun) and
#    PyMySQL's 60s read_timeout, whose broken connection then made the failing
#    rollback mask the real error. Joining evaluates the set once.
#  * STRAIGHT_JOIN pins the small side first. Left to itself MySQL drove from
#    `product` — a 54k-row scan plus a filesort for ORDER BY name — and probed the
#    derived set: 2.4s. Driving from the working set makes the catalogue an eq_ref
#    hit on uq_product_string and sorts only the ~3.7k surviving rows: 204ms.
#    Safe to pin, because the working set is by construction a subset of the
#    catalogue and so always the smaller input.
#
# UNION already dedupes, so this cannot multiply rows. Verified row-for-row
# against the IN form, and against the join without STRAIGHT_JOIN.
#
# (%% because execute_query runs `query % params`, so a literal % must be doubled.)
# The working set is the whole active catalogue. It used to be the subset of parts
# a company had actually traded (derived from the Busy sales feed and target part
# groups), but this deployment has neither — sales arrive as uploaded invoices — and
# its catalogue is small enough to hold and search on the device in full.
_WORKING_SET_FROM = "product "


def _has_working_set(current_user):
    """Whether there is a catalogue to serve as the working set.

    The working set is now the full active catalogue, so this is simply whether any
    product exists. Kept as a function so the caller's branch reads unchanged.
    """
    return bool(mysql_manager.execute_query(
        "SELECT 1 FROM product LIMIT 1"))


# ── Pricing and stock, for the pack-and-price order flow ─────────────────────────
#
# A rep pricing an order at the counter needs three things the catalogue alone does not
# carry: what the product retails at (mrp), what it costs us (the rate a margin is
# applied to), and whether there is any to sell. All three are per company, and the
# first two are per BATCH — so this mirrors price_for()'s rule (most recently received
# batch, else the batch-0 list rate) rather than inventing a second one.
#
# One query for the page, for the same reason order_units_for is: the picker asks for up
# to 5000 SKUs and a per-SKU lookup here would be 5000 round trips.

def pricing_for(product_ids, company_id):
    """{product_id: {'mrp', 'rate', 'gst_rate', 'stock_qty'}} for the given products.

    `rate` is landing price net of credit note — the same figure price_for() calls
    `amount`, and the basis a margin is applied to. None where nobody has priced the
    product, which the app must show as "no rate" rather than as zero.
    """
    if not product_ids or company_id is None:
        return {}
    ids = list(product_ids)
    out = {}
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        ph = ','.join(['%s'] * len(chunk))
        # One price row per product, chosen by the COSTLIEST received batch.
        #
        # Not the newest. A product sitting on two batches will be shipped from
        # whichever the warehouse picks, so pricing off the cheaper one quietly
        # sells the dearer stock below the margin the rep thought they were
        # taking. Costliest-first makes the quoted margin a floor rather than an
        # average, and it is the only choice that cannot lose money on the mix.
        #
        # Batch 0 is excluded outright, not merely ranked last. It is the supplier's
        # RATE LIST, written with quantity_received = 0 — a price for goods that
        # never arrived. Quoting from it means quoting a cost nobody has paid, so a
        # product with no received batch is reported as HAVING NO RATE rather than
        # being valued off the list. The app already renders that state ("no rate on
        # file — the office will price this line"), which is the honest answer.
        #
        # created_on breaks a tie between two batches at the same cost.
        for r in (mysql_manager.execute_query(
                f"""SELECT entity_id, mrp, (landing_price - cn_rate) AS rate, gst_rate
                      FROM (SELECT entity_id, mrp, landing_price, cn_rate, gst_rate,
                                   ROW_NUMBER() OVER (PARTITION BY entity_id
                                       ORDER BY (landing_price - cn_rate) DESC,
                                                created_on DESC) AS rn
                              FROM fc_sku_price_details
                             WHERE entity_type = 'sku' AND company_id = %s
                               AND batch_id <> 0
                               AND entity_id IN ({ph})) ranked
                     WHERE rn = 1""", (company_id, *chunk)) or []):
            out[r['entity_id']] = {
                'mrp': float(r['mrp']) if r['mrp'] is not None else None,
                'rate': float(r['rate']) if r['rate'] is not None else None,
                'gst_rate': float(r['gst_rate']) if r['gst_rate'] is not None else None,
                'stock_qty': 0.0,
            }
        # Stock is held per batch and per bin, so a product's sellable quantity is the
        # sum across them — in the priced unit, which is what the ladder converts to.
        for r in (mysql_manager.execute_query(
                f"""SELECT entity_id, COALESCE(SUM(quantity), 0) AS qty
                      FROM fc_entity_stock
                     WHERE entity_type = 'sku' AND company_id = %s
                       AND entity_id IN ({ph})
                     GROUP BY entity_id""", (company_id, *chunk)) or []):
            out.setdefault(r['entity_id'], {'mrp': None, 'rate': None, 'gst_rate': None})
            out[r['entity_id']]['stock_qty'] = float(r['qty'] or 0)
    return out


def _sku_out(r, packing=None, pricing=None):
    """One SKU as JSON. `packing` is this product's entry from order_units_for(), when
    the caller has fetched them — omitted, the SKU simply carries no order units and the
    app falls back to a single implicit unit."""
    packing = packing or {}
    return {
        "sku_code": r['sku_code'], "name": r['name'], "description": r['description'],
        "category_id": r['category_id'], "uom": r['uom'],
        "size": r['size'], "weight": float(r['weight']) if r['weight'] is not None else None,
        "barcode": r['barcode'], "hsn_code": r['hsn_code'],
        "price": float(r['price']) if r['price'] is not None else None,
        "is_active": bool(r['is_active']), "created_at": _iso(r['created_at']),
        # Empty list = no packaging ladder = order in the one implicit unit.
        "order_units": packing.get('order_units', []),
        "price_uom": packing.get('price_uom'),
        # Null throughout for a company that prices nothing — every Hero part today —
        # so the flow that reads them can say "no rate" instead of showing a zero.
        "mrp": (pricing or {}).get('mrp'),
        "rate": (pricing or {}).get('rate'),
        "gst_rate": (pricing or {}).get('gst_rate'),
        "stock_qty": (pricing or {}).get('stock_qty'),
    }


def _skus_out(rows):
    """A list of SKUs with their order units, price and stock attached.

    Two extra queries for the whole page regardless of its size, not two per SKU.
    Pricing is grouped by the row's own company because price and stock are held per
    company; in practice a rep's page is one company and this is a single pass.
    """
    packing = order_units_for([r['product_id'] for r in rows if r.get('product_id')])

    by_company = {}
    for r in rows:
        if r.get('product_id') is not None:
            by_company.setdefault(r.get('company_id'), []).append(r['product_id'])
    pricing = {}
    for company_id, pids in by_company.items():
        pricing.update(pricing_for(pids, company_id))

    return [_sku_out(r, packing.get(r.get('product_id')),
                     pricing.get(r.get('product_id'))) for r in rows]


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


def _working_set_etag(current_user, company_params):
    """A validator for one user's working set, or None if it can't be computed.

    Built from what actually changes the set: the month whose target groups define
    it, how many products are in it, and the newest change among them. That is one
    cheap aggregate query against the same rows the real query reads, and it moves
    exactly when the answer does.

    Scoped to the caller's companies, so two reps in different companies can never
    share a tag and be served each other's catalog.

    Returning None on any problem is deliberate: a missing ETag costs a full
    response, which is merely the old behaviour, whereas a wrong one serves a stale
    catalog that a rep cannot refresh.
    """
    try:
        rows = mysql_manager.execute_query(
            """SELECT COUNT(*) AS n,
                      COALESCE(MAX(product.updated_at), '') AS newest,
                      -- The response now carries price, packing and stock as well as
                      -- the catalogue row, so all three have to be able to move the
                      -- tag. Without them a re-priced product is served from cache
                      -- indefinitely: the rep quotes last week's rate and nothing
                      -- anywhere reports a problem.
                      --
                      -- Deliberately global rather than per company. It over-
                      -- invalidates a little — one company's price load costs
                      -- everyone a full response — which is the safe direction. The
                      -- opposite error is a stale price on a live order.
                      (SELECT COALESCE(MAX(updated_on), '')
                         FROM fc_sku_price_details) AS priced,
                      (SELECT COALESCE(MAX(updated_at), '')
                         FROM product_uom) AS packed,
                      (SELECT COALESCE(MAX(updated_on), '')
                         FROM fc_entity_stock) AS stocked
                 FROM product
                WHERE product.is_active = 1""",
        )
        if not rows:
            return None
        row = rows[0]
        scope = ','.join(str(p) for p in company_params)
        raw = (f"{scope}|{row['n']}|{row['newest']}"
               f"|{row['priced']}|{row['packed']}|{row['stocked']}")
        return 'W/"%s"' % hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception:  # pragma: no cover - never fail a catalog read over a tag
        logger.warning("could not compute working-set etag", exc_info=True)
        return None


@rest_api.route('/api/v1/catalog/skus')
class V1Skus(Resource):
    @v1_require_permission(P.CATALOG_READ)
    def get(self, current_user):
        active_only = str(request.args.get('active_only', 'false')).lower() == 'true'
        working_set = str(request.args.get('working_set', 'false')).lower() == 'true'
        q = (request.args.get('q') or '').strip()
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

        # working_set: the parts a sales rep actually deals with — anything sold
        # in the last 6 months, plus everything in this month's target part
        # groups. ~3.7k rows instead of 60k, so the app can hold it locally and
        # search it instantly; the long tail is reached via `q` instead. See
        # _WORKING_SET_FROM for how the set is built and why it is shaped that way.
        #
        # It only means anything for a company that HAS a Busy feed or target part
        # groups. A company with neither — one whose sales arrive as uploaded
        # invoices — intersects it in zero rows, and narrowing its catalogue down
        # to nothing left the order picker empty with no way to add a line at all.
        # So the narrowing is applied only where it narrows something: a company
        # with no working set has its whole catalogue as its working set, which is
        # what the flag was asking for to begin with.
        #
        # Decided before `q` is applied, so a search matching nothing inside a
        # real working set still means "no results" rather than silently widening
        # to the full 60k catalogue.
        if working_set and _has_working_set(current_user):
            frm = _WORKING_SET_FROM
        else:
            frm = "product "

        # Server-side search for parts outside the working set. A leading
        # wildcard can't use a B-tree index, so this is a scan of ~59k rows —
        # acceptable at this size, but it's the thing to index (FULLTEXT) if the
        # catalog grows a lot.
        if q:
            conds.append("(name LIKE %s OR product_string LIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])

        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        # The working set is the one response worth validating: it is ~480KB, the
        # app refetches it on every launch, and it only really turns over when the
        # month's target groups change. An ETag turns that daily refetch into a
        # ~200-byte 304 — the single largest saving available on a field link.
        #
        # Only for the unfiltered working set. A search is small, and per-query
        # tags would just fill the client's storage with entries it never reuses.
        if working_set and not q:
            etag = _working_set_etag(current_user, params)
            if etag:
                if request.headers.get('If-None-Match') == etag:
                    return '', 304, {'ETag': etag}
                rows = mysql_manager.execute_query(
                    f"SELECT {SKU_COLS} FROM {frm}{where} "
                    f"ORDER BY name LIMIT %s OFFSET %s",
                    tuple(params + [limit, offset]),
                ) or []
                # _skus_out, not a bare _sku_out: this branch was dropping the
                # packaging ladder (and now price and stock) from every cached
                # response, so a pack-ordered catalogue arrived with nothing to
                # order it in — but only on the ETag path, which is why it looked
                # intermittent.
                return _skus_out(rows), 200, {'ETag': etag}

        rows = mysql_manager.execute_query(
            f"SELECT {SKU_COLS} FROM {frm}{where} "
            f"ORDER BY name LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        ) or []
        return _skus_out(rows), 200

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
            """INSERT INTO product (product_string, name, description, category_id,
                                    uom, size, weight, barcode, hsn_code, price, is_active,
                                    company_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)""",
            (sku_code, name, body.get('description'), category_id,
             body.get('uom'), body.get('size'), body.get('weight'), barcode,
             body.get('hsn_code'), body.get('price'), company_id),
            fetch=False,
        )
        return _skus_out([get_sku(sku_code)])[0], 201


@rest_api.route('/api/v1/catalog/skus/<string:sku_code>')
class V1SkuDetail(Resource):
    @v1_require_permission(P.CATALOG_READ)
    def get(self, current_user, sku_code):
        r = get_sku(sku_code, current_user)
        if not r:
            return {"detail": f"sku {sku_code} not found"}, 404
        return _skus_out([r])[0], 200

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
        updatable = ['name', 'description', 'category_id', 'uom', 'size',
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
        return _skus_out([get_sku(sku_code)])[0], 200
