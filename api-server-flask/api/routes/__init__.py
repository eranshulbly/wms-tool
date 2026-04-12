# -*- encoding: utf-8 -*-
"""
Routes package.

Exports:
  rest_api            — the canonical Flask-RESTX Api instance (from extensions)
  token_required      — JWT auth decorator (re-exported for backward compat)
  active_required     — active-user decorator (re-exported for backward compat)
  upload_permission_required — upload permission decorator (re-exported)
  register_all_routes — call once in create_app() to wire all endpoints
"""

from ..extensions import rest_api  # noqa: F401
from ..core.auth import (          # noqa: F401
    token_required,
    active_required,
    upload_permission_required,
)


def register_all_routes():
    """Import all route modules so @rest_api.route() decorators fire."""
    from . import auth_routes       # noqa: F401
    from . import order_routes      # noqa: F401
    from . import invoice_routes    # noqa: F401
    from . import product_routes    # noqa: F401
    from . import dashboard_routes  # noqa: F401
    from . import admin_routes      # noqa: F401
    from . import eway_bill_routes  # noqa: F401
