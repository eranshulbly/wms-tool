# -*- encoding: utf-8 -*-
"""Compatibility shim. Real home: api/shared/auth.py."""
import sys as _sys

from api.shared import auth as _real

_sys.modules[__name__] = _real
