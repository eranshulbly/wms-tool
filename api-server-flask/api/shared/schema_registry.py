# -*- encoding: utf-8 -*-
"""
Schema registry.

Each module owns its tables. Instead of one giant create_all_tables() living in
db_manager, a module registers its CREATE TABLE statements here (at import time),
and initialize_database() asks the registry to create everything in dependency
order. This keeps table ownership inside the module that uses the table — the
first boundary rule of the modular monolith.

Migration note: the legacy inline DDL in db_manager.create_all_tables() is being
moved into modules incrementally. Anything registered here is created *in
addition* to the legacy DDL, so new modules (inventory, assignment) can own their
schema from day one while the older tables are migrated over.

Usage (in a module's models.py / schema.py, at import time):
    from api.shared.schema_registry import register_table

    register_table(
        name="stock",
        ddl='''CREATE TABLE IF NOT EXISTS stock (...) ...''',
        order=50,          # lower runs first; use ~50+ for new modules
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _Table:
    order: int
    name: str = field(compare=False)
    ddl: str = field(compare=False)


_registry: List[_Table] = []
_seen: set[str] = set()


def register_table(name: str, ddl: str, order: int = 100) -> None:
    """Register one table's CREATE TABLE IF NOT EXISTS. Idempotent per name."""
    if name in _seen:
        return
    _seen.add(name)
    _registry.append(_Table(order=order, name=name, ddl=ddl))


def registered_tables() -> List[_Table]:
    """All registered tables, sorted by declared order."""
    return sorted(_registry)


def create_registered(cursor) -> None:
    """Execute every registered CREATE TABLE using an open DB cursor."""
    for table in registered_tables():
        logger.info("schema_registry: creating table %s", table.name)
        cursor.execute(table.ddl)
