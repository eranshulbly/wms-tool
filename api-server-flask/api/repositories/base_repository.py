# -*- encoding: utf-8 -*-
"""
BaseRepository — common dependencies for all repository classes.

Every repository subclass gets:
  self._db              — the MySQLManager singleton
  self._pf(table, ...)  — the partition_filter helper
"""

from ..db_manager import mysql_manager, partition_filter


class BaseRepository:
    """Abstract base providing shared DB access helpers."""

    def __init__(self):
        self._db = mysql_manager
        self._pf = partition_filter
