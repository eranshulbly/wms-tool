// Ported verbatim from wms-v2-frontend/test/analytics_grouping_test.dart —
// these 8 cases ARE the spec for the card-grouping arithmetic.
import { groupSuggestions } from './suggestionGrouping';

// A part in `group` (carrying that group's shared figures) under `scheme`.
const part = (code, { group, scheme, sold = 0, target = 0, last6m = 0 } = {}) => ({
  item_code: code,
  part_group: group ?? null,
  scheme: scheme ?? null,
  group_sold: sold,
  group_target: target,
  group_gap: target - sold,
  group_last6m: last6m,
});

test('scheme PG cards by part group, one card each', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Clutch', scheme: 'PG', sold: 2, target: 10 }),
    part('b', { group: 'Clutch', scheme: 'PG', sold: 2, target: 10 }),
    part('c', { group: 'Spark Plug', scheme: 'PG', sold: 1, target: 4 }),
  ]);
  expect(groups.map((g) => g.name)).toEqual(['Clutch', 'Spark Plug']);
  // Two parts share one group: the target counts ONCE, not twice.
  expect(groups[0].groupTarget).toBe(10);
  expect(groups[0].groupSold).toBe(2);
  expect(groups[0].parts.length).toBe(2);
  expect(groups[0].partGroupCount).toBe(1);
});

test('non-PG scheme merges its part groups into a single card', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Ball Bearing', scheme: 'Basket 1', sold: 3, target: 10 }),
    part('b', { group: 'Ball Bearing', scheme: 'Basket 1', sold: 3, target: 10 }),
    part('c', { group: 'Belt', scheme: 'Basket 1', sold: 5, target: 20 }),
  ]);
  expect(groups.length).toBe(1);
  expect(groups[0].name).toBe('Basket 1');
  expect(groups[0].partGroupCount).toBe(2);
  // Summed over DISTINCT part groups: 10 + 20, not 10 + 10 + 20.
  expect(groups[0].groupTarget).toBe(30);
  expect(groups[0].groupSold).toBe(8);
  expect(groups[0].groupGap).toBe(22);
  expect(groups[0].parts.length).toBe(3);
});

test('pct is recomputed from card totals', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Ball Bearing', scheme: 'Basket 1', sold: 5, target: 10 }),
    part('b', { group: 'Belt', scheme: 'Basket 1', sold: 5, target: 30 }),
  ]);
  expect(groups[0].groupPct).toBe(25.0); // 10 / 40
});

test('zero target yields null pct rather than dividing by zero', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Belt', scheme: 'Basket 1', sold: 0, target: 0 }),
  ]);
  expect(groups[0].groupPct).toBeNull();
});

test('PG and non-PG schemes coexist, API order preserved', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Ball Bearing', scheme: 'Basket 1', sold: 1, target: 9 }),
    part('b', { group: 'Clutch', scheme: 'PG', sold: 2, target: 8 }),
    part('c', { group: 'Belt', scheme: 'Basket 1', sold: 1, target: 5 }),
  ]);
  // Basket 1 keeps first-appearance position even though 'c' arrives last.
  expect(groups.map((g) => g.name)).toEqual(['Basket 1', 'Clutch']);
  expect(groups[0].groupTarget).toBe(14);
});

test('missing scheme falls back to part-group carding', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Clutch', sold: 1, target: 5 }),
    part('b', { group: 'Clutch', scheme: '  ', sold: 1, target: 5 }),
  ]);
  expect(groups.length).toBe(1);
  expect(groups[0].name).toBe('Clutch');
  expect(groups[0].groupTarget).toBe(5);
});

test('null part group and null scheme land in one Other parts card', () => {
  const groups = groupSuggestions([
    { item_code: 'x', part_group: null, scheme: null, group_sold: 0, group_target: 3, group_gap: 3 },
  ]);
  expect(groups.length).toBe(1);
  expect(groups[0].name).toBe('Other parts');
});

test('scheme match is case insensitive for PG', () => {
  const groups = groupSuggestions([
    part('a', { group: 'Clutch', scheme: 'pg', sold: 1, target: 5 }),
  ]);
  expect(groups[0].name).toBe('Clutch');
});
