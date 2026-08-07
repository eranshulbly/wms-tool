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

// Litres carry one decimal: pack sizes are 0.8 L and 0.9 L, so rounding to whole litres
// would show a dealer who sold ten 900 ml bottles as having sold 9 against a 9 L target
// one time and 8 the next, depending on the mix.
export const litres = (n) => `${(Number(n) || 0).toLocaleString('en-IN', {
  minimumFractionDigits: 0, maximumFractionDigits: 1 })} L`;

// A target's unit, from the two fields the API attaches to every targeted figure.
// 'value' is always rupees; a quantity target is litres only when it says so.
export const unitOf = (kind, uom) => (kind === 'value' ? 'rs' : uom === 'litres' ? 'litres' : 'qty');

// One figure, rendered in the unit its own target is set in.
//
// Targets are no longer all of one kind: the baskets are set in rupees, the PG part
// groups in pieces and Oil in litres, and rows carrying different units sit in the same
// table. Every figure therefore formats from the unit that travelled with it — the table
// it happens to be in is not evidence of anything.
export const amount = (n, unit) =>
  (unit === 'rs' ? compact(n) : unit === 'litres' ? litres(n) : qty(n));

// The word for a unit, for column headers and captions.
export const unitLabel = (unit) =>
  (unit === 'rs' ? 'sales' : unit === 'litres' ? 'litres' : 'qty');

// The headline figure for a category cell: whatever its own target is measured in, so
// the number and the percentage beneath it are always the same pair.
//
// A cell with NO target falls back to rupees. That is deliberate — rupees are the only
// measure every category shares, and an untargeted tile showing a bare unit count would
// invite comparison with a targeted one beside it that counts something else.
export const sold = (c) => {
  const u = unitOf(c?.target_kind, c?.target_uom);
  if (!c?.target_kind) return compact(c?.sales);
  return amount(u === 'rs' ? c.sales : u === 'litres' ? c.litres_sold : c.qty_sold, u);
};

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
