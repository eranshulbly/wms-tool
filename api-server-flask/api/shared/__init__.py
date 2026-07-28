# -*- encoding: utf-8 -*-
"""
shared/ — cross-cutting infrastructure shared by all modules.

Home of the MySQL manager, partition helpers, auth decorators, structured
logging, domain exceptions, the in-process event bus, and the schema registry.

Modules import from here; nothing here imports a module. This is the seam that
lets each domain module stay independent (mirrors wms-v2-backend's app/shared
and app/core).
"""
