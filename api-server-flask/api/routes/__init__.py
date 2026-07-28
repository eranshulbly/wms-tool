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
    """Import every module's router so @rest_api.route() decorators fire.

    HTTP handlers now live in api/modules/<module>/router*.py. Route paths are
    unchanged — this only relocates where the handlers are defined.
    """
    from ..modules.user_auth import router as _user_auth_router        # noqa: F401
    from ..modules.user_auth import router_admin as _admin_router      # noqa: F401
    from ..modules.order import router as _order_router                # noqa: F401
    from ..modules.order import router_dashboard as _dashboard_router  # noqa: F401
    from ..modules.invoice import router as _invoice_router            # noqa: F401
    from ..modules.catalog import router as _catalog_router            # noqa: F401
    from ..modules.eway_bill import router as _eway_router             # noqa: F401
    from ..modules.supply_sheet import router as _supply_sheet_router  # noqa: F401
    from ..modules.inventory import router as _inventory_router        # noqa: F401
    from ..modules.assignment import router as _assignment_router      # noqa: F401
    from ..modules.analytics import router as _analytics_router        # noqa: F401

    # Mobile API (/api/v1/*) — ported from wms-v2-backend, see docs/V2_API_PORT.md
    from ..modules.user_auth import router_v1 as _v1_auth_router        # noqa: F401
    from ..modules.catalog import router_v1 as _v1_catalog_router       # noqa: F401
    from ..modules.order import router_v1 as _v1_order_router           # noqa: F401
    from ..modules.inventory import router_v1 as _v1_inventory_router   # noqa: F401
    from ..modules.assignment import router_v1 as _v1_assignment_router # noqa: F401
    from ..modules.visit import router_v1 as _v1_visit_router           # noqa: F401
    from ..modules.analytics import router_v1 as _v1_analytics_router    # noqa: F401
