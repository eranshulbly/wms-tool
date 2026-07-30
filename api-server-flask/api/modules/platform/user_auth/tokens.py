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
import secrets
from datetime import datetime, timedelta

import jwt

from api.config import BaseConfig
from api.shared.db_manager import mysql_manager
from api.modules.platform.user_auth import rbac

ACCESS_TTL_MINUTES = 30
REFRESH_TTL_DAYS = 14
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
        "SELECT id, user_id, expires_at, revoked_at FROM refresh_tokens WHERE token_hash = %s",
        (hash_refresh_token(raw_refresh),),
    )
    if not rows:
        raise ValueError("Refresh token invalid or expired")

    row = rows[0]
    if row['revoked_at'] is not None or row['expires_at'] < datetime.utcnow():
        raise ValueError("Refresh token invalid or expired")

    user = mysql_manager.execute_query(
        "SELECT id, status FROM users WHERE id = %s", (row['user_id'],)
    )
    if not user or user[0]['status'] != 'active':
        raise ValueError("Account not active")

    mysql_manager.execute_query(
        "UPDATE refresh_tokens SET revoked_at = %s WHERE id = %s",
        (datetime.utcnow(), row['id']),
        fetch=False,
    )
    access, refresh = issue_tokens(row['user_id'], user_agent)
    return access, refresh, row['user_id']
