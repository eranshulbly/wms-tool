# -*- encoding: utf-8 -*-
"""
supply_sheet module — table DDL (registered with the schema registry).

  supply_sheet_counter  per-warehouse running number for generated supply sheets

Mirrors migration_supply_sheet.sql. That file also does an unguarded
`ALTER TABLE dealer ADD COLUMN town` which fails on second run, so it cannot simply be
re-applied; the dealer column is handled idempotently by _migrate_dealer_columns() in
shared/db_manager.py instead.
"""

from api.shared.schema_registry import register_table

register_table("supply_sheet_counter", """
CREATE TABLE IF NOT EXISTS supply_sheet_counter (
    counter_id   INT NOT NULL AUTO_INCREMENT,
    warehouse_id INT NOT NULL,
    counter      INT NOT NULL DEFAULT 0,
    PRIMARY KEY (counter_id),
    UNIQUE KEY uq_warehouse (warehouse_id),
    CONSTRAINT fk_ssc_warehouse FOREIGN KEY (warehouse_id)
        REFERENCES warehouse (warehouse_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=75)
