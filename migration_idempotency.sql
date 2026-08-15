-- Idempotency keys.
--
-- The problem: on a field link a write can commit server-side while its response
-- is lost in transit. The app sees a failure, the rep taps submit again, and a
-- second identical order is created. That makes automatic retry — the whole point
-- of the outbox — unsafe, because retrying is exactly how you get duplicates.
--
-- A key is generated ONCE, when the rep hits submit, and reused for every attempt
-- of that same intent. The first attempt to arrive does the work and stores its
-- response; every later attempt replays that response instead of acting again.
--
-- Idempotent: re-applying is safe.

SET @db := DATABASE();

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    "CREATE TABLE idempotency_keys (
       idem_key     CHAR(36) NOT NULL PRIMARY KEY,
       user_id      INT NOT NULL,
       endpoint     VARCHAR(64) NOT NULL,
       -- in_progress -> completed. A row is claimed before the work starts, so a
       -- duplicate arriving mid-flight is told to wait rather than racing it.
       state        VARCHAR(16) NOT NULL DEFAULT 'in_progress',
       status_code  SMALLINT NULL,
       response     MEDIUMTEXT NULL,
       created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
       completed_at DATETIME NULL,
       INDEX idx_idem_created (created_at),
       INDEX idx_idem_user (user_id)
     ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci",
    "SELECT 'idempotency_keys already present'"
  )
  FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'idempotency_keys'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
