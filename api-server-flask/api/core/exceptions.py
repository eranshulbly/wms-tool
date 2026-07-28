# -*- encoding: utf-8 -*-
"""Compatibility shim. Real home: api/shared/exceptions.py."""
import sys as _sys

from api.shared import exceptions as _real

_sys.modules[__name__] = _real
