# -*- encoding: utf-8 -*-
"""PO Builder API — admin only. Ebco only: every call acts on the Ebco company, which
the server works out itself (there is no company parameter).

Masters:
  GET  /api/po-builder/settings                  PUT same
  GET  /api/po-builder/sku-masters               versions, newest first
  POST /api/po-builder/sku-masters               file, name, commit=0|1 (0 = preview only)
  GET  /api/po-builder/schemes
  POST /api/po-builder/schemes                   file, name, commit   (the latest upload is in force)
  GET  /api/po-builder/schemes/<id>              groups + slabs     PUT name
  GET  /api/po-builder/schemes/<id>/mapping      ?view=all|unmapped&q=   (read-only)

Purchase orders:
  POST /api/po-builder/current                   the PO being built (latest; a new draft if none)
  POST /api/po-builder/pos                       start a new PO {po_date?, title?, remarks?}
  GET  /api/po-builder/pos/<id>                  full page payload     PUT header    DELETE (draft)
  GET  /api/po-builder/pos/<id>/search?q=&group=&limit=   (no q = browse; group = id | none)
  GET  /api/po-builder/pos/<id>/groups            scheme groups (+ category) for the filter
  POST /api/po-builder/pos/<id>/lines            {sku_code, qty}
  PUT  /api/po-builder/pos/<id>/lines/<line>     {qty}                 DELETE
  POST /api/po-builder/pos/<id>/imports          file | text, source_tag, sheet
  GET  /api/po-builder/pos/<id>/imports/<imp>
  PUT  /api/po-builder/pos/<id>/imports/<imp>/rows/<row>   {sku_code} | {dismiss} | {qty}   (review)
  POST /api/po-builder/pos/<id>/imports/<imp>/rows/<row>/add  {sku_code, qty?}  straight into the PO
  POST /api/po-builder/pos/<id>/imports/<imp>/apply
  POST /api/po-builder/pos/<id>/imports/<imp>/discard
  POST /api/po-builder/pos/<id>/finalise         POST .../reopen
  GET  /api/po-builder/pos/<id>/export          the Order Book workbook
"""

import io
from functools import wraps

from flask import request, send_file
from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required
from api.core.logging import get_logger
from api.modules.procurement.po_builder import exports, service as svc
from api.modules.procurement.po_builder.parsers import ParseError

logger = get_logger(__name__)

BASE = '/api/po-builder'


def _guard(f):
    """Admin only; maps the module's errors to JSON responses."""
    @wraps(f)
    def wrapper(self, current_user, *args, **kwargs):
        if not current_user or current_user.role != 'admin':
            return {'success': False, 'msg': 'Admin access required.'}, 403
        try:
            return f(self, current_user, *args, **kwargs)
        except svc.NotFound as e:
            return {'success': False, 'msg': str(e)}, 404
        except (svc.PoBuilderError, ParseError, exports.ExportError) as e:
            return {'success': False, 'msg': str(e)}, 400
        except Exception:
            logger.exception('po-builder %s %s failed', request.method, request.path)
            return {'success': False, 'msg': 'Something went wrong — nothing was changed. See logs.'}, 500
    return token_required(active_required(wrapper))


def _ebco():
    """The Ebco company — the only company PO Builder works for (see service.ebco_company_id)."""
    return svc.ebco_company_id()


def _scope():
    return [_ebco()]


def _body():
    return request.get_json(silent=True) or {}


def _file():
    f = request.files.get('file')
    if not f:
        raise svc.PoBuilderError('No file uploaded.')
    return f.read(), f.filename


# ---------------------------------------------------------------------------- masters

@rest_api.route(f'{BASE}/settings')
class PobSettings(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'settings': svc.get_settings(_ebco())}

    @_guard
    def put(self, current_user):
        cid = _ebco()
        return {'success': True, 'settings': svc.update_settings(cid, _body(), current_user.username)}


@rest_api.route(f'{BASE}/sku-masters')
class PobSkuMasters(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'masters': svc.list_masters(_ebco())}

    @_guard
    def post(self, current_user):
        cid = _ebco()
        data, name = _file()
        out = svc.sku_master_upload(cid, data, name, request.form.get('name'), current_user.username,
                                    commit=request.form.get('commit') == '1')
        return {'success': True, **out}


@rest_api.route(f'{BASE}/schemes')
class PobSchemes(Resource):
    @_guard
    def get(self, current_user):
        return {'success': True, 'schemes': svc.list_schemes(_ebco())}

    @_guard
    def post(self, current_user):
        cid = _ebco()
        data, name = _file()
        out = svc.scheme_upload(cid, data, name, request.form, current_user.username,
                                commit=request.form.get('commit') == '1')
        return {'success': True, **out}


@rest_api.route(f'{BASE}/schemes/<int:scheme_id>')
class PobScheme(Resource):
    @_guard
    def get(self, current_user, scheme_id):
        return {'success': True, **svc.scheme_detail(_ebco(), scheme_id)}

    @_guard
    def put(self, current_user, scheme_id):
        cid = _ebco()
        return {'success': True, 'scheme': svc.update_scheme(cid, scheme_id, _body())}


@rest_api.route(f'{BASE}/schemes/<int:scheme_id>/mapping')
class PobMapping(Resource):
    @_guard
    def get(self, current_user, scheme_id):
        cid = _ebco()
        return {'success': True, **svc.mapping(cid, scheme_id, request.args.get('view', 'all'),
                                               request.args.get('q', ''))}



# ---------------------------------------------------------------------------- POs

@rest_api.route(f'{BASE}/pos')
class PobPos(Resource):
    @_guard
    def post(self, current_user):
        cid = _ebco()
        return {'success': True, 'id': svc.create_po(cid, _body(), current_user.username)}


@rest_api.route(f'{BASE}/current')
class PobCurrent(Resource):
    @_guard
    def post(self, current_user):
        return {'success': True, 'id': svc.current_po(_ebco(), current_user.username)}


@rest_api.route(f'{BASE}/pos/<int:po_id>')
class PobPo(Resource):
    @_guard
    def get(self, current_user, po_id):
        return {'success': True, **svc.po_view(po_id, _scope())}

    @_guard
    def put(self, current_user, po_id):
        svc.update_po(po_id, _scope(), _body())
        return {'success': True, **svc.po_view(po_id, _scope())}

    @_guard
    def delete(self, current_user, po_id):
        svc.delete_po(po_id, _scope())
        return {'success': True}


@rest_api.route(f'{BASE}/pos/<int:po_id>/search')
class PobSearch(Resource):
    @_guard
    def get(self, current_user, po_id):
        return {'success': True, **svc.search(po_id, _scope(), request.args.get('q', ''),
                                              group=request.args.get('group') or None,
                                              limit=request.args.get('limit', 25, type=int))}


@rest_api.route(f'{BASE}/pos/<int:po_id>/groups')
class PobGroupOptions(Resource):
    @_guard
    def get(self, current_user, po_id):
        return {'success': True, **svc.group_options(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/lines')
class PobLines(Resource):
    @_guard
    def post(self, current_user, po_id):
        svc.add_line(po_id, _scope(), _body(), current_user.username)
        return {'success': True, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/lines/<int:line_id>')
class PobLine(Resource):
    @_guard
    def put(self, current_user, po_id, line_id):
        svc.set_line_qty(po_id, _scope(), line_id, _body(), current_user.username)
        return {'success': True, **svc.po_view(po_id, _scope())}

    @_guard
    def delete(self, current_user, po_id, line_id):
        svc.delete_line(po_id, _scope(), line_id)
        return {'success': True, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports')
class PobImports(Resource):
    @_guard
    def post(self, current_user, po_id):
        tag = request.form.get('source_tag')
        sheet = request.form.get('sheet') or None
        if request.files.get('file'):
            data, name = _file()
            out = svc.create_import(po_id, _scope(), current_user.username, tag,
                                    data=data, filename=name, sheet=sheet)
        else:
            text = request.form.get('text') or ''
            if not text.strip():
                raise svc.PoBuilderError('Paste some rows or choose a file.')
            out = svc.create_import(po_id, _scope(), current_user.username, tag, text=text)
        return {'success': True, **out}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports/<int:import_id>')
class PobImport(Resource):
    @_guard
    def get(self, current_user, po_id, import_id):
        return {'success': True, **svc.import_view(po_id, _scope(), import_id)}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports/<int:import_id>/rows/<int:row_id>')
class PobImportRow(Resource):
    @_guard
    def put(self, current_user, po_id, import_id, row_id):
        return {'success': True, **svc.resolve_row(po_id, _scope(), import_id, row_id,
                                                   _body(), current_user.username)}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports/<int:import_id>/rows/<int:row_id>/add')
class PobImportRowAdd(Resource):
    @_guard
    def post(self, current_user, po_id, import_id, row_id):
        svc.add_row(po_id, _scope(), import_id, row_id, _body(), current_user.username)
        return {'success': True, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports/<int:import_id>/apply')
class PobImportApply(Resource):
    @_guard
    def post(self, current_user, po_id, import_id):
        out = svc.apply_import(po_id, _scope(), import_id, current_user.username)
        return {'success': True, 'result': out, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/imports/<int:import_id>/discard')
class PobImportDiscard(Resource):
    @_guard
    def post(self, current_user, po_id, import_id):
        svc.discard_import(po_id, _scope(), import_id)
        return {'success': True}


@rest_api.route(f'{BASE}/pos/<int:po_id>/finalise')
class PobFinalise(Resource):
    @_guard
    def post(self, current_user, po_id):
        svc.finalise(po_id, _scope(), current_user.username)
        return {'success': True, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/reopen')
class PobReopen(Resource):
    @_guard
    def post(self, current_user, po_id):
        svc.reopen(po_id, _scope())
        return {'success': True, **svc.po_view(po_id, _scope())}


@rest_api.route(f'{BASE}/pos/<int:po_id>/export')
class PobExport(Resource):
    @_guard
    def get(self, current_user, po_id):
        view = svc.po_view(po_id, _scope())
        po = view['po']
        stem = po['po_no'] + ('' if po['status'] == 'finalised' else '_DRAFT')
        data = exports.order_book_xlsx(view)
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f'{stem}_Order_Book.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
