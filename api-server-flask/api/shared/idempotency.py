# -*- encoding: utf-8 -*-
"""
Make a write safe to retry.

On a field link a request can commit here while its response is lost on the way
back. The app sees a failure and retries — and without this module that retry
creates a second order. Since the mobile client queues writes and retries them
automatically, "retry is safe" is not a nicety; it is what makes the queue usable
at all.

Contract:

  * The client generates a UUID once, when the rep hits submit, and sends it as
    `Idempotency-Key` on every attempt at that intent.
  * The first attempt to arrive claims the key and does the work; its response is
    stored against the key.
  * Any later attempt with the same key replays the stored response rather than
    acting again.
  * An attempt arriving while the first is still running is told to retry shortly
    (409), rather than being allowed to race it.

Scoped per user: one caller's key can never replay another's response, so a
guessed key leaks nothing.

Usage:

    @rest_api.route('/api/v1/orders')
    class V1Orders(Resource):
        @v1_require_permission(P.ORDER_WRITE)
        def post(self, current_user):
            with idempotent(current_user['user_id'], 'orders.create') as guard:
                if guard.replayed:
                    return guard.response
                ...
                return guard.store(body, 201)

A request without the header runs normally and stores nothing, so older builds of
the app keep working exactly as before.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

from flask import request

from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger

logger = get_logger(__name__)

HEADER = 'Idempotency-Key'

# How long a completed key can be replayed. Comfortably longer than any outbox
# will keep retrying, and short enough that the table stays small.
RETENTION_DAYS = 7

# A claimed-but-unfinished key older than this is assumed dead — the worker that
# claimed it was killed mid-request (a deploy, an OOM). Longer than gunicorn's
# 120s request timeout, so a request that is merely slow is never stolen.
STALE_CLAIM_SECONDS = 300


class _Guard:
    """Handle yielded by [idempotent]."""

    def __init__(self, key, user_id, endpoint, replayed=False, response=None):
        self.key = key
        self.user_id = user_id
        self.endpoint = endpoint
        self.replayed = replayed
        self.response = response

    def store(self, body, status_code):
        """Record this response against the key and return it unchanged.

        Returning the value through means a route reads as
        `return guard.store(payload, 201)`, so it is hard to store a response and
        accidentally return a different one.

        Only success is remembered. A failed attempt releases the key instead,
        for two reasons: nothing was created, so there is no duplicate to protect
        against; and storing the failure would poison the key, so the retry the
        client is about to make would replay the error forever rather than
        succeeding once the cause cleared.
        """
        if not self.key:
            return body, status_code

        if status_code >= 400:
            self.release()
            return body, status_code

        mysql_manager.execute_query(
            """UPDATE idempotency_keys
                  SET state = 'completed', status_code = %s, response = %s,
                      completed_at = %s
                WHERE idem_key = %s""",
            (status_code, json.dumps(body), datetime.utcnow(), self.key),
            fetch=False,
        )
        return body, status_code

    def release(self):
        """Drop the claim so a retry is not blocked behind it."""
        if not self.key:
            return
        mysql_manager.execute_query(
            "DELETE FROM idempotency_keys WHERE idem_key = %s AND state = 'in_progress'",
            (self.key,), fetch=False,
        )


class InProgress(Exception):
    """Raised when the same key is already being processed."""


@contextmanager
def idempotent(user_id, endpoint):
    """Claim the request's idempotency key, or replay a stored response.

    Yields a [_Guard]. Check `guard.replayed` first: when true, `guard.response`
    is the original (body, status) and the route must do nothing else.
    """
    key = (request.headers.get(HEADER) or '').strip()
    if not key:
        # No key: behave exactly as before. Older app builds depend on this.
        yield _Guard(None, user_id, endpoint)
        return

    existing = mysql_manager.execute_query(
        """SELECT idem_key, user_id, endpoint, state, status_code, response, created_at
             FROM idempotency_keys WHERE idem_key = %s""",
        (key,),
    )

    if existing:
        row = existing[0]
        # Never let one caller replay another's response, nor reuse a key across
        # endpoints — that would return an order to a check-in request.
        if row['user_id'] != user_id or row['endpoint'] != endpoint:
            raise InProgress("idempotency key already used for a different request")

        if row['state'] == 'completed':
            body = json.loads(row['response']) if row['response'] else None
            logger.info("replaying idempotent response",
                        extra={'endpoint': endpoint, 'user_id': user_id})
            yield _Guard(key, user_id, endpoint, replayed=True,
                         response=(body, row['status_code']))
            return

        # Still in flight. If the claim is ancient the worker holding it died, so
        # take it over; otherwise tell the caller to come back.
        age = (datetime.utcnow() - row['created_at']).total_seconds()
        if age < STALE_CLAIM_SECONDS:
            raise InProgress("this request is already being processed")

        logger.warning("reclaiming a stale idempotency key",
                       extra={'endpoint': endpoint, 'age_s': int(age)})
        mysql_manager.execute_query(
            "UPDATE idempotency_keys SET created_at = %s WHERE idem_key = %s",
            (datetime.utcnow(), key), fetch=False,
        )
        yield _Guard(key, user_id, endpoint)
        return

    # Claim it. The PRIMARY KEY is what makes this safe against two requests
    # arriving at once: exactly one INSERT wins and the loser is handled as an
    # in-flight duplicate.
    try:
        mysql_manager.execute_query(
            """INSERT INTO idempotency_keys (idem_key, user_id, endpoint, state)
               VALUES (%s, %s, %s, 'in_progress')""",
            (key, user_id, endpoint), fetch=False,
        )
    except Exception:
        raise InProgress("this request is already being processed")

    try:
        yield _Guard(key, user_id, endpoint)
    except Exception:
        # The work failed, so the key must not linger as a claim that blocks the
        # retry this failure will provoke.
        mysql_manager.execute_query(
            "DELETE FROM idempotency_keys WHERE idem_key = %s AND state = 'in_progress'",
            (key,), fetch=False,
        )
        raise


def purge_expired(keep_days=RETENTION_DAYS):
    """Drop keys past their replay window. Call from the same sweep as the
    refresh-token purge."""
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    return mysql_manager.execute_query(
        "DELETE FROM idempotency_keys WHERE created_at < %s", (cutoff,), fetch=False,
    )
