# -*- encoding: utf-8 -*-
"""Handheld telemetry sink.

  POST /api/v1/diag   — the app posts a batch of events

**Unauthenticated on purpose.** The events worth having most are the ones from
before a session exists: which build launched, whether a login was refused, what
the home screen decided to draw. Requiring a token would silence exactly those.
The token is read when present, so signed-in events still say who.

That makes it an open write endpoint, so it is capped hard rather than trusted:
a bounded number of events per request, bounded field lengths, and a row cap
enforced on write. It can also be switched off without a deploy — set
DIAG_INGEST=off in the environment and it stops accepting.

Turn it off once the handhelds are behaving.
"""

import json
import os
import random

from flask import request
from flask_restx import Resource

from api.core.logging import get_logger
from api.db_manager import mysql_manager
from api.extensions import rest_api
from api.modules.platform.diagnostics.schema import MAX_ROWS

logger = get_logger(__name__)

MAX_EVENTS_PER_BATCH = 50
MAX_DETAIL_CHARS = 2000


def _enabled():
    return (os.environ.get('DIAG_INGEST', 'on').strip().lower()
            not in ('off', '0', 'false', 'no'))


def _clip(value, limit):
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:limit]


def _current_user_or_none():
    """Identify the caller if they sent a usable token; never fail if they did not."""
    try:
        from api.shared.auth_v1 import _resolve_current_user
        user, err = _resolve_current_user()
        return None if err else user
    except Exception:
        return None


@rest_api.route('/api/v1/diag')
class V1Diagnostics(Resource):
    """Accept a batch of client events."""

    def post(self):
        if not _enabled():
            return {'accepted': 0, 'detail': 'diagnostics ingest is off'}, 202

        body = request.get_json(silent=True) or {}
        events = body.get('events') or []
        if not isinstance(events, list):
            return {'detail': 'events must be a list'}, 422

        # Truncate rather than reject: a handset that over-reports should lose the
        # tail of one batch, not have its whole report thrown away.
        events = events[:MAX_EVENTS_PER_BATCH]
        if not events:
            return {'accepted': 0}, 200

        user = _current_user_or_none()
        session_id = _clip(body.get('session') or 'unknown', 64)
        build = _clip(body.get('build'), 64)
        device = _clip(body.get('device'), 64)
        platform = _clip(body.get('platform'), 64)

        rows = []
        for e in events:
            if not isinstance(e, dict):
                continue
            detail = e.get('detail')
            if detail is not None and not isinstance(detail, str):
                try:
                    detail = json.dumps(detail, ensure_ascii=False)
                except Exception:
                    detail = str(detail)
            rows.append((
                session_id, build, device, platform,
                (user or {}).get('user_id'),
                _clip((user or {}).get('email'), 128),
                _clip(e.get('level') or 'info', 16),
                _clip(e.get('event') or 'unknown', 80),
                _clip(detail, MAX_DETAIL_CHARS),
                _clip(e.get('at'), 40),
            ))

        if not rows:
            return {'accepted': 0}, 200

        try:
            with mysql_manager.get_cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO app_diag_log
                         (session_id, build, device, platform, user_id, user_email,
                          level, event, detail, client_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    rows,
                )
                # Trim occasionally rather than every request: the cap only has to
                # hold on average, and a DELETE on every ping would cost more than
                # the ingest it is protecting.
                if random.random() < 0.02:
                    cursor.execute(
                        "DELETE FROM app_diag_log WHERE id <= "
                        "(SELECT * FROM (SELECT MAX(id) - %s FROM app_diag_log) t)",
                        (MAX_ROWS,),
                    )
        except Exception as e:
            # Telemetry must never be the thing that breaks the app. Swallow, log
            # server-side, and tell the client it is fine.
            logger.warning("Could not store diagnostics batch",
                           extra={'error': str(e), 'count': len(rows)})
            return {'accepted': 0}, 200

        return {'accepted': len(rows)}, 200
