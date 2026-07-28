"""
Partition Manager — monthly lifecycle for WMS partitioned tables.

Responsibilities
────────────────
1. add_next_month_partition()  — called at the start of every new month.
   Splits p_future into (new-month partition + new p_future).

2. drop_old_partitions()       — called after a successful S3 dump.
   Drops any partition whose upper bound is older than the active window.

3. list_partitions()           — returns current partition state for all
   managed tables.

Run modes
─────────
• Cron (recommended):
      # add partition on 1st of each month at 00:05
      5 0 1 * * python -m api.partition_manager add_next
      # drop old partitions after S3 dump completes
      30 2 1 * * python -m api.partition_manager drop_old

• One-shot from Flask app (called during startup in dev):
      from api.partition_manager import PartitionManager
      PartitionManager().ensure_current_month_partition()
"""

import sys
from datetime import date, datetime
from .db_manager import mysql_manager, PARTITION_COLUMN, PARTITIONED_TABLES, partition_window_start


class PartitionManager:

    # ── public API ────────────────────────────────────────────────────────────

    def ensure_current_month_partition(self):
        """
        Idempotent: ensures the current month has its own named partition on
        every managed table.  Safe to call at app startup.
        """
        today = date.today()
        for table in sorted(PARTITIONED_TABLES):
            try:
                self._ensure_month_partition(table, today.year, today.month)
            except Exception as exc:
                print(f"[PartitionManager] WARNING: could not ensure partition for "
                      f"{table} ({today.year}-{today.month:02d}): {exc}")

    def add_next_month_partition(self):
        """
        Add a named partition for next calendar month on every managed table.
        Call this on the 1st of each month (cron).
        """
        today = date.today()
        nm = today.month + 1
        ny = today.year
        if nm > 12:
            nm = 1
            ny += 1
        for table in sorted(PARTITIONED_TABLES):
            try:
                self._ensure_month_partition(table, ny, nm)
                print(f"[PartitionManager] {table}: partition for {ny}-{nm:02d} OK")
            except Exception as exc:
                print(f"[PartitionManager] ERROR on {table}: {exc}")

    def drop_old_partitions(self, dry_run: bool = False):
        """
        Drop partitions whose data is fully outside the active 4-month window.

        Only drops partitions named  p_YYYY_MM  (never p_archive / p_future).
        Before dropping, prints the partition name and row count so you can
        verify the S3 dump completed first.

        Returns list of (table, partition_name) that were (or would be) dropped.
        """
        cutoff = partition_window_start()
        dropped = []

        for table in sorted(PARTITIONED_TABLES):
            old = self._partitions_older_than(table, cutoff)
            for pname, rows in old:
                if dry_run:
                    print(f"[DRY RUN] Would drop {table} / {pname}  ({rows} rows)")
                else:
                    print(f"[PartitionManager] Dropping {table} / {pname}  ({rows} rows)…")
                    mysql_manager.execute_query(
                        f"ALTER TABLE `{table}` DROP PARTITION `{pname}`",
                        fetch=False
                    )
                    print(f"[PartitionManager] Dropped {table} / {pname}")
                dropped.append((table, pname))

        return dropped

    def list_partitions(self) -> dict:
        """
        Returns {table: [{name, rows, upper_bound}]} for every managed table.
        """
        result = {}
        for table in sorted(PARTITIONED_TABLES):
            result[table] = self._get_partition_info(table)
        return result

    # ── private helpers ───────────────────────────────────────────────────────

    def _ensure_month_partition(self, table: str, year: int, month: int):
        """
        If p_YYYY_MM does not already exist, reorganise p_future to split off
        a new named monthly partition.
        """
        pname = f"p_{year:04d}_{month:02d}"
        existing = {p['name'] for p in self._get_partition_info(table)}

        if pname in existing:
            return   # already exists

        # Upper bound of the new partition = first day of the month after
        nm = month + 1
        ny = year
        if nm > 12:
            nm = 1
            ny += 1
        upper = f"{ny:04d}-{nm:02d}-01"

        sql = (
            f"ALTER TABLE `{table}` "
            f"REORGANIZE PARTITION p_future INTO ("
            f"  PARTITION `{pname}` VALUES LESS THAN ('{upper}'), "
            f"  PARTITION p_future  VALUES LESS THAN (MAXVALUE)"
            f")"
        )
        mysql_manager.execute_query(sql, fetch=False)

    def _get_partition_info(self, table: str) -> list:
        """
        Queries INFORMATION_SCHEMA for partition metadata on `table`.
        Returns list of dicts with keys: name, rows, upper_bound.
        """
        rows = mysql_manager.execute_query(
            """
            SELECT
                PARTITION_NAME              AS name,
                TABLE_ROWS                  AS rows,
                PARTITION_DESCRIPTION       AS upper_bound
            FROM information_schema.PARTITIONS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = %s
              AND PARTITION_NAME IS NOT NULL
            ORDER BY PARTITION_ORDINAL_POSITION
            """,
            (table,)
        )
        return rows or []

    def _partitions_older_than(self, table: str, cutoff: datetime) -> list:
        """
        Returns [(partition_name, row_count)] for monthly partitions (p_YYYY_MM)
        whose entire data range falls before `cutoff`.

        A partition named p_2025_11 has data < 2025-12-01.
        If cutoff is 2025-12-01, that partition is fully outside the window.
        """
        result = []
        for info in self._get_partition_info(table):
            pname = info['name']
            if not (pname.startswith('p_') and len(pname) == 9):
                continue   # skip p_archive / p_future
            try:
                year  = int(pname[2:6])
                month = int(pname[7:9])
            except ValueError:
                continue

            # upper bound of this partition = first day of next month
            nm = month + 1
            ny = year
            if nm > 12:
                nm = 1
                ny += 1
            upper = datetime(ny, nm, 1)

            if upper <= cutoff:
                result.append((pname, info['rows']))

        return result


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli():
    import os
    # Ensure Flask app env is loaded so db_manager connects
    os.environ.setdefault('FLASK_APP', 'run.py')

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'help'
    mgr = PartitionManager()

    if cmd == 'add_next':
        mgr.add_next_month_partition()

    elif cmd == 'drop_old':
        dry = '--dry-run' in sys.argv
        dropped = mgr.drop_old_partitions(dry_run=dry)
        print(f"{'Would drop' if dry else 'Dropped'} {len(dropped)} partition(s).")

    elif cmd == 'list':
        for table, parts in mgr.list_partitions().items():
            print(f"\n{table}:")
            for p in parts:
                print(f"  {p['name']:20s}  rows={p['rows']:>8}  upper={p['upper_bound']}")

    elif cmd == 'ensure':
        mgr.ensure_current_month_partition()

    else:
        print("Usage: python -m api.partition_manager [add_next|drop_old [--dry-run]|list|ensure]")


if __name__ == '__main__':
    _cli()
