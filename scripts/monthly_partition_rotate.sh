#!/usr/bin/env bash
# =============================================================================
# WMS Tool - Monthly Partition Rotation
# Run on the 1st of each month (cron):
#   5 0 1 * * /opt/wms-tool/scripts/monthly_partition_rotate.sh >> /var/log/wms-partitions.log 2>&1
#
# What it does:
#   1. Adds next month's named partition to all 10 partitioned tables
#   2. Lists partitions older than the 4-month window (for S3 dump + drop)
# =============================================================================
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-db}"
DB_PASS="${DB_PASS:-root-pw}"
DB_NAME="${DB_NAME:-warehouse_management}"
MYSQL="docker exec -i $DB_CONTAINER mysql -u root -p$DB_PASS $DB_NAME"

echo "============================================="
echo " WMS Partition Rotation  $(date -u)"
echo "============================================="

# ── Step 1: Calculate next month ─────────────────────────────────────────────
NEXT_YEAR=$(date -d "+1 month" +%Y 2>/dev/null || date -v+1m +%Y)
NEXT_MONTH=$(date -d "+1 month" +%m 2>/dev/null || date -v+1m +%m)
NEXT_UPPER_YEAR=$(date -d "+2 months" +%Y 2>/dev/null || date -v+2m +%Y)
NEXT_UPPER_MONTH=$(date -d "+2 months" +%m 2>/dev/null || date -v+2m +%m)

PART_NAME="p_${NEXT_YEAR}_${NEXT_MONTH}"
UPPER_BOUND="${NEXT_UPPER_YEAR}-${NEXT_UPPER_MONTH}-01"

echo ">>> Adding partition $PART_NAME (data < $UPPER_BOUND) to all tables..."

TABLES=(
    "potential_order"
    "potential_order_product"
    "invoice"
    "order_state_history"
    "\`order\`"
    "order_product"
    "order_box"
    "box_product"
    "upload_batches"
    "jwt_token_blocklist"
)

for TABLE in "${TABLES[@]}"; do
    SQL="ALTER TABLE ${TABLE} REORGANIZE PARTITION p_future INTO (
        PARTITION ${PART_NAME}  VALUES LESS THAN ('${UPPER_BOUND}'),
        PARTITION p_future      VALUES LESS THAN (MAXVALUE)
    );"
    echo "  $TABLE → $PART_NAME"
    echo "$SQL" | $MYSQL 2>&1 | grep -v Warning || echo "  [WARN] $TABLE may already have $PART_NAME"
done

# ── Step 2: Show partitions outside the 4-month window (ready to dump+drop) ──
WINDOW_START=$(date -d "-4 months" +%Y-%m-01 2>/dev/null || date -v-4m +%Y-%m-01)

echo ""
echo ">>> Partitions OLDER than 4-month window (cutoff: $WINDOW_START):"
echo ">>> Dump these to S3 before dropping."
echo ""

$MYSQL 2>/dev/null -e "
SELECT
    TABLE_NAME,
    PARTITION_NAME,
    TABLE_ROWS                AS approx_rows,
    PARTITION_DESCRIPTION     AS upper_bound
FROM information_schema.PARTITIONS
WHERE TABLE_SCHEMA = DATABASE()
  AND PARTITION_NAME REGEXP '^p_[0-9]{4}_[0-9]{2}$'
  AND PARTITION_DESCRIPTION <= '$WINDOW_START'
ORDER BY TABLE_NAME, PARTITION_ORDINAL_POSITION;" 2>&1 | grep -v Warning

echo ""
echo ">>> To drop old partitions after S3 dump, run:"
echo "    $0 --drop-old"
echo "============================================="
