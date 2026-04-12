# -*- encoding: utf-8 -*-
"""
UserRepository — all SQL for the Users and JWTTokenBlocklist tables.

Additive in Phase 4; route handlers still call model classmethods directly
and will be migrated to this repository in Phase 5-6.
"""

from ..core.logging import get_logger
from .base_repository import BaseRepository

logger = get_logger(__name__)


class UserRepository(BaseRepository):
    """Data access layer for user authentication domain."""

    def find_by_id(self, user_id: int):
        """Return a Users instance by primary key, or None."""
        from ..models import Users
        rows = self._db.execute_query(
            "SELECT * FROM users WHERE id = %s", (user_id,)
        )
        return Users(**rows[0]) if rows else None

    def find_by_email(self, email: str):
        """Return a Users instance by email, or None."""
        from ..models import Users
        rows = self._db.execute_query(
            "SELECT * FROM users WHERE email = %s", (email,)
        )
        return Users(**rows[0]) if rows else None

    def find_by_username(self, username: str):
        """Return a Users instance by username, or None."""
        from ..models import Users
        rows = self._db.execute_query(
            "SELECT * FROM users WHERE username = %s", (username,)
        )
        return Users(**rows[0]) if rows else None

    def save(self, user) -> None:
        """Persist a Users instance (INSERT or UPDATE)."""
        user.save()

    def is_token_revoked(self, token: str) -> bool:
        """Return True if *token* appears in the blocklist."""
        pf_sql, pf_params = self._pf('jwt_token_blocklist')
        rows = self._db.execute_query(
            f"SELECT id FROM jwt_token_blocklist WHERE jwt_token = %s AND {pf_sql}",
            (token, *pf_params)
        )
        return bool(rows)

    def revoke_token(self, token: str) -> None:
        """Add *token* to the JWT blocklist."""
        from ..models import JWTTokenBlocklist
        JWTTokenBlocklist(jwt_token=token).save()
