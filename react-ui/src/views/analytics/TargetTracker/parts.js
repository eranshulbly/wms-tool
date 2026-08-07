import React, { useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import { compact, band, pctText, mins, amount, unitOf, unitLabel } from './format';

// Small shared pieces of the Target Tracker. Markup and class names follow the
// prototype; the behaviour rules they enforce are noted where they matter.

// ---------------------------------------------------------------------------
// First-column search
//
// Filtering is client-side over the rows already on screen. It deliberately does NOT
// re-query: the figures stay computed over the scope the user chose, so searching can
// only ever hide rows, never change a number or a percentage.
// ---------------------------------------------------------------------------

export const useRowFilter = (items, fields) => {
  const [q, setQ] = useState('');
  const rows = useMemo(() => {
    const terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return items;
    // Word-by-word, so "auto point badaun" matches regardless of field order.
    return items.filter((o) => {
      const hay = fields.map((f) => String(o[f] ?? '')).join(' ').toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [items, fields, q]);
  return [rows, q, setQ];
};

export const ColSearch = ({ value, onChange, placeholder }) => (
  <input
    className="colsearch"
    type="search"
    value={value}
    placeholder={placeholder}
    autoComplete="off"
    // The row is clickable on these tables — typing must not drill in.
    onClick={(e) => e.stopPropagation()}
    onChange={(e) => onChange(e.target.value)}
  />
);
ColSearch.propTypes = { value: PropTypes.string, onChange: PropTypes.func, placeholder: PropTypes.string };

// Shown when a search empties an otherwise non-empty table — distinct from "no data",
// and it always says what was searched for.
export const NoMatch = ({ q, what }) => (
  <div className="empty">
    <b>No {what} matches &quot;{q}&quot;</b>
    Try a shorter search, or clear it to see every row.
  </div>
);
NoMatch.propTypes = { q: PropTypes.string, what: PropTypes.string };

export const Pct = ({ pct }) => (
  <>
    <span className={`pct ${band(pct)}`}>{pctText(pct)}</span>
    <div className="bar">
      <i className={band(pct)} style={{ width: `${Math.min(100, pct || 0)}%` }} />
    </div>
  </>
);
Pct.propTypes = { pct: PropTypes.number };

// §3.3 — a row with no target shows the words "no target" and an em-dash, never 0 and
// never a red 0%.
//
// `unit` is 'rs' | 'litres' | 'qty' and comes from the target itself, never from the
// column it sits in — a scheme table now holds rupee-targeted baskets alongside
// unit-targeted part groups.
export const TargetCell = ({ value, unit }) =>
  (value ? <>{amount(value, unit)}</> : <span className="dash">no target</span>);
TargetCell.propTypes = { value: PropTypes.number, unit: PropTypes.string };

export const Empty = ({ title, help }) => (
  <div className="empty">
    <b>{title}</b>
    {help}
  </div>
);
Empty.propTypes = { title: PropTypes.string, help: PropTypes.string };

// `onClick` is optional — a card only becomes interactive when there is somewhere to go,
// so a tile with nothing behind it never advertises a click that does nothing.
export const Kpi = ({ label, value, foot, onClick }) => (
  <div
    className={`kpi${onClick ? ' kpi-click' : ''}`}
    {...(onClick ? {
      role: 'button',
      tabIndex: 0,
      onClick,
      onKeyDown: (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick())
    } : {})}
  >
    <div className="lab">{label}</div>
    <div className="val">{value}</div>
    <div className="foot">{foot}</div>
  </div>
);
Kpi.propTypes = {
  label: PropTypes.string,
  value: PropTypes.node,
  foot: PropTypes.node,
  onClick: PropTypes.func
};

// One category's sales + target for a row. A rupee-targeted category compares money to
// money; a quantity-targeted one compares units to units, or litres to litres — never a
// mix, and never a figure that adds categories together.
//
// The unit comes from the CELL first: the axis kind describes the column, but an
// untargeted cell in a targeted column has no unit of its own and falls back to it.
export const CatCells = ({ cell, kind }) => {
  const c = cell || {};
  const unit = unitOf(c.target_kind || kind, c.target_uom);
  const sold = unit === 'rs' ? c.sales : unit === 'litres' ? c.litres_sold : c.qty_sold;
  return (
    <>
      <td className="num">{amount(sold, unit)}</td>
      <td className="num"><TargetCell value={c.target} unit={unit} /></td>
      <td className="num">{c.target ? <Pct pct={c.pct} /> : <span className="dash">—</span>}</td>
    </>
  );
};
CatCells.propTypes = { cell: PropTypes.object, kind: PropTypes.string };

// The header block a category contributes to any table: sales / target / % achieved,
// grouped under the category name so the three are never read as scope-wide figures.
// The first column is captioned with the unit it is actually measured in, so an Oil
// column reads "Oil litres" rather than an ambiguous "Oil qty".
export const CatHead = ({ axis }) => (
  <>
    {axis.map((a) => (
      <React.Fragment key={a.category}>
        <th className="num">{a.category} {unitLabel(unitOf(a.target_kind, a.target_uom))}</th>
        <th className="num">Target</th>
        <th className="num">%</th>
      </React.Fragment>
    ))}
  </>
);
CatHead.propTypes = { axis: PropTypes.array };

// Searching an executive/dealer row covers the secondary line too — a dealer's town and
// its executive live there, and those are what people actually type.
const RANK_FIELDS = ['name', 'sub'];

// Executive / dealer table (§5.3 case A, §6.1). Clickable only when a single month is
// selected — drill-down is single-month only (§10.1). One sales/target/% block per
// category; there is deliberately no combined column.
export const RankTable = ({ head, items, axis, clickable, onPick }) => {
  const [rows, q, setQ] = useRowFilter(items, RANK_FIELDS);
  if (!items.length) return <Empty title="Nothing to show" help="Loosen a filter or pick another month." />;
  const cols = axis || [];
  return (
    <table>
      <thead>
        <tr>
          <th>
            {head}
            <ColSearch value={q} onChange={setQ} placeholder={`Search ${head.toLowerCase()}…`} />
          </th>
          <CatHead axis={cols} />
          <th className="num">Visits</th>
          <th className="num">Avg time</th>
        </tr>
      </thead>
      <tbody>
        {!rows.length && (
          <tr>
            <td colSpan={2 + cols.length * 3}><NoMatch q={q} what={head.toLowerCase()} /></td>
          </tr>
        )}
        {rows.map((o) => (
          <tr
            key={o.id}
            className={clickable ? 'clickable' : undefined}
            onClick={clickable && onPick ? () => onPick(o) : undefined}
          >
            <td>
              <span className="name">{o.name}</span>
              <br />
              <span className="dim" style={{ fontSize: 12 }}>{o.sub}</span>
            </td>
            {cols.map((a) => (
              <CatCells key={a.category} cell={o.cats?.[a.category]} kind={a.target_kind} />
            ))}
            <td className="num">{o.visits}</td>
            <td className="num">{mins(o.avg_minutes)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};
RankTable.propTypes = {
  head: PropTypes.string,
  items: PropTypes.array,
  axis: PropTypes.array,
  clickable: PropTypes.bool,
  onPick: PropTypes.func
};

const QTY_FIELDS = ['name'];

// Category / scheme table (§6.2). Every row opens the popup.
export const QtyTable = ({ mode, items, onOpen }) => {
  const [rows, q, setQ] = useRowFilter(items, QTY_FIELDS);
  if (!items.length) {
    return (
      <Empty
        title={mode === 'scheme' ? 'No products in scheme' : 'Nothing to show'}
        help={
          mode === 'scheme'
            ? 'Nothing is mapped to a scheme for the months you picked.'
            : 'No sales or targets for the current filters.'
        }
      />
    );
  }
  return (
    <table>
      {/* The Target and Sold columns hold MIXED units — Basket 1 is targeted in rupees
          and the PG part groups in pieces, and both are schemes. The header is therefore
          neutral and every cell carries its own unit; a column captioned "Target qty"
          would be a lie on two rows out of three. Value stays a separate rupee column so
          a unit-targeted row still shows what it was worth. */}
      <thead>
        <tr>
          <th>
            {mode === 'category' ? 'Category' : 'Scheme'}
            <ColSearch value={q} onChange={setQ} placeholder={`Search ${mode === 'category' ? 'categories' : 'schemes'}…`} />
          </th>
          <th className="num">Target</th>
          <th className="num">Sold</th>
          <th className="num">% Achieved</th>
          <th className="num">Value</th>
        </tr>
      </thead>
      <tbody>
        {!rows.length && (
          <tr><td colSpan={5}><NoMatch q={q} what={mode === 'category' ? 'category' : 'scheme'} /></td></tr>
        )}
        {rows.map((o) => {
          const unit = unitOf(o.target_kind, o.target_uom);
          return (
            <tr key={o.key} className="clickable" onClick={() => onOpen(o)} title="See products">
              <td>
                <span className="name">{o.name}</span>
                {/* §3.3 — sales-only rows are tagged, so a blank target is never read as a miss. */}
                {!o.target && <span className="tag soft">sales only</span>}
                <br />
                <span className="dim" style={{ fontSize: 12 }}>
                  {mode === 'category'
                    ? `${o.groups} part groups · ${o.skus} SKUs`
                    : `${o.skus} SKUs in scheme this period`}
                </span>
              </td>
              <td className="num"><TargetCell value={o.target} unit={unit} /></td>
              {/* Sold is shown in the unit the target is in, so the two read as a pair.
                  With no target there is nothing to match, so it falls back to units. */}
              <td className="num">{amount(o.sold, o.target ? unit : 'qty')}</td>
              <td className="num">{o.target ? <Pct pct={o.pct} /> : <span className="dash">—</span>}</td>
              <td className="num">{compact(o.value)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};
QtyTable.propTypes = { mode: PropTypes.string, items: PropTypes.array, onOpen: PropTypes.func };
