# -*- encoding: utf-8 -*-
"""
packing — the weight-verified carton packing module (Zebra TC21 handheld).

**This module owns no tables.** It rides the inventory-owned movement engine:
a packing job is an `entity_movement_request` with `movement_type='packing'`,
and every box / SKU-in-box / shortfall is an `entity_movement_details` row.
There is deliberately no `schema.py` here — see PACKING_DESIGN.md §1 D1–D4.

Layout
    constants.py   vocabulary + the config constants served by /packing/config
    barcode.py     the delimited-code parser (split-and-trim, never byte offsets)
    repository.py  every raw SQL statement against EMR / EMD
    service.py     the business rules, including the anti-fraud tolerance check
    router_v1.py   /api/v1/packing/* — the 14 handheld endpoints
    events.py      carton.sealed / packing.session_completed on the shared bus
"""
