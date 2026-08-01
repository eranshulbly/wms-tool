# -*- encoding: utf-8 -*-
"""
user_auth module — table DDL (registered with the schema registry).

The v2 auth model (RBAC + refresh tokens) plus dealer location capture:

  permissions       permission catalogue, keyed by code
  role_permissions  role -> permission (many-to-many)
  user_roles        user -> role (many-to-many; supersedes the legacy users.role string)
  refresh_tokens    issued refresh tokens, hashed, revocable
  dealer_location_submissions  field-captured dealer GPS + photo, pending admin approval

The first four mirror migration_v2_api.sql exactly, so a deployment that already ran that
migration sees a no-op here. They are registered rather than left in the .sql file because
that migration also carries ALTERs written against production's older table lineage (e.g.
`ALTER TABLE dealer MODIFY activated_on`), which fail on a schema built fresh from
create_all_tables() — so it cannot be applied wholesale to a new database.

The legacy `users.role` VARCHAR is still what login and permissions.py read. user_roles is
the forward-looking model used by rbac.py; both exist during the migration.
"""

from api.shared.schema_registry import register_table

register_table("permissions", """
CREATE TABLE IF NOT EXISTS permissions (
    permission_id INT AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(100) NOT NULL UNIQUE,
    description   VARCHAR(255) NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=70)

register_table("role_permissions", """
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    INDEX idx_rp_permission (permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=71)

register_table("user_roles", """
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     INT NOT NULL,
    role_id     INT NOT NULL,
    assigned_by INT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    INDEX idx_ur_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=72)

register_table("refresh_tokens", """
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  VARCHAR(255) NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    revoked_at  DATETIME NULL,
    user_agent  VARCHAR(255) NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_refresh_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=73)


# Reconstructed from its read/write sites (router_v1.py submits, router_dealer_locations.py
# lists/reviews) — unlike the tables above this one has no DDL in any migration file.
# `photo_path` is NULLed on review: the image is evidence for the approval decision only and
# is deleted from disk once acted on, so the column must stay nullable.
register_table("dealer_location_submissions", """
CREATE TABLE IF NOT EXISTS dealer_location_submissions (
    submission_id INT AUTO_INCREMENT PRIMARY KEY,
    dealer_id     INT NOT NULL,
    submitted_by  INT NULL,
    latitude      DECIMAL(10,7) NULL,
    longitude     DECIMAL(10,7) NULL,
    accuracy_m    FLOAT NULL,
    photo_path    VARCHAR(255) NULL,
    mime_type     VARCHAR(64) NULL,
    size_bytes    INT NULL,
    note          VARCHAR(500) NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    reviewed_by   INT NULL,
    reviewed_at   DATETIME NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dls_dealer (dealer_id),
    INDEX idx_dls_status (status),
    INDEX idx_dls_submitted_by (submitted_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
""", order=74)
