# -*- encoding: utf-8 -*-
"""Compatibility shim. Real home: api/shared/logging.py."""
import sys as _sys

from api.shared import logging as _real

_sys.modules[__name__] = _real
