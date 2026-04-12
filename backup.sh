#!/usr/bin/env bash
# =============================================================================
# WMS Tool - Automated MySQL Backup Script
# Usage:
#   Manual:  ./backup.sh
#   Cron:    0 2 * * * /opt/wms-tool/backup.sh >> /var/log/wms-backup.log 2>&1
#
# Keeps 7 daily + 4 weekly backups. Optionally uploads to object storage.
# =============================================================================
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAILY=7
KEEP_WEEKLY=4

# Load env vars if file exists
if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-warehouse_management}"
DB_USERNAME="${DB_USERNAME:-root}"
DB_PASS="${DB_PASS:-}"

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
DAY_OF_WEEK=$(date +"%u")   # 1=Monday … 7=Sunday
BACKUP_FILE="$BACKUP_DIR/wms_${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u)] Starting backup: $BACKUP_FILE"

# ── Dump database ─────────────────────────────────────────────────────────────
# Uses the running Docker container if available, else direct mysqldump
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "wms_mysql"; then
    docker exec wms_mysql mysqldump \
        -u "$DB_USERNAME" \
        -p"$DB_PASS" \
        --single-transaction \
        --routines \
        --triggers \
        --add-drop-table \
        "$DB_NAME" | gzip > "$BACKUP_FILE"
else
    MYSQL_PWD="$DB_PASS" mysqldump \
        -h "$DB_HOST" \
        -P "$DB_PORT" \
        -u "$DB_USERNAME" \
        --single-transaction \
        --routines \
        --triggers \
        --add-drop-table \
        "$DB_NAME" | gzip > "$BACKUP_FILE"
fi

BACKUP_SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date -u)] Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# ── Weekly backup copy (every Sunday) ────────────────────────────────────────
if [[ "$DAY_OF_WEEK" == "7" ]]; then
    WEEKLY_FILE="$BACKUP_DIR/weekly/wms_${DB_NAME}_week_$(date +%Y-W%V).sql.gz"
    mkdir -p "$BACKUP_DIR/weekly"
    cp "$BACKUP_FILE" "$WEEKLY_FILE"
    echo "[$(date -u)] Weekly backup saved: $WEEKLY_FILE"
fi

# ── Rotate old daily backups ──────────────────────────────────────────────────
echo "[$(date -u)] Rotating daily backups (keeping $KEEP_DAILY days)..."
ls -t "$BACKUP_DIR"/wms_*.sql.gz 2>/dev/null | tail -n +"$((KEEP_DAILY + 1))" | xargs -r rm -f

# ── Rotate old weekly backups ─────────────────────────────────────────────────
if [[ -d "$BACKUP_DIR/weekly" ]]; then
    ls -t "$BACKUP_DIR/weekly"/wms_*.sql.gz 2>/dev/null | tail -n +"$((KEEP_WEEKLY + 1))" | xargs -r rm -f
fi

# ── Optional: Upload to DigitalOcean Spaces (or S3) ──────────────────────────
# Uncomment and configure after installing s3cmd: apt install s3cmd
# s3cmd put "$BACKUP_FILE" s3://your-bucket-name/wms-backups/

echo "[$(date -u)] Backup rotation done."
echo "[$(date -u)] Disk usage: $(du -sh "$BACKUP_DIR" | cut -f1)"
