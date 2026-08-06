import React, { useEffect } from 'react';
import PropTypes from 'prop-types';
import { compact, qty } from './format';
import { Pct, TargetCell, Empty } from './parts';

// The bifurcation behind the "Total sales Other" card. That card headlines a single
// rupee total because rupees are the one thing its categories share; this popup is where
// the total is broken back out, each category against its OWN target and scale — rupee
// for some, quantity for others — which is exactly why the card itself carries no
// target and no percentage.
//
// Closes on ×, Escape and the backdrop, matching DetailModal (§8.4).

const OtherCategoriesModal = ({ categories, total, scopeLabel, monthsLabel, onClose }) => {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const rows = categories || [];

  return (
    <div
      className="tt-overlay"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label="Other categories breakdown">
        <div className="modal-h">
          <div>
            <h3>Other categories</h3>
            <span className="note">
              {scopeLabel} · {monthsLabel} · {rows.length} categor{rows.length === 1 ? 'y' : 'ies'} · {compact(total)} in total
            </span>
          </div>
          <button type="button" className="mx" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-b">
          {!rows.length ? (
            <Empty title="Nothing to show" help="No sales outside Parts for the current filters." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th className="num">Sales</th>
                  <th className="num">Qty sold</th>
                  <th className="num">Target</th>
                  <th className="num">% Achieved</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.category}>
                    <td>
                      <span className="name">{c.category}</span>
                      {/* Say which scale this row's target is on, so a quantity target is
                          never read as a rupee one. */}
                      {!c.target_kind && <span className="tag soft">sales only</span>}
                      {c.target_kind === 'qty' && <span className="tag soft">qty target</span>}
                    </td>
                    <td className="num">{compact(c.sales)}</td>
                    <td className="num">{qty(c.qty_sold)}</td>
                    <td className="num">
                      {c.target_kind === 'qty'
                        ? <TargetCell value={c.target} />
                        : <TargetCell value={c.target} money />}
                    </td>
                    <td className="num">
                      {c.target_kind ? <Pct pct={c.pct} /> : <span className="dash">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td><span className="name">Total</span></td>
                  <td className="num">{compact(total)}</td>
                  {/* Quantity, target and % are deliberately blank: these categories are
                      measured on different scales, so neither adds up to anything real. */}
                  <td className="num"><span className="dash">—</span></td>
                  <td className="num"><span className="dash">—</span></td>
                  <td className="num"><span className="dash">—</span></td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

OtherCategoriesModal.propTypes = {
  categories: PropTypes.array,
  total: PropTypes.number,
  scopeLabel: PropTypes.string,
  monthsLabel: PropTypes.string,
  onClose: PropTypes.func
};

export default OtherCategoriesModal;
