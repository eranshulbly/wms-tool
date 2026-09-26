# -*- encoding: utf-8 -*-
"""diagnostics module — DDL. This module owns this table.

Not partitioned and deliberately small. This is a debugging aid with a retention
cap, not a record anyone should come to depend on: `trim()` keeps it bounded so a
handheld stuck in a reconnect loop cannot fill the disk on a box that has 19GB
free and four other applications on it.
"""

from api.shared.schema_registry import register_table

# How many rows to keep. Roughly a few days of one handset chattering, or a couple
# of hours of a whole fleet — either way enough to debug with and small enough to
# scan without an index on anything but time.
MAX_ROWS = 20000

register_table("app_diag_log", """
CREATE TABLE IF NOT EXISTS app_diag_log (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    -- One id per app launch, generated on the device. Ties a run's events
    -- together when several handsets report at once.
    session_id  VARCHAR(64) NOT NULL,
    -- AppConfig.buildStamp. The whole reason this table exists: it answers
    -- "which build is that handset actually running" without touching it.
    build       VARCHAR(64) NULL,
    device      VARCHAR(64) NULL,
    platform    VARCHAR(64) NULL,
    -- NULL before sign-in. A failed login is exactly the case that must still be
    -- reportable, so the endpoint does not require a token.
    user_id     INT NULL,
    user_email  VARCHAR(128) NULL,
    level       VARCHAR(16) NOT NULL DEFAULT 'info',   -- info | warn | error
    event       VARCHAR(80) NOT NULL,                  -- e.g. home.render
    detail      TEXT NULL,                             -- JSON, truncated by the router
    client_at   VARCHAR(40) NULL,                      -- device clock, as sent
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_diag_created (created_at),
    INDEX idx_diag_session (session_id),
    INDEX idx_diag_event (event)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=90)
