# -*- encoding: utf-8 -*-
"""
Mobile API — diagnostics sink (/api/v1/debug/*).

A place for the handheld to post what it observed, so bring-up against hardware
nobody can reach from a workstation stops being guesswork. The packing app's
Bluetooth scale transport streams its whole event log here: connect attempts,
raw bytes in hex, decoded lines, and the frames the parser refused.

**Development only.** Every route 404s unless APP_ENV is a development
environment, so this cannot become a live, unauthenticated write endpoint by
being forgotten — the check is on the request, not just on registration, because
a config reload is a likelier accident than a redeploy.

Deliberately unauthenticated in dev: the scale has to be debuggable when sign-in
is exactly what is broken, and requiring a token here would put the diagnostics
behind the failure they exist to explain.

Storage is a JSONL file in the container, not a table. It is throwaway by
construction — a restart clears it — and adding a migration for a debugging aid
would outlive the debugging.
"""

import json
import os
import threading
from datetime import datetime, timezone

from flask import request
from flask_restx import Resource

from api.extensions import rest_api

LOG_PATH = os.getenv('SCALE_DIAG_LOG', '/tmp/scale_diag.jsonl')

# Bound the file so a handset left streaming overnight cannot fill the container
# disk and take the API down with it.
MAX_BYTES = 8 * 1024 * 1024

_lock = threading.Lock()


def _dev_only():
    """None when diagnostics are allowed, else a 404 response tuple."""
    env = (os.getenv('APP_ENV') or 'production').lower()
    if env.startswith('dev') or env in ('local', 'test', 'testing'):
        return None
    return {"detail": "Not found"}, 404


def _truncate_if_large():
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_BYTES:
            # Keep the tail: the interesting part of a bring-up log is always
            # what happened most recently, not how it started an hour ago.
            with open(LOG_PATH, 'r', encoding='utf-8', errors='replace') as fh:
                lines = fh.readlines()[-2000:]
            with open(LOG_PATH, 'w', encoding='utf-8') as fh:
                fh.writelines(lines)
    except OSError:
        pass


@rest_api.route('/api/v1/debug/scale-log')
class V1ScaleLog(Resource):

    def post(self):
        """Append a batch of scale-transport events.

        Accepts whatever the app sends and never rejects on shape: a diagnostics
        endpoint that 400s on an unexpected field is useless precisely when the
        app is misbehaving, which is the only time it is called.
        """
        blocked = _dev_only()
        if blocked:
            return blocked

        body = request.get_json(silent=True) or {}
        events = body.get('events') or []
        record = {
            'received_at': datetime.now(timezone.utc).isoformat(),
            'remote': request.remote_addr,
            'session': body.get('session'),
            'device': body.get('device'),
            'probe': body.get('probe'),
            'events': events,
        }

        with _lock:
            _truncate_if_large()
            try:
                with open(LOG_PATH, 'a', encoding='utf-8') as fh:
                    fh.write(json.dumps(record, default=str) + '\n')
            except OSError as exc:
                return {"detail": f"could not write log: {exc}"}, 500

        return {"ok": True, "stored": len(events)}, 200

    def get(self):
        """Read the log back as flat text, newest last.

        `?limit=` caps the number of EVENTS returned, not batches — batches vary
        wildly in size and a batch limit makes the output length unpredictable.
        """
        blocked = _dev_only()
        if blocked:
            return blocked

        try:
            limit = min(int(request.args.get('limit', 400)), 5000)
        except (TypeError, ValueError):
            limit = 400

        if not os.path.exists(LOG_PATH):
            return {"lines": [], "detail": "no diagnostics received yet"}, 200

        out = []
        with open(LOG_PATH, 'r', encoding='utf-8', errors='replace') as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                for ev in rec.get('events') or []:
                    out.append(
                        f"{ev.get('at', '')} [{ev.get('kind', '')}] {ev.get('text', '')}")

        return {"count": len(out), "lines": out[-limit:]}, 200

    def delete(self):
        """Start a clean run."""
        blocked = _dev_only()
        if blocked:
            return blocked
        with _lock:
            try:
                if os.path.exists(LOG_PATH):
                    os.remove(LOG_PATH)
            except OSError as exc:
                return {"detail": f"could not clear: {exc}"}, 500
        return {"ok": True}, 200


@rest_api.route('/api/v1/debug/scale-log/probe')
class V1ScaleLogProbe(Resource):

    def get(self):
        """The most recent platform snapshot the app sent.

        Separated from the event feed because it answers the first question —
        is the device even bonded, and is it Classic or LE — without reading
        through a thousand raw-byte lines to find it.
        """
        blocked = _dev_only()
        if blocked:
            return blocked

        if not os.path.exists(LOG_PATH):
            return {"detail": "no diagnostics received yet"}, 200

        latest = None
        with open(LOG_PATH, 'r', encoding='utf-8', errors='replace') as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if rec.get('probe'):
                    latest = {
                        'received_at': rec.get('received_at'),
                        'remote': rec.get('remote'),
                        'device': rec.get('device'),
                        'probe': rec.get('probe'),
                    }
        return latest or {"detail": "no probe in log yet"}, 200
