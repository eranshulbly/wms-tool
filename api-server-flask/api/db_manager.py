# -*- encoding: utf-8 -*-
"""Compatibility shim. Real home: api/shared/db_manager.py.

Kept so existing `from ..db_manager import ...` / `from .db_manager import ...`
sites keep working during the module restructure. Remove once all imports point
at api.shared.db_manager.
"""
import sys as _sys

from api.shared import db_manager as _real

_sys.modules[__name__] = _real
