# WMS Tool — Backend Context (AI handoff)

This is the **v1 WMS tool** backend: Flask-RESTX + MySQL (raw SQL / active-record,
no ORM). In mid-2026 it was restructured into a **modular monolith** modelled on the
sibling rebuild `~/Desktop/Projects/Ebco/wms-v2-backend` (FastAPI + Postgres), but
kept on its own Flask/MySQL stack. Read this file first for a complete map.

## Stack
Python 3.9, Flask + Flask-RESTX (single `Api` singleton, `@rest_api.route`), PyMySQL
connection pool, Flask-Admin (server-rendered admin panel), gunicorn. MySQL 8, several
high-volume tables RANGE-partitioned by date. Runs via Docker Compose.

## Architecture: modular monolith
One deployable app, split into domain **modules** under `api/modules/`. Rules borrowed
from v2:
1. **A module owns its tables.** Its `models.py` holds the active-record classes; its
   DDL is created at startup (legacy DDL still in `shared/db_manager.py`; newer modules
   register DDL via `shared/schema_registry.py`).
2. **No cross-module foreign keys.** Modules reference each other's rows by plain ID.
3. **Cross-module calls go through a module's `service.py`**, not by importing another
   module's models.
4. **Reactions go through the event bus** (`shared/events.py`) — publisher never imports
   subscriber. Swappable for SNS/SQS later.

### Layout
```
api/
  shared/            cross-cutting infra (imported by modules; imports no module)
    db_manager.py       MySQLManager pool, partition_filter, legacy create-all DDL
    schema_registry.py  register_table(); newer modules own their DDL here
    events.py           EventBus + singleton event_bus (ported from v2)
    auth.py             token_required / active_required / upload_permission_required
    logging.py exceptions.py partition_manager.py base_repository.py
    upload_base.py upload_factory.py upload_utils.py upload_validators.py upload_types.py
  modules/
    user_auth/     users, roles, role_order_states, role_uploads, user_warehouse_company,
                   jwt_token_blocklist; auth login/register; router_admin.py (admin JSON API)
    catalog/       company, dealer, product (SKU master) + product/dealer business & upload
    order/         potential_order(_product), order(_product), order_state(_history);
                   upload + lifecycle + state_machine + dashboard listing (router_dashboard.py)
    invoice/       invoice, invoice_processing_config; upload/classification/stats
    inventory/     warehouse (live) + SCAFFOLD: stock, inventory_transactions, picklists,
                   picklist_items (schema.py, from v2)
    assignment/    SCAFFOLD: jobs, job_status_history, worker_availability,
                   allocation_policies; events.py + handlers.py (log-only, from v2)
    eway_bill/     transport_routes, customer_route_mappings, daily_route_manifests,
                   company_schema_mappings; routes + JSON generation
    supply_sheet/  supply_sheet_counter + PDF generation
```

### Compatibility shims (transitional)
`api/models.py`, `api/db_manager.py`, `api/core/*`, `api/partition_manager.py`,
`api/business/`, `api/services/`, `api/repositories/`, `api/validation/`,
`api/permissions.py` still exist as **thin re-export shims** so older import paths keep
working. Real code lives in `shared/` and `modules/`. Remove shims once all imports point
at the new homes.

### Assembly
`api/__init__.py` `create_app()` → `routes/__init__.py::register_all_routes()` imports each
module's `router*.py` (route paths unchanged from before the restructure) → registers the
assignment event handlers → `initialize_database()` creates legacy + registered tables →
mounts Flask-Admin. `gunicorn api:app`.

## Order lifecycle
`Open → Picking → Packed → Invoiced → Dispatch Ready → Completed`. Single source of truth:
`modules/order/state_machine.py`.

## Notable 2026 changes
- **Boxes removed.** The `box` / `order_box` / `box_product` tables and all box-building
  are gone (`migration_drop_boxes.sql`). Packing is now a pure state transition;
  `box_count` remains a plain integer on orders. Products live in `catalog`.
- **inventory / assignment scaffolded** from v2 schemas (tables + status endpoints +
  event wiring) — engines not implemented yet.
- Frontend landing is a **tile launcher** (`react-ui/src/views/launcher/Launcher.js`):
  Order Tracking, E-Way Bill, Supply Sheet, Admin.

## Adding a feature
Pick the owning module → add table (register DDL in its `schema.py` or add to db_manager)
→ model in `models.py` → logic in `service.py`/`business.py` → endpoints in `router.py`
(import into `register_all_routes`) → cross-module reactions via `shared/events.py`.
Update this file when structure/modules change.
