# -*- encoding: utf-8 -*-
"""
sales module — table DDL (registered with the schema registry).

The field-sales visit log:

  dealer_visits            check-in/check-out per executive per dealer
"""

from api.shared.schema_registry import register_table


# Field-sales visit log — one row per check-in, closed out by check_out_at.
# DDL kept identical to migration_v2_api.sql so an existing deployment that already ran
# that migration is a no-op here rather than a conflict.
register_table("dealer_visits", """
CREATE TABLE IF NOT EXISTS dealer_visits (
    visit_id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id              INT NOT NULL,
    dealer_id            INT NOT NULL,
    company_id           INT,
    check_in_at          DATETIME NOT NULL,
    check_in_latitude    DECIMAL(10,7),
    check_in_longitude   DECIMAL(10,7),
    check_in_accuracy_m  FLOAT,
    check_out_at         DATETIME,
    check_out_latitude   DECIMAL(10,7),
    check_out_longitude  DECIMAL(10,7),
    check_out_accuracy_m FLOAT,
    status               VARCHAR(20) NOT NULL DEFAULT 'active',
    notes                TEXT,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_dv_user (user_id),
    INDEX idx_dv_dealer (dealer_id),
    INDEX idx_dv_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=64)
