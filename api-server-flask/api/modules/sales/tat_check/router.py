# -*- encoding: utf-8 -*-
"""TAT Check API. Ebco only: every call acts on the Ebco company, which the server
works out itself (there is no company parameter).

  GET  /api/tat-check/lookup?q=     any logged-in user — SKUs with qty in stock /
                                    in transit / in PO and their status
  GET  /api/tat-check/suggest?q=    any logged-in user — type-ahead: SKU code + name only
  GET  /api/tat-check/status        any logged-in user — when each feed (and the SKU master)
                                    was last uploaded
  POST /api/tat-check/upload        admin only — form fields feed, file; replaces that feed
  GET  /api/tat-check/inventory-by-category
                                    any logged-in user — stock per SKU-master category
  POST /api/tat-check/inventory-by-category/export
                                    any logged-in user — body {rows}: the rows on screen
                                    as .xlsx
"""

from functools import wraps

import io
from datetime import date

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.sales.tat_check import service as svc
from api.modules.sales.tat_check.parser import ParseError, PARSERS
from api.modules.sales.tat_check import exports as X

logger = get_logger(__name__)

BASE = '/api/tat-check'


def _guard(admin=False):
    """Maps the module's errors to JSON responses; `admin` restricts to the admin role."""
    def deco(f):
        @wraps(f)
        def wrapper(self, current_user, *args, **kwargs):
            if admin and (not current_user or current_user.role != 'admin'):
                return {'success': False, 'msg': 'Admin access required.'}, 403
            try:
                return f(self, current_user, *args, **kwargs)
            except (svc.TatCheckError, ParseError, X.ExportError) as e:
                return {'success': False, 'msg': str(e)}, 400
            except Exception:
                logger.exception('tat-check %s %s failed', request.method, request.path)
                return {'success': False, 'msg': 'Something went wrong — nothing was changed. See logs.'}, 500
        return token_required(active_required(wrapper))
    return deco


@rest_api.route(f'{BASE}/lookup')
class TatLookup(Resource):
    @_guard()
    def get(self, current_user):
        company_id = svc.ebco_company_id()
        return {'success': True, 'results': svc.lookup(company_id, request.args.get('q'))}, 200


@rest_api.route(f'{BASE}/suggest')
class TatSuggest(Resource):
    @_guard()
    def get(self, current_user):
        company_id = svc.ebco_company_id()
        return {'success': True, 'results': svc.suggest(company_id, request.args.get('q'))}, 200


@rest_api.route(f'{BASE}/status')
class TatStatus(Resource):
    @_guard()
    def get(self, current_user):
        company_id = svc.ebco_company_id()
        return {'success': True, 'feeds': svc.feed_status(company_id),
                'sources': svc.sources(company_id)}, 200


@rest_api.route(f'{BASE}/upload')
class TatUpload(Resource):
    @_guard(admin=True)
    def post(self, current_user):
        feed = request.form.get('feed')
        if feed not in PARSERS:
            return {'success': False, 'msg': 'Choose which file this is.'}, 400
        f = request.files.get('file')
        if not f:
            return {'success': False, 'msg': 'No file uploaded'}, 400
        company_id = svc.ebco_company_id()
        out = svc.ingest(feed, f.stream, f.filename, company_id, current_user.username)
        return {'success': True, 'result': out}, 200


@rest_api.route(f'{BASE}/inventory-by-category')
class TatInventoryByCategory(Resource):
    """Analytics → Inventory Report: stock per SKU-master category."""

    @_guard()
    def get(self, current_user):
        company_id = svc.ebco_company_id()
        return {'success': True, **svc.inventory_by_category(company_id)}, 200


@rest_api.route(f'{BASE}/inventory-by-category/export')
class TatInventoryByCategoryExport(Resource):
    """The By Category view as Excel. The page posts the rows it shows (filtered and
    sorted), so the file is the view on screen."""

    @_guard()
    def post(self, current_user):
        body = request.get_json(silent=True) or {}
        rows = X.clean_rows(body.get('rows'))
        company_id = svc.ebco_company_id()
        data = X.build_workbook(rows)
        # Named for the inventory it reports on, not the day it was downloaded.
        uploaded = svc.inventory_uploaded_on(company_id) or date.today()
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f'In_Stock_SKUs_by_Category_{uploaded:%d-%b-%Y}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
