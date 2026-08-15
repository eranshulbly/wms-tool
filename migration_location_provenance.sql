-- Location provenance and capture time on orders.
--
-- Two gaps this closes.
--
-- 1. The app falls back to the OS's last-known position when a live fix is not
--    available (common indoors). That fallback was sent exactly like a live
--    reading, so a coordinate hours old and from another town was
--    indistinguishable from one taken at the shop door. Every order ever raised
--    has this ambiguity; `location_source` and `location_age_s` remove it going
--    forward.
--
-- 2. Orders are now queued on the device and sent when a connection allows, so
--    "when the server received it" is no longer "when the rep raised it". The
--    existing `location_captured_at` column is what should hold the latter, but
--    service_v1.create_order was writing server time into it — so it duplicated
--    created_at and said nothing. No schema change is needed for that; the fix is
--    in the service, which now stores the device's capture time. `created_at`
--    remains receipt time, and the pair is what makes the gap visible.
--
--    This matters beyond audit: `location_captured_at` is the order's business
--    date. An order taken at 23:50 offline and synced at 00:15 otherwise lands on
--    the wrong day and mis-attributes that day's target.
--
-- Nothing is rejected on these columns. They are recorded so anomalies can be
-- found, not so orders can be refused in the field.
--
-- Idempotent: re-applying is safe.

SET @db := DATABASE();

-- Column name -> definition. Applied one at a time because information_schema
-- has to be consulted per column.
SET @tbl := 'submitted_orders';

-- location_source: 'gps' | 'last_known'
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE submitted_orders ADD COLUMN location_source VARCHAR(16) NULL
       COMMENT 'gps = live reading; last_known = OS cached position'",
    "SELECT 'location_source already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = @tbl AND COLUMN_NAME = 'location_source'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- location_age_s: how stale the reading was when captured.
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE submitted_orders ADD COLUMN location_age_s INT NULL
       COMMENT 'seconds between the OS taking the reading and the rep submitting'",
    "SELECT 'location_age_s already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = @tbl AND COLUMN_NAME = 'location_age_s'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- location_is_mocked: Android's own flag for a mock-location app.
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    "ALTER TABLE submitted_orders ADD COLUMN location_is_mocked TINYINT(1) NULL",
    "SELECT 'location_is_mocked already present'")
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = @tbl AND COLUMN_NAME = 'location_is_mocked'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- No column is added for capture time: `location_captured_at` already exists and
-- is exactly that. It was being written with server time; the service now writes
-- the device's.

-- Finding the orders worth a second look — a stale fix, a mocked one, or a long
-- gap between capture and receipt. The gap query compares location_captured_at
-- against created_at, so it wants an index on the former.
SET @sql := (
  SELECT IF(COUNT(*) = 0,
    'CREATE INDEX idx_orders_captured ON submitted_orders (location_captured_at)',
    "SELECT 'idx_orders_captured already present'")
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = @db AND TABLE_NAME = @tbl AND INDEX_NAME = 'idx_orders_captured'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
