-- Refresh-token hardening.
--
-- Idempotent: every statement checks information_schema first, matching the
-- convention in api/shared/db_manager.py, so this can be re-applied safely.
--
-- 1. `revoked_reason` — why a token stopped being valid. Without it a revoked row
--    is indistinguishable from a rotated one, and the single case that matters
--    most (a token replayed after it was already spent, i.e. a possible theft) is
--    invisible after the fact.
-- 2. Indexes for the two queries added alongside: revoking a user's whole token
--    family on reuse detection, and the periodic purge.

SET @db := DATABASE();

-- ---- 1. revoked_reason -----------------------------------------------------
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE refresh_tokens
       ADD COLUMN revoked_reason VARCHAR(32) NULL
       COMMENT ''rotated | logout | reuse_detected | admin''',
    'SELECT ''refresh_tokens.revoked_reason already present'''
  )
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'refresh_tokens'
    AND COLUMN_NAME = 'revoked_reason'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---- 1b. replaced_by -------------------------------------------------------
-- Links a rotated token to the one that superseded it. Needed by the grace
-- window: when a client retries a refresh whose response it never received, the
-- successor it never saw has to be revoked as we mint its replacement, or a live
-- token nobody holds is left behind for the rest of its 14 days.
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE refresh_tokens ADD COLUMN replaced_by BIGINT NULL',
    'SELECT ''refresh_tokens.replaced_by already present'''
  )
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'refresh_tokens'
    AND COLUMN_NAME = 'replaced_by'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---- 2. Index for family revocation ---------------------------------------
-- Reuse detection revokes every live token for one user, so that lookup wants
-- (user_id, revoked_at) rather than the existing user_id-only index.
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'CREATE INDEX idx_refresh_user_live ON refresh_tokens (user_id, revoked_at)',
    'SELECT ''idx_refresh_user_live already present'''
  )
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'refresh_tokens'
    AND INDEX_NAME = 'idx_refresh_user_live'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---- 3. Index for the purge -----------------------------------------------
-- The table gains a row per login AND per rotation. With 30-minute access tokens
-- that is roughly 48 rows per rep per day, so it needs both a sweep and an index
-- to sweep on.
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'CREATE INDEX idx_refresh_expires ON refresh_tokens (expires_at)',
    'SELECT ''idx_refresh_expires already present'''
  )
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db
    AND TABLE_NAME = 'refresh_tokens'
    AND INDEX_NAME = 'idx_refresh_expires'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
