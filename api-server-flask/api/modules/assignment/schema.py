# -*- encoding: utf-8 -*-
"""
assignment module — table DDL (registered with the schema registry).

Scaffolded from wms-v2-backend's assignment module, adapted to MySQL. This is
the warehouse work queue: jobs auto-assigned to available, eligible workers.
Job creation is event-driven (see handlers.py). References to users/warehouses
are plain IDs — no cross-module foreign keys.

The assignment engine itself is not implemented yet; these tables and the event
subscriptions are the scaffolding for it.
"""

from api.shared.schema_registry import register_table

register_table("jobs", """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       BIGINT NOT NULL AUTO_INCREMENT,
    job_type     VARCHAR(20) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',
    source_type  VARCHAR(40),
    source_id    BIGINT,
    warehouse_id BIGINT NOT NULL,
    priority     INT NOT NULL DEFAULT 0,
    assigned_to  BIGINT,
    assigned_by  BIGINT,
    assigned_at  DATETIME,
    started_at   DATETIME,
    completed_at DATETIME,
    notes        TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id),
    INDEX idx_jobs_queue (warehouse_id, status, job_type),
    INDEX idx_jobs_assignee (assigned_to, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=60)

register_table("job_status_history", """
CREATE TABLE IF NOT EXISTS job_status_history (
    id          BIGINT NOT NULL AUTO_INCREMENT,
    job_id      BIGINT NOT NULL,
    from_status VARCHAR(20),
    to_status   VARCHAR(20) NOT NULL,
    changed_by  BIGINT,
    note        TEXT,
    changed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_job_hist_job (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=61)

register_table("worker_availability", """
CREATE TABLE IF NOT EXISTS worker_availability (
    id            BIGINT NOT NULL AUTO_INCREMENT,
    user_id       BIGINT NOT NULL,
    warehouse_id  BIGINT NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'offline',
    active_job_id BIGINT,
    last_seen_at  DATETIME,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_worker_user (user_id),
    INDEX idx_worker_wh_status (warehouse_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=62)

register_table("allocation_policies", """
CREATE TABLE IF NOT EXISTS allocation_policies (
    policy_id    BIGINT NOT NULL AUTO_INCREMENT,
    warehouse_id BIGINT NOT NULL,
    job_type     VARCHAR(20) NOT NULL,
    weight       INT NOT NULL DEFAULT 1,
    start_time   TIME,
    end_time     TIME,
    days_of_week VARCHAR(20),
    is_active    TINYINT(1) NOT NULL DEFAULT 1,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (policy_id),
    INDEX idx_alloc_wh (warehouse_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=63)
