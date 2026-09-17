import { useMemo, useState } from 'react';

/**
 * Per-column free-text search, AND-combined across columns — the pattern Batch Costing
 * established first: one small input per column header, each filtering that column
 * alone, so "narrow to this dealer AND this product" doesn't need a single combined
 * search box to guess which term means which column.
 *
 * `rows` should already reflect any OTHER filtering (date range, tabs, band chips) —
 * this only adds a further, purely textual narrowing on top, and rebuilds itself
 * whenever the upstream rows change.
 *
 * `renderFn(type, value)` is the table's own cell-rendering function, reused here so a
 * column is searchable by what's actually on screen (a formatted date, "₹ 1,234.00")
 * as readily as by its raw stored value — a search that only matched raw values would
 * make "1234" find a money cell but "1,234" or "₹" would not.
 */
export function useColumnSearch(rows, columns, renderFn) {
  const [filters, setFilters] = useState({});

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
    if (!active.length) return searchable.map((s) => s.row);
    return searchable
      .filter((s) => active.every(([k, term]) => (s.text[k] || '').includes(term.trim().toLowerCase())))
      .map((s) => s.row);
  }, [searchable, filters]);

  const setFilter = (key, value) => setFilters((f) => ({ ...f, [key]: value }));
  const clearFilters = () => setFilters({});
  const hasActive = Object.values(filters).some((v) => (v || '').trim());

  return { filters, setFilter, clearFilters, hasActive, visible };
}

export default useColumnSearch;
