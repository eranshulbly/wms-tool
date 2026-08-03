// Card-grouping layer for dealer part suggestions.
//
// The backend (api/modules/sales/analytics/service.py :: dealer_suggestions)
// returns a FLAT list of parts, each carrying its part group's shared figures
// (group_sold / group_target / group_gap / group_last6m repeated on every part
// in that group). This layer groups the flat list into collapsible cards —
// presentation only; which parts are suggested is decided by the backend.
//
// Grouping key:
//   scheme 'PG' (case-insensitive) or null/blank  -> one card per PART GROUP
//   any other scheme (Basket 1/2, Ancillary, …)   -> one card per SCHEME
//   null part group with no scheme                -> a single "Other parts" card
// API ordering (hardest-behind first) is preserved by first appearance.
//
// CRITICAL: a card that spans several part groups must sum sold/target/gap over
// the DISTINCT part groups it contains — NOT over its parts. The API repeats a
// group's figures on every part, so summing per part multiplies the target by
// the part count. We keep one representative part ("head") per distinct part
// group and sum over those. groupPct is recomputed from the card totals.
//
// Ported from wms-v2-frontend/lib/widgets/analytics.dart (groupSuggestions /
// SuggestionGroup). See suggestionGrouping.test.js for the spec.

const nz = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

function makeGroup(schemeKey, name, head) {
  const heads = new Map();
  heads.set(head.part_group ?? '', head);
  return { schemeKey, name, parts: [head], _heads: heads };
}

function addPart(g, p) {
  g.parts.push(p);
  const k = p.part_group ?? '';
  if (!g._heads.has(k)) g._heads.set(k, p); // first part in a group is its head
}

function sumHeads(g, field) {
  let a = 0;
  for (const h of g._heads.values()) a += nz(h[field]);
  return a;
}

function finalize(g) {
  const groupSold = sumHeads(g, 'group_sold');
  const groupTarget = sumHeads(g, 'group_target');
  const groupGap = sumHeads(g, 'group_gap');
  const groupLast6m = sumHeads(g, 'group_last6m');
  return {
    schemeKey: g.schemeKey,
    name: g.name,
    parts: g.parts,
    groupSold,
    groupTarget,
    groupGap,
    groupLast6m,
    // Recomputed from the card totals; null (render "—") when there is no target.
    groupPct: groupTarget <= 0 ? null : (groupSold / groupTarget) * 100,
    partGroupCount: g._heads.size,
  };
}

/**
 * Group a flat suggestion list (grow[] or new_opportunity[]) into cards.
 * @param {Array<object>} parts backend suggestion rows
 * @returns {Array<object>} cards in first-appearance (hardest-behind-first) order
 */
/**
 * Group the target sheet (grow[]) into the rows the Targets panel renders.
 *
 * The API already returns one row per TARGETED UNIT — a part group under scheme 'PG',
 * the whole scheme otherwise — so this only decides nesting, never which units exist:
 *
 *   scheme 'PG'  -> ONE expandable parent ("PG · 9 part groups"), sold and target
 *                   summed across its groups, with one child row per part group;
 *   anything else -> a single flat row, nothing beneath it.
 *
 * PG is the only expandable row. API order (widest gap first) is preserved by first
 * appearance, and the PG parent takes the position of its first member.
 *
 * @param {Array<object>} units grow[] rows from the API
 * @returns {Array<object>} rows in API order; PG carries `children`
 */
export function groupTargets(units) {
  const rows = [];
  let pg = null;
  for (const u of units || []) {
    const isPg = (u.scheme ?? '').trim().toUpperCase() === 'PG';
    if (!isPg) {
      rows.push({
        key: `u:${u.scheme ?? ''}:${u.part_group ?? ''}`,
        // Non-PG units are labelled by the unit itself: the scheme, or the category
        // for a category-level target (the API names it for us).
        name: u.part_group || u.scheme || 'Other parts',
        sold: nz(u.group_sold),
        target: nz(u.group_target),
        expandable: false,
        children: []
      });
      continue;
    }
    if (!pg) {
      pg = { key: 'scheme:PG', name: 'PG', sold: 0, target: 0, expandable: true, children: [] };
      rows.push(pg); // holds the position of the first PG unit, so ordering survives
    }
    pg.sold += nz(u.group_sold);
    pg.target += nz(u.group_target);
    pg.children.push({
      key: `pg:${u.part_group ?? ''}`,
      name: u.part_group || 'Other parts',
      sold: nz(u.group_sold),
      target: nz(u.group_target)
    });
  }
  return rows;
}

export function groupSuggestions(parts) {
  const byKey = new Map();
  const order = [];
  for (const p of parts || []) {
    const scheme = (p.scheme ?? '').trim();
    const byPartGroup = scheme === '' || scheme.toUpperCase() === 'PG';
    const key = byPartGroup ? `pg:${p.part_group ?? ''}` : `sc:${scheme}`;
    const name = byPartGroup ? (p.part_group ?? 'Other parts') : scheme;

    const g = byKey.get(key);
    if (!g) {
      const ng = makeGroup(key, name, p);
      byKey.set(key, ng);
      order.push(ng);
    } else {
      addPart(g, p);
    }
  }
  return order.map(finalize);
}

export default groupSuggestions;
