# -*- encoding: utf-8 -*-
"""Compatibility shim. Real home: api/shared/partition_manager.py."""
import sys as _sys

from api.shared import partition_manager as _real

_sys.modules[__name__] = _real
