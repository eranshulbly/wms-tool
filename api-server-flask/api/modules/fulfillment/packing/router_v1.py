# -*- encoding: utf-8 -*-
"""
Mobile API — packing module (/api/v1/packing/*).

The 14 endpoints the Zebra TC21 packing app calls. Contracts are
`PACKING_SCREEN_API_CONTRACTS.md`; this file is the translation layer and nothing
more — every rule lives in `service.py`, so a rule cannot be enforced on one route
and forgotten on another.

  GET  /packing/config                      Screen 3   thresholds + barcode layout
  GET  /packing/picklists                   Screens 4,5 the pool
  GET  /packing/picklists/{order_id}        Screen 5   pre-flight read
  GET  /packing/short-reasons               Screen 12  the shared shortfall list
  POST /packing/jobs                        Screen 6   create or resume the job
  GET  /packing/jobs/{request_id}           Screen 16  crash-recovery read
  POST /packing/jobs/{request_id}/boxes     Screen 6   open a box with its tare
  POST /packing/boxes/{box_id}/bind         Screen 7   scan the warehouse label
  POST /packing/boxes/{box_id}/scans        Screen 8   the batched scan loop
  POST /packing/jobs/{request_id}/cartons   Screen 8b  an intact supplier carton
  POST /packing/boxes/{box_id}/close        Screen 9   weight-verify and seal
  POST /packing/boxes/{box_id}/abandon      Screen 14  take a box out of the job
  POST /packing/jobs/{request_id}/save      Screen 11  pause
  POST /packing/jobs/{request_id}/submit    Screen 12  finalise + order write-back

Every endpoint requires `inventory:pack`. Every write accepts `Idempotency-Key`:
the app queues writes on disk and retries them automatically, so "retry is safe"
is what makes the queue usable at all rather than a nicety.

Errors are `{"detail": "<sentence>"}` plus a machine-readable `code` on business
rejections — the app switches on `code` and displays `detail`.
"""

from flask import request
from flask_restx import Resource

from api.extensions import rest_api
from api.shared.auth_v1 import v1_require_permission
from api.shared.idempotency import InProgress, idempotent
from api.modules.platform.user_auth.rbac import P
from api.modules.fulfillment.packing import service as svc


def _paging(default_limit: int = 50):
    """(limit, offset, error). Bounded because the pool is a handheld list, and an
    unbounded limit is a whole-table read one query string away."""
    try:
        limit = int(request.args.get('limit', default_limit))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return None, None, ({"detail": "limit/offset must be integers"}, 422)
    return max(1, min(limit, 200)), max(offset, 0), None


def _warehouse_id(current_user=None):
    """The bench being packed at. A packer works one, so the pool is always scoped.

    Falls back to the caller's own grant when the parameter is absent and there is
    exactly one, because in that case the server already knows the answer and there
    is nothing to disambiguate. Demanding it anyway made a caller that had simply
    forgotten it fail with `warehouse_id is required` — technically true, unhelpful,
    and avoidable given the token names the warehouse.

    Still required when the caller holds several warehouses or holds them all:
    there the server would be guessing, and guessing which bench a packer is stood
    at is how one warehouse's picklists end up on another's screen.
    """
    warehouse_id = request.args.get('warehouse_id', type=int)
    if warehouse_id is not None:
        return warehouse_id, None

    ids = (current_user or {}).get('warehouse_ids')
    if not (current_user or {}).get('has_all_warehouses') and ids and len(ids) == 1:
        return int(ids[0]), None

    return None, ({"detail": "warehouse_id is required", "code": "warehouse_required"}, 422)


def _handle(fn, *args, **kwargs):
    """Run a service call and translate its domain errors to HTTP.

    One mapping for all fourteen endpoints: a per-route try/except would drift, and
    the day one route forgets `ConflictError` a fraud rejection becomes a 500 that
    reads to the packer as "the server is broken, try again".
    """
    try:
        return fn(*args, **kwargs), 200
    except svc.ValidationError as e:
        return e.body(), 422
    except svc.NotFoundError as e:
        return e.body(), 404
    except svc.ConflictError as e:
        return e.body(), 409


def _write(current_user, endpoint: str, fn, *args, success: int = 200, **kwargs):
    """`_handle` wrapped in the idempotency guard, for the ten write endpoints.

    Only a success is stored against the key. A rejection releases it, so the
    retry the packer is about to make is judged against the world as it is then —
    a `weight_mismatch` must not be replayed forever after the packer removes the
    offending item.
    """
    try:
        with idempotent(current_user['user_id'], endpoint) as guard:
            if guard.replayed:
                return guard.response
            body, status = _handle(fn, *args, **kwargs)
            return guard.store(body, success if status == 200 else status)
    except InProgress as e:
        # The same key is mid-flight. Not an error the packer should see — the
        # outbox simply tries again shortly.
        return {"detail": str(e)}, 409


def _body() -> dict:
    return request.get_json(silent=True) or {}


# ── SCREEN 3 — bootstrap ─────────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/config')
class V1PackingConfig(Resource):
    """Operational thresholds and this company's barcode layout.

    Reads no table. Served rather than compiled into the APK so tuning tolerance —
    or onboarding a company whose codes decode differently — is a config push.
    """

    @v1_require_permission(P.INVENTORY_PACK)
    def get(self, current_user):
        warehouse_id = request.args.get('warehouse_id', type=int) or 1
        return svc.config_payload(warehouse_id), 200


# ── SCREENS 4 & 5 — the pool ─────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/picklists')
class V1PackingPicklists(Resource):
    """Orders sitting at `Picking`. Search is server-side: the pool is shared and
    self-serve, and a stale local copy filtered on the device sends two packers at
    the same picklist."""

    @v1_require_permission(P.INVENTORY_PACK)
    def get(self, current_user):
        warehouse_id, err = _warehouse_id(current_user)
        if err:
            return err
        limit, offset, err = _paging()
        if err:
            return err
        return _handle(svc.list_picklists, current_user, warehouse_id,
                       request.args.get('q'), limit, offset)


@rest_api.route('/api/v1/packing/picklists/<int:potential_order_id>')
class V1PackingPicklistDetail(Resource):
    """The pre-flight read behind a tapped card, before any job exists."""

    @v1_require_permission(P.INVENTORY_PACK)
    def get(self, current_user, potential_order_id):
        return _handle(svc.get_picklist_detail, current_user, potential_order_id)


@rest_api.route('/api/v1/packing/short-reasons')
class V1PackingShortReasons(Resource):
    """`understack_reason` — the one shared shortfall list, shared with stacking."""

    @v1_require_permission(P.INVENTORY_PACK)
    def get(self, current_user):
        return _handle(svc.list_short_reasons)


# ── SCREEN 6 — the job and its first box ─────────────────────────────────────

@rest_api.route('/api/v1/packing/jobs')
class V1PackingJobs(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user):
        """Create or resume the packing job for a picklist.

        Serialised on the order row inside the service: `entity_movement_request`
        has no unique key to race on, so without that lock two packers tapping the
        same card create two jobs and both pack the same picklist.
        """
        body = _body()
        order_id = body.get('potential_order_id')
        if not isinstance(order_id, int):
            return {"detail": "potential_order_id is required"}, 422
        return _write(current_user, 'packing.jobs.create', svc.create_or_resume_job,
                      current_user, order_id, body.get('station'))


@rest_api.route('/api/v1/packing/jobs/<int:request_id>')
class V1PackingJobDetail(Resource):
    """The reconciliation read after a crash, a battery swap or a long offline
    stretch. The server's box state wins over anything the app still holds."""

    @v1_require_permission(P.INVENTORY_PACK)
    def get(self, current_user, request_id):
        return _handle(svc.get_job_state, current_user, request_id)


@rest_api.route('/api/v1/packing/jobs/<int:request_id>/boxes')
class V1PackingBoxes(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, request_id):
        """Open a box from the empty carton's settled weight. Setup step 1."""
        body = _body()
        tare = body.get('tare_kg')
        if not isinstance(tare, (int, float)):
            return {"detail": "tare_kg is required"}, 422
        return _write(current_user, 'packing.boxes.open', svc.open_box,
                      current_user, request_id, float(tare), body.get('captured_at'),
                      success=201)


# ── SCREEN 7 — bind the label ────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/boxes/<int:box_id>/bind')
class V1PackingBoxBind(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, box_id):
        """Claim a pre-printed warehouse label for this box. Single-use forever.

        The app never generates a code — the demo's `QR-PL-4821-01-A7F2` is mock
        behaviour and must not ship.
        """
        body = _body()
        return _write(current_user, 'packing.boxes.bind', svc.bind_label,
                      current_user, box_id, body.get('label_code'), body.get('scanned_at'))


# ── SCREEN 8 — the scan loop ─────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/boxes/<int:box_id>/scans')
class V1PackingBoxScans(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, box_id):
        """Apply a flushed batch of trigger pulls.

        Batched because one call per ack costs 7 auth queries before the endpoint
        runs — 700 for a 100-unit picklist, ~70/sec across ten packers, against a
        connection budget of 60. Batching is what keeps the module inside it.

        **This endpoint is not the weight check.** The live red/green
        reconciliation runs on the device against the scale stream; the
        authoritative, tamper-proof check is at close.
        """
        body = _body()
        scans = body.get('scans')
        if not isinstance(scans, list):
            return {"detail": "scans must be a list"}, 422
        return _write(current_user, 'packing.boxes.scans', svc.apply_scans,
                      current_user, box_id, scans, body.get('weight_events') or [])


# ── SCREEN 8b — an intact supplier carton ────────────────────────────────────

@rest_api.route('/api/v1/packing/jobs/<int:request_id>/cartons')
class V1PackingCartons(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, request_id):
        """One scan creates, fills, weighs and seals a box from an unopened carton.

        Rejects a retail-pack code with 422 `not_an_intact_carton` — the mirror of
        `/scans` rejecting a carton code. A built box may be open at the same time
        and is untouched.
        """
        body = _body()
        raw = body.get('raw')
        measured = body.get('measured_kg')
        if not raw or not isinstance(measured, (int, float)):
            return {"detail": "raw and measured_kg are required"}, 422
        return _write(current_user, 'packing.cartons.intake', svc.intake_carton,
                      current_user, request_id, raw, float(measured),
                      body.get('scanned_at'), success=201)


# ── SCREEN 9 — close ─────────────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/boxes/<int:box_id>/close')
class V1PackingBoxClose(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, box_id):
        """Weight-verify and seal. **The authoritative write.**

        A box whose `/scans` batches never uploaded still seals correctly, because
        the item list is carried here in full. The expected weight is recomputed
        server-side from snapshotted unit weights; any client-supplied expected
        value is ignored, and a mismatch is a 409 that writes nothing but the
        rejected attempt.
        """
        body = _body()
        sealed = body.get('sealed_kg')
        if not isinstance(sealed, (int, float)):
            return {"detail": "sealed_kg is required"}, 422
        items = body.get('items')
        if not isinstance(items, list):
            return {"detail": "items must be a list"}, 422
        return _write(current_user, 'packing.boxes.close', svc.close_box,
                      current_user, box_id, float(sealed), body.get('sealed_at'),
                      items, body.get('scans') or [], body.get('weight_events') or [])


# ── SCREEN 14 — abandon ──────────────────────────────────────────────────────

@rest_api.route('/api/v1/packing/boxes/<int:box_id>/abandon')
class V1PackingBoxAbandon(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, box_id):
        """Take a box out of the job. Nothing is deleted and the label is spent.

        The app must call this before discarding local state, or the box sits
        `open` forever and blocks the job from saving or submitting.
        """
        body = _body()
        return _write(current_user, 'packing.boxes.abandon', svc.abandon_box,
                      current_user, box_id, body.get('reason') or 'packer_exit')


# ── SCREENS 11 & 12 — save and submit ────────────────────────────────────────

@rest_api.route('/api/v1/packing/jobs/<int:request_id>/save')
class V1PackingJobSave(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, request_id):
        """Pause the job. Nothing is written to the order — a half-written packed
        quantity would be read by invoicing as final."""
        return _write(current_user, 'packing.jobs.save', svc.save_job,
                      current_user, request_id)


@rest_api.route('/api/v1/packing/jobs/<int:request_id>/submit')
class V1PackingJobSubmit(Resource):
    @v1_require_permission(P.INVENTORY_PACK)
    def post(self, current_user, request_id):
        """Finalise the job and write back to the order.

        **Call it with an empty body first.** If the order is short it refuses with
        the server-computed shortfall in the body — that rejection IS the
        confirmation dialog, so the numbers the packer acknowledges are produced by
        the same code that will write them. `acknowledge_short: true` then commits.
        """
        body = _body()
        return _write(current_user, 'packing.jobs.submit', svc.submit_job,
                      current_user, request_id,
                      bool(body.get('acknowledge_short')), body.get('reason_id'),
                      body.get('note'), body.get('reasons') or {})
