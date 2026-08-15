# -*- encoding: utf-8 -*-
"""
Token issue/verify for the mobile API (/api/v1), matching wms-v2-backend's contract.

Access token claims:  sub=str(user_id), type="access", perms=[...], iat, exp (+30m)
Refresh token claims: sub, type="refresh", iat, exp (+14d), jti
Only the SHA-256 hex of the raw refresh JWT is stored (`refresh_tokens.token_hash`);
refresh rotates the token (old row revoked, new row issued) and is single-use.

Signed with this backend's existing secret — one auth system, not a fork.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta

import jwt

from api.config import BaseConfig
from api.shared.db_manager import mysql_manager
from api.shared.logging import get_logger
from api.modules.platform.user_auth import rbac

logger = get_logger(__name__)

# 30 minutes was aggressive for a field app: a rep crosses the boundary many times
# a day, and each crossing costs a rotation round trip on whatever link they have.
# 60 gives up little — refresh tokens are single-use and rotating, so a stolen
# access token is the only thing this window protects, and it was never the weak
# point — while halving refresh traffic on exactly the connections least able to
# carry it.
ACCESS_TTL_MINUTES = int(os.environ.get('ACCESS_TTL_MINUTES', '60'))
REFRESH_TTL_DAYS = int(os.environ.get('REFRESH_TTL_DAYS', '14'))

# How long after a rotation the spent token is still honoured, to absorb a
# response that never reached the phone. See rotate_refresh_token for why this
# exists; lowering it toward 0 makes reuse detection stricter at the cost of
# logging reps out when a refresh response is lost in transit.
REFRESH_GRACE_SECONDS = int(os.environ.get('REFRESH_GRACE_SECONDS', '60'))
ALGORITHM = "HS256"


def _secret():
    return BaseConfig.SECRET_KEY


def create_access_token(user_id, permissions):
    now = datetime.utcnow()
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "perms": list(permissions),
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TTL_MINUTES),
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def hash_refresh_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh_token(user_id):
    """Returns (raw_jwt, sha256_hash, expires_at)."""
    now = datetime.utcnow()
    expires_at = now + timedelta(days=REFRESH_TTL_DAYS)
    raw = jwt.encode(
        {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": expires_at,
            "jti": secrets.token_urlsafe(16),
        },
        _secret(),
        algorithm=ALGORITHM,
    )
    if isinstance(raw, bytes):  # PyJWT 1.x compat
        raw = raw.decode()
    return raw, hash_refresh_token(raw), expires_at


def decode_token(token):
    """Raises jwt.PyJWTError subclasses on invalid/expired."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])


def issue_tokens(user_id, user_agent=None):
    """Mint an access+refresh pair and persist the refresh hash."""
    perms = rbac.get_user_permission_codes(user_id)
    access = create_access_token(user_id, perms)
    if isinstance(access, bytes):
        access = access.decode()

    raw_refresh, token_hash, expires_at = create_refresh_token(user_id)
    mysql_manager.execute_query(
        """INSERT INTO refresh_tokens (user_id, token_hash, expires_at, user_agent)
           VALUES (%s, %s, %s, %s)""",
        (user_id, token_hash, expires_at, (user_agent or '')[:255] or None),
        fetch=False,
    )
    return access, raw_refresh


def _row_id_for_hash(token_hash):
    rows = mysql_manager.execute_query(
        "SELECT id FROM refresh_tokens WHERE token_hash = %s", (token_hash,)
    )
    return rows[0]['id'] if rows else None


def revoke_all_for_user(user_id, reason):
    """Revoke every live refresh token belonging to one user.

    Used on sign-out-everywhere and, more importantly, on reuse detection. Returns
    the number of tokens killed.
    """
    return mysql_manager.execute_query(
        """UPDATE refresh_tokens
              SET revoked_at = %s, revoked_reason = %s
            WHERE user_id = %s AND revoked_at IS NULL""",
        (datetime.utcnow(), reason, user_id),
        fetch=False,
    )


def revoke_refresh_token(raw_refresh, user_id=None):
    """Revoke a single refresh token — what signing out does.

    Silent about whether the token existed: a caller must not be able to use this
    to learn which tokens are real. Scoped to [user_id] when given, so one
    authenticated user cannot revoke another's session by presenting its token.
    """
    conds, params = ["token_hash = %s"], [hash_refresh_token(raw_refresh)]
    if user_id is not None:
        conds.append("user_id = %s")
        params.append(user_id)
    mysql_manager.execute_query(
        f"""UPDATE refresh_tokens
               SET revoked_at = %s, revoked_reason = 'logout'
             WHERE {' AND '.join(conds)} AND revoked_at IS NULL""",
        (datetime.utcnow(), *params),
        fetch=False,
    )


def purge_expired_refresh_tokens(keep_days=30):
    """Delete refresh tokens that expired more than [keep_days] ago.

    The table gains a row per login and per rotation — with 30-minute access
    tokens that is roughly 48 rows per rep per day, growing without bound. Expired
    rows are kept a while so a revocation can still be explained during an
    incident, then dropped.
    """
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    return mysql_manager.execute_query(
        "DELETE FROM refresh_tokens WHERE expires_at < %s",
        (cutoff,),
        fetch=False,
    )


def rotate_refresh_token(raw_refresh, user_agent=None):
    """Validate a refresh token, revoke it, and issue a fresh pair.

    Returns (access, refresh, user_id) or raises ValueError with the reason.
    """
    try:
        payload = decode_token(raw_refresh)
    except jwt.PyJWTError:
        raise ValueError("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise ValueError("Invalid token type")

    rows = mysql_manager.execute_query(
        """SELECT id, user_id, expires_at, revoked_at, revoked_reason, replaced_by
             FROM refresh_tokens WHERE token_hash = %s""",
        (hash_refresh_token(raw_refresh),),
    )
    if not rows:
        raise ValueError("Refresh token invalid or expired")

    row = rows[0]

    # Tokens are single-use, so a previously revoked one being presented again is
    # either an attacker replaying a stolen copy, or the legitimate client
    # retrying a rotation whose RESPONSE it never received. Those look identical
    # from here, and the field app makes the second case common: it is exactly
    # what a dropped connection mid-refresh produces.
    #
    # Treating every replay as theft would therefore log reps out on precisely the
    # links this system exists to tolerate. So: a token revoked by rotation, very
    # recently, is read as a lost response and honoured once more. Anything else —
    # an older token, or one revoked by logout — is treated as theft and kills the
    # whole family, so an attacker's descendant tokens die with it.
    #
    # The window is deliberately short. It is the only period in which a stolen
    # token is still worth something, and it is bounded by how long a phone takes
    # to notice a failed request and retry.
    if row['revoked_at'] is not None:
        grace = timedelta(seconds=REFRESH_GRACE_SECONDS)
        benign = (
            row.get('revoked_reason') == 'rotated'
            and datetime.utcnow() - row['revoked_at'] <= grace
        )
        if not benign:
            revoked = revoke_all_for_user(row['user_id'], 'reuse_detected')
            logger.warning(
                "refresh token reuse detected; revoked whole family",
                extra={'user_id': row['user_id'], 'tokens_revoked': revoked},
            )
            raise ValueError("Refresh token invalid or expired")

        # The successor was minted but evidently never arrived. Kill it as we
        # issue its replacement, so the family keeps exactly one live token
        # instead of leaving one nobody holds valid for another fortnight.
        if row.get('replaced_by'):
            mysql_manager.execute_query(
                """UPDATE refresh_tokens
                      SET revoked_at = %s, revoked_reason = 'superseded'
                    WHERE id = %s AND revoked_at IS NULL""",
                (datetime.utcnow(), row['replaced_by']),
                fetch=False,
            )
        logger.info(
            "refresh retried inside the grace window; treating as a lost response",
            extra={'user_id': row['user_id']},
        )

    elif row['expires_at'] < datetime.utcnow():
        raise ValueError("Refresh token invalid or expired")

    user = mysql_manager.execute_query(
        "SELECT id, status FROM users WHERE id = %s", (row['user_id'],)
    )
    if not user or user[0]['status'] != 'active':
        raise ValueError("Account not active")

    access, refresh = issue_tokens(row['user_id'], user_agent)

    # Mark the spent token rotated and point it at its successor. Written after
    # the new row exists so `replaced_by` can never dangle; a token presented in
    # between is still unrevoked and simply rotates again, which the grace window
    # already covers.
    mysql_manager.execute_query(
        """UPDATE refresh_tokens
              SET revoked_at = %s, revoked_reason = 'rotated', replaced_by = %s
            WHERE id = %s""",
        (datetime.utcnow(), _row_id_for_hash(hash_refresh_token(refresh)), row['id']),
        fetch=False,
    )
    return access, refresh, row['user_id']
