# Per-company schema routing

**Status:** design · **Model:** one backend instance ⇄ one company ⇄ one MySQL schema (database), on a shared MySQL server.

## Goal

Today a single database, `warehouse_management`, holds every company's rows, separated by a
`company_id` column on ~25 tables. We are moving to **one schema (database) per company** on the
**same MySQL server**, with the backend **deployed separately per company**. Each deployment must
have its repo/query layer talk to exactly one schema.

## The enabling fact

The data layer already makes this almost free:

- `MySQLManager` (`api/shared/db_manager.py`) binds its schema in the connection DSN —
  `pymysql.connect(database=os.getenv('DB_NAME', 'warehouse_management'))`. The schema is fixed for
  the life of each pooled connection.
- **Every SQL statement is bare / schema-implicit.** There are zero `warehouse_management.<table>`
  qualifiers in the codebase. Tables resolve against the connection's default schema.
- All migrations introspect via `WHERE TABLE_SCHEMA = DATABASE()` and alter bare `` `{table}` ``, so
  they follow whatever schema the connection is bound to.
- Partitioning (`partition_filter`, `partition_manager`) is a date predicate only — no schema baked in.

Therefore **switching the connection's default schema is sufficient**, and the selector is already a
single env var: `DB_NAME`. No repo-layer rewrite, no per-query qualification.

## Design

### 1. Config is the selector

`DB_NAME` becomes the canonical per-deployment **schema** selector; introduce `DB_SCHEMA` as a clearer
alias (fall back to `DB_NAME` for compatibility). `DB_HOST / DB_PORT / DB_USERNAME / DB_PASS` stay
shared — same server, same credentials, different default schema.

```
# Cadila deployment          # Hero deployment
DB_HOST=mysql (shared)       DB_HOST=mysql (shared)
DB_SCHEMA=cadila             DB_SCHEMA=hero
COMPANY_KEY=cadila           COMPANY_KEY=hero
```

`COMPANY_KEY` names the tenant for the handful of code paths that currently dispatch by matching the
**company row's name** (`product_pack._PROFILES`, `dms.COMPANY_DMS_BUILDERS`). After the split each
deployment is single-company, so those stop string-matching a row and read `COMPANY_KEY` (or, in the
Cadila-only build, hardcode the Cadila profile/builder).

### 2. Startup guard

At boot, after the pool is built, assert and log the binding:

```
SELECT DATABASE()  ->  must equal DB_SCHEMA, non-empty
log: "DB ready: schema=<db> company=<COMPANY_KEY>"
```

Fail fast if the schema is empty or does not match config — this prevents a misconfigured Cadila
instance from silently writing into the Hero schema.

### 3. Provisioning a schema

Bootstrap already runs once at app start (`create_app → initialize_database → create_all_tables`)
against `DB_NAME`. So a fresh deployment pointed at a new, empty schema will create and migrate it on
first boot — **provided the schema (database) exists** and the DB user may write it. Two supported
paths:

- **Auto:** grant the app user `CREATE`, and add a pre-bootstrap step
  `CREATE DATABASE IF NOT EXISTS <schema> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` before
  `USE`/connect. Then boot creates the tables.
- **Explicit (preferred for prod):** a `flask create-schema <name>` command / script that creates the
  database and runs `create_all_tables()` + all `_migrate_*` against a connection bound to it. This
  keeps DDL privileges out of the running app.

The migration order dependencies documented in `create_all_tables` must be preserved per schema — they
already are, because the same functions run; only the target schema differs.

### 4. Repo layer — unchanged

`BaseRepository` captures the global `mysql_manager` in `__init__`; direct importers use the same
singleton. Because the singleton connects to the configured schema, **no repository or model changes
are required.** (Repos are instantiated per-call, so none freeze a stale manager.)

### 5. company_id scoping — kept, demoted

Within a single-company schema the `company_id` predicate is redundant but harmless. We **keep the
columns and the `WHERE company_id = …` filters** (removing them is a 25-table migration with no
upside) and instead:

- seed **exactly one** `company` row per schema (the deployment's company);
- replace `DEFAULT_COMPANY = 1` (Hero) with "the deployment's single company," resolved once from
  that row (or from `COMPANY_KEY`);
- drop the vestigial `company_schema_mappings` table (unused; superseded by this model).

### 6. Out of scope

Cross-schema reporting (reading Hero + Cadila together) is intentionally unsupported in this model —
each app sees one company. If ever needed: a separate read-only connection with schema-qualified SQL,
or a reporting warehouse. Not built now.

## What this is NOT

- Not per-request schema selection. One instance serves one schema, chosen at boot. (Per-request
  routing is feasible — `current_user['company_ids']` exists — but would need per-schema pools and a
  `before_request` binding, and is unnecessary for separate deployments.)
- Not a code change to how queries are written. They stay bare-named.

## Change surface (this design)

| Change | File(s) |
|---|---|
| `DB_SCHEMA` alias + startup guard/log | `api/shared/db_manager.py`, `api/config.py` |
| `CREATE DATABASE` provisioning / `create-schema` command | new small script / CLI |
| `COMPANY_KEY`, replace `DEFAULT_COMPANY` | `api/shared/db_manager.py` (seed), `field_sales/service.py` |
| Drop `company_schema_mappings` | `api/shared/db_manager.py` |
| Per-deployment env | `.env`, `docker-compose*.yml` |
