// PO pricing, mirrored from the backend (api/modules/procurement/po_builder/pricing.py)
// so a qty edit re-prices the page while you type. The server stays the source of truth
// for saving, finalising and exporting — change both files together.
//
//   DTR basic     = MRP x (1 - dtr%)
//   after std     = DTR basic x (1 - std%)
//   landing       = after std x (1 - scheme% of the line's group)
//   line value    = landing x qty;  GST = line value x the SKU's GST%
//
// Slabs are evaluated per scheme group on the group's cumulative total: qty for a QTY
// group, after-std value for a VALUE group. The highest slab reached applies.

export const unitPrices = (mrp, dtrPct, stdPct) => {
  const dtr = Number(mrp) * (1 - Number(dtrPct) / 100);
  return [dtr, dtr * (1 - Number(stdPct) / 100)];
};

export const slabFor = (total, slabs) => {
  const ordered = [...slabs].sort(
    (a, b) => Number(a.min_threshold) - Number(b.min_threshold) || a.slab_no - b.slab_no
  );
  let reached = null;
  ordered.forEach((s) => {
    if (total + 1e-9 >= Number(s.min_threshold)) reached = s;
  });
  const next = ordered.find((s) => Number(s.min_threshold) > total + 1e-9) || null;
  return reached
    ? { slabNo: reached.slab_no, pct: Number(reached.discount_pct), next }
    : { slabNo: 0, pct: 0, next };
};

const schemeKey = (no) => {
  const digits = String(no).replace(/\D/g, '');
  return digits ? Number(digits) : 1e9;
};

// lines: [{id, qty, mrp, gst_pct, scheme_group_id}], groups: {id: {scheme_no, name, basis, slabs}}
export const pricePo = (lines, groups, settings) => {
  const dtrPct = Number(settings.dtr_discount_pct);
  const stdPct = Number(settings.std_discount_pct);
  const base = {};
  const groupTotal = {};
  lines.forEach((ln) => {
    const qty = Number(ln.qty) || 0;
    const [dtr, afterStd] = unitPrices(ln.mrp, dtrPct, stdPct);
    base[ln.id] = { qty, dtr, afterStd };
    const g = groups[ln.scheme_group_id];
    if (g) {
      const amount = g.basis === 'QTY' ? qty : afterStd * qty;
      groupTotal[ln.scheme_group_id] = (groupTotal[ln.scheme_group_id] || 0) + amount;
    }
  });

  const groupPct = {};
  const summaries = {};
  Object.entries(groupTotal).forEach(([gid, total]) => {
    const g = groups[gid];
    const { slabNo, pct, next } = slabFor(total, g.slabs);
    groupPct[gid] = pct;
    summaries[gid] = {
      scheme_group_id: Number(gid),
      scheme_no: g.scheme_no,
      name: g.name,
      basis: g.basis,
      total,
      slab_no: slabNo,
      slab_count: g.slabs.length,
      slabs: [...g.slabs]
        .map((s) => ({ slab_no: s.slab_no, min_threshold: Number(s.min_threshold), discount_pct: Number(s.discount_pct) }))
        .sort((a, b) => a.min_threshold - b.min_threshold || a.slab_no - b.slab_no),
      scheme_pct: pct,
      next_slab_no: next ? next.slab_no : null,
      next_threshold: next ? Number(next.min_threshold) : null,
      next_pct: next ? Number(next.discount_pct) : null,
      gap: next ? Number(next.min_threshold) - total : null,
      line_count: 0,
      value: 0,
      saving: 0
    };
  });

  const out = {};
  const totals = { line_count: 0, qty: 0, mrp_value: 0, pre_scheme_value: 0, value: 0, gst: 0, grand_total: 0, scheme_saving: 0 };
  lines.forEach((ln) => {
    const { qty, dtr, afterStd } = base[ln.id];
    const pct = groupPct[ln.scheme_group_id] || 0;
    const landing = afterStd * (1 - pct / 100);
    const value = landing * qty;
    const gst = (value * Number(ln.gst_pct)) / 100;
    const saving = (afterStd - landing) * qty;
    out[ln.id] = {
      dtr_basic: dtr,
      after_std: afterStd,
      scheme_pct: pct,
      landing,
      pre_scheme_value: afterStd * qty,
      line_value: value,
      gst,
      line_total: value + gst,
      scheme_saving: saving
    };
    const s = summaries[ln.scheme_group_id];
    if (s) {
      s.line_count += 1;
      s.value += value;
      s.saving += saving;
    }
    totals.line_count += 1;
    totals.qty += qty;
    totals.mrp_value += Number(ln.mrp) * qty;
    totals.pre_scheme_value += afterStd * qty;
    totals.value += value;
    totals.gst += gst;
    totals.grand_total += value + gst;
    totals.scheme_saving += saving;
  });

  const groupList = Object.values(summaries).sort(
    (a, b) => schemeKey(a.scheme_no) - schemeKey(b.scheme_no) || String(a.scheme_no).localeCompare(String(b.scheme_no))
  );
  return { lines: out, groups: groupList, totals };
};

// ---- formatting -------------------------------------------------------------------

const inr2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const qtyFmt = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 });

export const money = (v) => (v === null || v === undefined ? '—' : `₹${inr2.format(v)}`);
export const money0 = (v) => (v === null || v === undefined ? '—' : `₹${inr0.format(v)}`);
export const num = (v) => (v === null || v === undefined ? '—' : qtyFmt.format(v));
export const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}%`);

// Group total / threshold in the group's own unit.
export const basisAmount = (basis, v) => (basis === 'VALUE' ? money0(v) : `${num(v)} nos`);
