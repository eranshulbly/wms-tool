import React, { useEffect, useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import { compact, qty, band, pctText, amount, unitOf, unitLabel } from './format';
import { ColSearch, NoMatch } from './parts';

// The product popup (§8). Two layouts, chosen by whether the thing clicked carries a
// target:
//   targeted  -> grouped by part group, because that is where the target lives (§8.1);
//   sales-only -> flat, with the target and % columns REMOVED, not blanked (§8.2).
// Closes on ×, Escape and the backdrop (§8.4); the parent also closes it on any filter
// change, since its contents are month-specific.

const DetailModal = ({ detail, loading, scopeLabel, monthsLabel, onClose }) => {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // First-column search for each of the popup's two layouts. Held here rather than in
  // the table markup because the layout is chosen at render time.
  const [gq, setGq] = useState('');
  const [pq, setPq] = useState('');

  const d = detail;
  // Searching a part group keeps the group row AND the products beneath it, since the
  // products are the evidence for the group's number — hiding them would strand it.
  const groupRows = useMemo(() => {
    const terms = gq.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const all = d?.groups || [];
    if (!terms.length) return all;
    return all.filter((g) => {
      const hay = `${g.part_group || ''} ${g.category || ''}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [d, gq]);
  const productRows = useMemo(() => {
    const terms = pq.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const all = d?.products || [];
    if (!terms.length) return all;
    return all.filter((p) => {
      const hay = `${p.name || ''} ${p.item_code || ''} ${p.part_group || ''}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [d, pq]);

  // A single roll-up in the header is only honest when every group shares one measure;
  // the API says so with target_kind (null when they don't).
  const headTargeted = Boolean(d?.targeted && d?.target_kind);
  const headUnit = unitOf(d?.target_kind, d?.target_uom);

  // Two independent questions, which used to be one flag. A basket carries a target at
  // SCHEME level while none of the part groups beneath it carries one of its own — so it
  // has a header target and nothing to group by, and picking the grouped layout off the
  // header's target left an empty table under a correct total.
  const grouped = Number(d?.group_count) > 0;

  const sub = !d
    ? ''
    : `${scopeLabel} · ${monthsLabel} · ${
        grouped
          ? `${d.group_count} part group${d.group_count === 1 ? '' : 's'} · ${d.product_count} products`
          : `${d.product_count} products${headTargeted ? '' : ', sales only'}`
      }`;

  return (
    <div
      className="tt-overlay"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-h">
          <div>
            <h3>{d ? `${d.key}${d.mode === 'scheme' ? ' — scheme' : ''}` : 'Loading…'}</h3>
            <span className="note">{sub}</span>
          </div>
          <button type="button" className="mx" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-b">
          {loading || !d ? (
            <div className="empty">Loading…</div>
          ) : (
            <>
              {/* The header totals exist only when every group here is measured the same
                  way. Groups targeted in rupees and groups targeted in units have no
                  common total, so `mixed_targets` replaces the roll-up with a note and
                  leaves each group row to carry its own — an invented total would be the
                  one number on this screen with no defensible unit. */}
              <div className="msum">
                {headTargeted && (
                  <div>
                    <span>Target to date</span>
                    <b>{amount(d.target, headUnit)}</b>
                  </div>
                )}
                <div>
                  <span>{headTargeted ? `Sold (${unitLabel(headUnit)})` : 'Qty sold'}</span>
                  <b>{amount(headTargeted ? d.sold : d.sold_qty, headTargeted ? headUnit : 'qty')}</b>
                </div>
                {headTargeted ? (
                  <div>
                    <span>Achieved</span>
                    <b className={`pct ${band(d.pct)}`}>{pctText(d.pct)}</b>
                  </div>
                ) : (
                  <div>
                    <span>Target</span>
                    <b className="dash">
                      {d.mixed_targets ? 'set per group — see below' : 'not set — sales only'}
                    </b>
                  </div>
                )}
                <div>
                  <span>Value billed</span>
                  <b>{compact(d.value)}</b>
                </div>
              </div>

              {!d.product_count ? (
                <div className="empty">
                  <b>No products in scheme</b>
                  Nothing is mapped to this scheme for the months you picked.
                </div>
              ) : grouped ? (
                <>
                  <div className="callout">
                    Targets are set at part-group level. Each group shows its own target and
                    achievement; the products under it show what made up the sold quantity.
                    {d.mixed_targets && ' These groups are not all measured the same way — '
                      + 'each row shows the unit its own target is set in.'}
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>
                          Part group / product
                          <ColSearch value={gq} onChange={setGq} placeholder="Search part group…" />
                        </th>
                        <th className="num">Target</th>
                        <th className="num">Sold</th>
                        <th className="num">% Achieved</th>
                        <th className="num">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {!groupRows.length && (
                        <tr><td colSpan={5}><NoMatch q={gq} what="part group" /></td></tr>
                      )}
                      {groupRows.map((g) => {
                        const u = unitOf(g.target_kind, g.target_uom);
                        return (
                          <React.Fragment key={g.part_group}>
                            <tr className="grouprow">
                              <td>
                                <span className="name">{g.part_group}</span>
                                {g.category && <span className="tag soft">{g.category}</span>}
                                <br />
                                <span className="dim" style={{ fontSize: 12 }}>
                                  {g.products.length} products
                                </span>
                              </td>
                              <td className="num">
                                {g.target ? amount(g.target, u) : <span className="dash">no target</span>}
                              </td>
                              <td className="num">{amount(g.target ? g.sold : g.sold_qty, g.target ? u : 'qty')}</td>
                              <td className="num">
                                {g.target ? (
                                  <>
                                    <span className={`pct ${band(g.pct)}`}>{pctText(g.pct)}</span>
                                    <div className="bar">
                                      <i className={band(g.pct)} style={{ width: `${Math.min(100, g.pct || 0)}%` }} />
                                    </div>
                                  </>
                                ) : (
                                  <span className="dash">—</span>
                                )}
                              </td>
                              <td className="num">{compact(g.value)}</td>
                            </tr>
                            {g.products.map((p) => (
                              <tr className="subrow" key={p.item_code}>
                                <td>{p.name}</td>
                                {/* A product never carries a target or an achievement of its
                                    own — only its share of what the group sold (§8.1). The
                                    share is already computed in the group's own measure. */}
                                <td className="num"><span className="dash">—</span></td>
                                <td className="num">
                                  {amount(u === 'rs' ? p.value : u === 'litres' ? p.litres : p.sold, u)}
                                </td>
                                <td className="num"><span className="dim">{Math.round(p.share)}% of group</span></td>
                                <td className="num">{compact(p.value)}</td>
                              </tr>
                            ))}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>
                        Product
                        <ColSearch value={pq} onChange={setPq} placeholder="Search product…" />
                      </th>
                      <th>Part group</th>
                      <th>{d.mode === 'category' ? 'Scheme' : 'Category'}</th>
                      <th className="num">Qty sold</th>
                      <th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!productRows.length && (
                      <tr><td colSpan={5}><NoMatch q={pq} what="product" /></td></tr>
                    )}
                    {productRows.map((p) => (
                      <tr key={p.item_code}>
                        <td><span className="name">{p.name}</span></td>
                        <td className="dim">{p.part_group}</td>
                        <td className="dim">{(d.mode === 'category' ? p.scheme : p.category) || '—'}</td>
                        <td className="num">{qty(p.sold)}</td>
                        <td className="num">{compact(p.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* §8.3 — baskets change month to month, so a multi-month scheme popup is a
                  union of memberships and has to say so. */}
              {d.union_note && (
                <div className="callout" style={{ margin: '16px 24px 20px' }}>
                  Scheme baskets change month to month — this lists every product that was in{' '}
                  {d.key} in any of the selected months.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

DetailModal.propTypes = {
  detail: PropTypes.object,
  loading: PropTypes.bool,
  scopeLabel: PropTypes.string,
  monthsLabel: PropTypes.string,
  onClose: PropTypes.func
};

export default DetailModal;
