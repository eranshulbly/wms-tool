# -*- encoding: utf-8 -*-
"""
modules/ — domain modules of the WMS (modular monolith).

Each module owns its tables and exposes a service.py as its only cross-module
API. Structure mirrors wms-v2-backend (app/modules/*): user_auth, catalog,
order, invoice, inventory, assignment, eway_bill, supply_sheet.
"""
