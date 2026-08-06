import React, { useEffect, useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import { compact, qty, band, pctText } from './format';
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

  const sub = !d
    ? ''
    : `${scopeLabel} · ${monthsLabel} · ${
        d.targeted
          ? `${d.group_count} part group${d.group_count === 1 ? '' : 's'} · ${d.product_count} products`
          : `${d.product_count} products, sales only`
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
              <div className="msum">
                {d.targeted && (
                  <div>
                    <span>Target qty to date</span>
                    <b>{qty(d.target_qty)}</b>
                  </div>
                )}
                <div>
                  <span>Qty sold</span>
                  <b>{qty(d.sold)}</b>
                </div>
                {d.targeted ? (
                  <div>
                    <span>Achieved</span>
                    <b className={`pct ${band(d.pct)}`}>{pctText(d.pct)}</b>
                  </div>
                ) : (
                  <div>
                    <span>Target</span>
                    <b className="dash">not set — sales only</b>
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
              ) : d.targeted ? (
                <>
                  <div className="callout">
                    Targets are set at part-group level. Each group shows its own target and
                    achievement; the products under it show what made up the sold quantity.
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>
                          Part group / product
                          <ColSearch value={gq} onChange={setGq} placeholder="Search part group…" />
                        </th>
                        <th className="num">Target qty</th>
                        <th className="num">Qty sold</th>
                        <th className="num">% Achieved</th>
                        <th className="num">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {!groupRows.length && (
                        <tr><td colSpan={5}><NoMatch q={gq} what="part group" /></td></tr>
                      )}
                      {groupRows.map((g) => (
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
                              {g.target_qty ? qty(g.target_qty) : <span className="dash">no target</span>}
                            </td>
                            <td className="num">{qty(g.sold)}</td>
                            <td className="num">
                              {g.target_qty ? (
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
                                  own — only its share of what the group sold (§8.1). */}
                              <td className="num"><span className="dash">—</span></td>
                              <td className="num">{qty(p.sold)}</td>
                              <td className="num"><span className="dim">{Math.round(p.share)}% of group</span></td>
                              <td className="num">{compact(p.value)}</td>
                            </tr>
                          ))}
                        </React.Fragment>
                      ))}
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
