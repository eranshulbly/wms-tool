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
