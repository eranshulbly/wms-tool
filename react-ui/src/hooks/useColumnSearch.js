import { useMemo, useState } from 'react';

/**
 * Per-column free-text search plus click-to-sort, AND-combined across columns — the
 * pattern Batch Costing established first for search (one small input per header cell,
 * each filtering that column alone) and Stock Movement established for sort (click a
 * header, click again to reverse it).
 *
 * `rows` should already reflect any OTHER filtering (date range, tabs, band chips) —
 * this only adds a further, purely textual narrowing plus an ordering on top, and
 * rebuilds itself whenever the upstream rows change.
 *
 * `renderFn(type, value)` is the table's own cell-rendering function, reused here so a
 * column is searchable by what's actually on screen (a formatted date, "₹ 1,234.00")
 * as readily as by its raw stored value — a search that only matched raw values would
 * make "1234" find a money cell but "1,234" or "₹" would not.
 *
 * `initialSort` is an optional `{ key, dir }` to sort by before the user clicks
 * anything — omit it to leave rows in whatever order the caller already provides.
 */
export function useColumnSearch(rows, columns, renderFn, initialSort = null) {
  const [filters, setFilters] = useState({});
  const [sort, setSort] = useState(initialSort);

  const searchable = useMemo(
    () =>
      rows.map((row) => ({
        row,
        text: columns.reduce((acc, c) => {
          const raw = row[c.key];
          const rendered = renderFn ? renderFn(c.type, raw) : raw;
          acc[c.key] = `${raw ?? ''} ${rendered ?? ''}`.toLowerCase();
          return acc;
        }, {}),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, columns]
  );

  const visible = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => (v || '').trim());
    let out = !active.length
      ? searchable.map((s) => s.row)
      : searchable
          .filter((s) => active.every(([k, term]) => (s.text[k] || '').includes(term.trim().toLowerCase())))
          .map((s) => s.row);

    if (sort) {
      const { key, dir } = sort;
      const sign = dir === 'asc' ? 1 : -1;
      // Nulls always sort last, in either direction: a missing figure is not a small
      // one, and letting it float to the top would bury the rows the sort was for.
      out = [...out].sort((a, b) => {
        const x = a[key];
        const y = b[key];
        if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1;
        if (y === null || y === undefined) return -1;
        if (typeof x === 'number' && typeof y === 'number') return (x - y) * sign;
        return String(x).localeCompare(String(y)) * sign;
      });
    }
    return out;
  }, [searchable, filters, sort]);

  const setFilter = (key, value) => setFilters((f) => ({ ...f, [key]: value }));
  const clearFilters = () => setFilters({});
  const hasActive = Object.values(filters).some((v) => (v || '').trim());
  const toggleSort = (key) =>
    setSort((s) => ({ key, dir: s && s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }));

  return { filters, setFilter, clearFilters, hasActive, visible, sort, toggleSort };
}

export default useColumnSearch;
