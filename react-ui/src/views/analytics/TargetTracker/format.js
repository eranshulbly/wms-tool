// Formatting rules from §9.3 — Indian grouping, compact currency, whole-number
// percentages. Kept in one file so a figure can never be formatted two ways.

export const compact = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)} K`;
  return `₹${Math.round(v)}`;
};

export const inr = (n) => `₹${Math.round(Number(n) || 0).toLocaleString('en-IN')}`;
export const qty = (n) => Math.round(Number(n) || 0).toLocaleString('en-IN');

// §9.2 — the only three achievement bands on the screen. null means "no target", which
// is neutral, never red: a sales-only row shown at a red 0% reads as failure (§3.3).
export const band = (p) => (p == null ? '' : p >= 90 ? 'good' : p >= 60 ? 'mid' : 'bad');

export const pctText = (p) => (p == null ? '—' : `${Math.round(p)}%`);

export const mins = (m) => {
  if (m == null) return '—';
  const h = Math.floor(m / 60);
  const x = Math.round(m % 60);
  return `${h ? `${h}h ` : ''}${String(x).padStart(2, '0')}m`;
};

// §4.2 — how the months chip reads.
export const monthsLabel = (selected, all) => {
  const chosen = all.filter((m) => selected.includes(m.id));
  const chron = [...chosen].reverse();
  if (!chron.length) return '';
  if (chron.length === 1) return chron[0].label;
  if (chron.length === all.length) return `All ${all.length} months`;
  if (chron.length === 2) return `${chron[0].label} + ${chron[1].label}`;
  return `${chron[0].label} – ${chron[chron.length - 1].label} (${chron.length} months)`;
};
